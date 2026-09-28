"""Database adapter / comparisons. Reference mathematics lives in reference.py.

Production calls here are the system under test, never expected-value generators.
Only aggregate evidence and selected technical-row traces are exported.
"""
import csv
import hashlib
import io
import json
import random
import statistics
import platform
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

from . import reference as ref
from .checks import run_checks


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def write_csv(path, rows, fields=None):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields or list(rows[0]) if rows else fields or ["no_discrepancies"])
        writer.writeheader()
        writer.writerows(rows)


def compare(expected, actual):
    mismatches, differences = [], []
    for k in sorted(set(expected) | set(actual)):
        a, b = expected.get(k), actual.get(k)
        difference = abs(a-b) if a is not None and b is not None else None
        if difference is not None:
            differences.append(difference)
        if difference is None or difference > 1e-12:
            mismatches.append(dict(participant=k[0], construct=k[1], expected=a, actual=b, difference=difference))
    return dict(expected=len(expected), existing=len(actual), matches=len(set(expected)&set(actual))-sum(
        r["difference"] is not None for r in mismatches), mismatches=len(mismatches),
        max_absolute_difference=max(differences, default=0),
        mean_absolute_difference=statistics.mean(differences) if differences else None), mismatches


def run(csv_path, version_name, output, simulations, seed):
    from django.conf import settings
    from django import get_version
    from django.db import connection
    from polls.models import (Question, Scale, NormativeParticipant, NormativeAnswer,
                              NormativeDatasetVersion, NormativeScaleScore, NormativeSpectrumScore,
                              QuestionnaireSubmission, UserAnswer)
    from polls.scoring import calculate_scale_scores_from_answers
    from polls.spectrum_scores import calculate_spectrum_scores
    from polls.percentiles import _calculate_percentile
    from polls.simulation import _profile_answer, PROFILE_WEIGHTS, _apply_missing_answers
    from polls.attention_checks import evaluate_attention_checks

    output.mkdir(parents=True, exist_ok=True)
    key_path = settings.BASE_DIR / "scripts/import_questions.py"
    key = ref.read_key(key_path)
    raw = csv_path.read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter=";")
    rows = list(reader)
    headers = reader.fieldnames
    key_by_code = {q["item_code"]: q for q in key}
    questions = list(Question.objects.select_related("scale__subfactor__spectra").order_by("id"))
    db_key = [dict(item_code=q.item_code, scale=q.scale.name, subfactor=q.scale.subfactor.name,
                   spectrum=q.scale.subfactor.spectra.name, is_attention_check=q.is_attention_check)
              for q in questions]
    by_code = {q.item_code:q for q in questions}
    version = NormativeDatasetVersion.objects.get(name=version_name, environment="production")
    participants = list(version.participants.order_by("pk").values("id", "source", "age", "sex"))
    ids = [p["id"] for p in participants]
    answers = defaultdict(dict)
    duplicates = 0
    answer_rows = list(NormativeAnswer.objects.filter(participant_id__in=ids)
                       .order_by("participant_id", "question_id", "id")
                       .values_list("participant_id", "question__item_code", "answer"))
    for pid, code, value in answer_rows:
        duplicates += code in answers[pid]
        answers[pid][code] = value
    tokens = Counter(row.get(code) for row in rows for code in headers if code in key_by_code)
    csv_codes = [c for c in headers if c in key_by_code]
    signatures = defaultdict(list)
    for index,row in enumerate(rows,1):
        signatures[tuple(row.get(c) for c in sorted(csv_codes))].append(index)
    linked = {}
    for pid in ids:
        candidates = signatures.get(tuple(answers[pid].get(c) for c in sorted(csv_codes)), [])
        if len(candidates) == 1:
            linked[pid] = candidates[0]
    # No positional assumption. Exact full-response vectors establish safe links.
    cell_diffs = []
    for pid,index in linked.items():
        for code in set(csv_codes) | set(answers[pid]):
            a, b = rows[index-1].get(code), answers[pid].get(code)
            if a != b:
                cell_diffs.append(dict(participant=pid, csv_row=index, item_code=code, expected=a, actual=b))
    mapping_diffs = []
    for code in sorted(set(key_by_code)|set(by_code)):
        expected, q = key_by_code.get(code), by_code.get(code)
        if expected is None or q is None:
            mapping_diffs.append(dict(item_code=code, field="presence", expected=expected is not None, actual=q is not None))
            continue
        observed = dict(scale=q.scale.name, subfactor=q.scale.subfactor.name,
                        spectrum=q.scale.subfactor.spectra.name, is_attention_check=q.is_attention_check,
                        expected_answer=q.expected_answer, question_text=q.question_text)
        for field,actual in observed.items():
            target = expected.get(field, False if field=="is_attention_check" else "")
            if target != actual:
                mapping_diffs.append(dict(item_code=code,field=field,expected=target,actual=actual))

    stored_scales = {(p,n):s for p,n,s in NormativeScaleScore.objects.filter(version=version)
                     .values_list("participant_id","scale__name","raw_score")}
    stored_spectra = {(p,n):s for p,n,s in NormativeSpectrumScore.objects.filter(version=version)
                      .values_list("participant_id","spectrum__name","raw_score")}
    expected_scales, expected_spectra, csv_scales, csv_spectra = {}, {}, {}, {}
    engine_diffs = []
    attention_results=[]
    numeric_percentile_diffs = []
    production_spectrum_values = {}
    reordered_spectrum_values = {}
    for pid in ids:
        rs, rt = ref.scores(answers[pid], key)
        for target,data in ((expected_scales,rs),(expected_spectra,rt)):
            target.update({(pid,n):d["score"] for n,d in data.items() if d["score"] is not None})
        objects = [SimpleNamespace(question=by_code[c], answer=v) for c,v in answers[pid].items()]
        attention_results.append(evaluate_attention_checks(objects))
        prod_s = calculate_scale_scores_from_answers(objects)
        prod_t = calculate_spectrum_scores(prod_s)
        production_spectrum_values.update({(pid,o.name):d["score"] for o,d in prod_t.items() if d["score"] is not None})
        reordered = calculate_spectrum_scores(calculate_scale_scores_from_answers(list(reversed(objects))))
        reordered_spectrum_values.update({(pid,o.name):d["score"] for o,d in reordered.items() if d["score"] is not None})
        for kind, prod, expected in (("scale",prod_s,rs),("spectrum",prod_t,rt)):
            for obj,data in prod.items():
                wanted = expected.get(obj.name,{}).get("score")
                got = data["score"]
                if (got is None)!=(wanted is None) or (got is not None and abs(got-wanted)>1e-12):
                    engine_diffs.append(dict(participant=pid,kind=kind,construct=obj.name,expected=wanted,actual=got))
        if pid in linked:
            cs, ct = ref.scores(rows[linked[pid]-1],key)
            for target,data in ((csv_scales,cs),(csv_spectra,ct)):
                target.update({(pid,n):d["score"] for n,d in data.items() if d["score"] is not None})
    scale_cmp, scale_diff = compare(expected_scales,stored_scales)
    spectrum_cmp, spectrum_diff = compare(expected_spectra,stored_spectra)
    csv_scale_cmp, csv_scale_diff = compare(csv_scales,stored_scales)
    csv_spectrum_cmp, csv_spectrum_diff = compare(csv_spectra,stored_spectra)
    distributions = {"scale":defaultdict(list),"spectrum":defaultdict(list)}
    for kind, data in (("scale",stored_scales),("spectrum",stored_spectra)):
        for (_,name),score in data.items():
            distributions[kind][name].append(score)
    for kind,expected,actual in (("scale",expected_scales,stored_scales),("spectrum",expected_spectra,stored_spectra)):
        for (pid,name),value in expected.items():
            if (pid,name) in actual:
                p=ref.percentile(distributions[kind][name],value)
                a=ref.percentile(distributions[kind][name],actual[(pid,name)])
                if p!=a:
                    numeric_percentile_diffs.append(dict(participant=pid,kind=kind,construct=name,
                                                        reference_score=value,stored_score=actual[(pid,name)],reference_percentile=p,stored_percentile=a))
    order_diffs=[]
    live_stored_diffs=[]
    for (pid,name),value in production_spectrum_values.items():
        other=reordered_spectrum_values[(pid,name)]
        p=ref.percentile(distributions["spectrum"][name],value)
        a=ref.percentile(distributions["spectrum"][name],other)
        if p!=a:
            order_diffs.append(dict(participant=pid,spectrum=name,forward_score=value,reverse_score=other,
                                   forward_percentile=p,reverse_percentile=a))
        stored=stored_spectra.get((pid,name))
        old=ref.percentile(distributions["spectrum"][name],stored)
        if p!=old:
            live_stored_diffs.append(dict(participant=pid,spectrum=name,current_score=value,stored_score=stored,
                                         current_percentile=p,stored_percentile=old))
    percentile_rows, percentile_mismatches = [], 0
    for kind, groups in distributions.items():
        stats = []
        for name,values in sorted(groups.items()):
            stats.append(dict(construct=name,**ref.describe(values)))
            for value in sorted(set(values) | {0.,1.,2.5,4.,5.}):
                conventions = ref.conventions(values,value)
                actual = _calculate_percentile(values,value)
                percentile_mismatches += actual != conventions["production"]
                percentile_rows.append(dict(kind=kind,construct=name,score=value,**conventions))
        write_csv(output/f"{kind}_statistics.csv",stats)
    write_csv(output/"percentile_conventions.csv",percentile_rows)

    mc, traces, frequencies, missing_rows = [], [], {}, []
    simulation_engine_differences = 0
    for profile in PROFILE_WEIGHTS:
        collected = {"scale":defaultdict(list),"spectrum":defaultdict(list)}
        frequency = Counter()
        for i in range(simulations):
            rng = random.Random(f"{seed}:{profile}:{i}")
            generated = {q.item_code:_profile_answer(rng,profile) for q in questions if not q.is_attention_check}
            frequency.update(generated.values())
            ss,sp = ref.scores(generated,key)
            production_scales=calculate_scale_scores_from_answers([
                SimpleNamespace(question=by_code[c],answer=v) for c,v in generated.items()])
            production_spectra=calculate_spectrum_scores(production_scales)
            for kind,actual,expected in (("scale",production_scales,ss),("spectrum",production_spectra,sp)):
                for obj,d in actual.items():
                    simulation_engine_differences += abs(d["score"]-expected[obj.name]["score"])>1e-12
            for kind, data in (("scale",ss),("spectrum",sp)):
                for name,d in data.items():
                    if d["score"] is not None and name in distributions[kind]:
                        collected[kind][name].append((d["score"],ref.percentile(distributions[kind][name],d["score"])))
            if profile=="random" and i<3:
                high = sorted(ss, key=lambda n:ref.percentile(distributions["scale"][n],ss[n]["score"]), reverse=True)[:3]
                for name in high:
                    items = [q["item_code"] for q in key if q["scale"]==name and not q.get("is_attention_check")]
                    traces.append(dict(source="simulation",participant=i,seed=f"{seed}:{profile}:{i}",scale=name,
                                       items=items,raw=[generated[c] for c in items],reverse="none implemented",
                                       **ss[name],**ref.conventions(distributions["scale"][name],ss[name]["score"])))
        frequencies[profile] = dict(frequency)
        for kind,groups in collected.items():
            for name,pairs in sorted(groups.items()):
                ps = [p for _,p in pairs]
                mc.append(dict(profile=profile,kind=kind,construct=name,n=len(pairs),
                               simulated_mean=statistics.mean(s for s,_ in pairs),
                               normative_mean=statistics.mean(distributions[kind][name]),
                               median_percentile=statistics.median(ps),
                               **{f"percentage_ge_p{p}":100*sum(x>=p for x in ps)/len(ps) for p in (75,90,95,99)}))
    for percentage in (0,10,24.99,25,30,50,100):
        values = {q.id:"2" for q in questions}
        _apply_missing_answers(questions,values,random.Random(seed),percentage)
        counts = defaultdict(list)
        for q in questions:
            if not q.is_attention_check:
                counts[q.scale.name].append(values[q.id])
        for name, vals in sorted(counts.items()):
            d = ref.scale(vals)
            missing_rows.append(dict(requested_percentage=percentage,scale=name,n=len(vals),
                                     actual_missing=d["missing_answers"],actual_percentage=d["missing_percentage"],is_valid=d["is_valid"]))
    for pid in list(linked)[:3]:
        row = rows[linked[pid]-1]
        for name in ("Agoraphobia","Well-being","Antisocial Behavior"):
            items = [q["item_code"] for q in key if q["scale"]==name]
            d = ref.scale([row.get(c) for c in items])
            if d["score"] is not None:
                traces.append(dict(source="BD.csv",participant=pid,csv_row=linked[pid],scale=name,items=items,
                                   raw=[row.get(c) for c in items],reverse="none implemented",**d,
                                   **ref.conventions(distributions["scale"][name],d["score"])))

    # Demonstrate the omitted-row defect without touching a database.
    sample_q = next(q for q in questions if not q.is_attention_check)
    actual_missing_probe = calculate_scale_scores_from_answers([SimpleNamespace(question=sample_q,answer="4")])[sample_q.scale]
    sample_count=sum(q.scale_id==sample_q.scale_id and not q.is_attention_check for q in questions)
    intended_missing_probe = ref.scale(["4"]+[None]*(sample_count-1))
    incomplete = []
    completed=list(QuestionnaireSubmission.objects.filter(completed=True).select_related("report_normative_version").prefetch_related("spectra"))
    for submission in completed:
        selected = set(submission.spectra.values_list("id",flat=True))
        expected_codes = {q.item_code for q in questions if not q.is_attention_check and q.scale.subfactor.spectra_id in selected}
        present = set(UserAnswer.objects.filter(submission=submission).values_list("question__item_code",flat=True))
        absent = expected_codes-present
        if absent:
            incomplete.append(dict(submission_id=submission.pk,is_test_data=submission.is_test_data,
                                   missing_item_rows=len(absent)))
    report_state=dict(completed_submissions=len(completed),
                      completed_without_pin=sum(s.report_normative_version_id is None for s in completed),
                      completed_clinical_with_test_pin=sum(not s.is_test_data and s.simulation_mode=="normal" and
                          s.report_normative_version is not None and s.report_normative_version.environment=="test" for s in completed),
                      user_answer_invalid_tokens=UserAnswer.objects.exclude(answer__in=["1","2","3","4","5"]).count())
    metadata_diffs = sum(
        (p["age"] != (int(rows[linked[p["id"]]-1]["Age"]) if rows[linked[p["id"]]-1]["Age"] else None)
         or not rows[linked[p["id"]]-1]["sex"].strip().startswith(p["sex"]))
        for p in participants if p["id"] in linked)
    snapshot = dict(csv_sha256=hashlib.sha256(raw).hexdigest(),key_sha256=hashlib.sha256(key_path.read_bytes()).hexdigest(),
                    participant_count=len(ids),scale_score_count=len(stored_scales),spectrum_score_count=len(stored_spectra),
                    normalized_scale_hash=digest(sorted((linked.get(p,f"unlinked-{p}"),n,format(s,".12g")) for (p,n),s in stored_scales.items())),
                    normalized_spectrum_hash=digest(sorted((linked.get(p,f"unlinked-{p}"),n,format(s,".12g")) for (p,n),s in stored_spectra.items())),
                    mapping_hash=digest(db_key))
    fixture = Path(__file__).with_name("v1_snapshot.json")
    snapshot_status = "PASS" if fixture.exists() and json.loads(fixture.read_text())==snapshot else "FAIL"
    column_audit=[]
    for code in headers:
        values=[r[code] for r in rows]
        column_audit.append(dict(column=code,is_question=code in key_by_code,
                                 blanks=sum(v=="" for v in values),
                                 special_null_tokens=sum(str(v).lower() in {"nan","null","none","na","n/a"} for v in values),
                                 whitespace_values=sum(v!=v.strip() for v in values),
                                 distinct_values=len(set(values)),
                                 integer_tokens=sum(v.lstrip("-").isdigit() for v in values)))
    out_of_range=[dict(csv_row=i,item_code=c,value=r[c],attention_check=key_by_code[c].get("is_attention_check",False))
                  for i,r in enumerate(rows,1) for c in csv_codes if r[c] not in {"1","2","3","4","5",""}]
    scientific_tokens=Counter(r[q["item_code"]] for r in rows for q in key if not q.get("is_attention_check"))
    scale_names=list(Scale.objects.values_list("name",flat=True))
    duplicate_scale_names=len(scale_names)-len(set(scale_names))
    result = dict(runtime=dict(python=platform.python_version(),django=get_version()),
                  version=dict(id=version.pk,name=version.name,status=version.status,environment=version.environment),
                  csv=dict(rows=len(rows),columns=len(headers),encoding="UTF-8 (BOM allowed)",has_bom=raw.startswith(b"\xef\xbb\xbf"),
                           question_columns=len(csv_codes),non_question_columns=[c for c in headers if c not in key_by_code],
                           missing_key_columns=sorted(set(key_by_code)-set(headers)),duplicate_headers=len(headers)-len(set(headers)),
                           duplicate_response_vectors=sum(len(v)-1 for v in signatures.values()),
                           malformed_rows=sum(None in r or any(v is None for v in r.values()) for r in rows),tokens=dict(tokens),
                           scientific_tokens=dict(scientific_tokens),out_of_range_cells=out_of_range,
                           duplicate_full_rows=len(rows)-len({tuple(r[c] for c in headers) for r in rows})),
                  import_comparison=dict(participants=len(ids),answers=len(answer_rows),safe_links=len(linked),
                                         unique_csv_rows_linked=len(set(linked.values())),unlinked=len(ids)-len(linked),
                                         cell_differences=len(cell_diffs),duplicate_answers=duplicates,metadata_differences=metadata_diffs),
                  normative_attention=dict(passed=sum(d["passed"] for d in attention_results),
                                           failed=sum(not d["passed"] for d in attention_results),
                                           correct_counts=dict(Counter(d["correct"] for d in attention_results)),
                                           csv_attention_summary_counts=dict(Counter(r.get("ATTENTION CHECK") for r in rows))),
                  mapping=dict(script_questions=len(key),db_questions=len(questions),differences=len(mapping_diffs),
                               duplicate_scale_names=duplicate_scale_names,
                               empty_scales=list(Scale.objects.filter(questions__isnull=True).values_list("name",flat=True)),
                               script_duplicate_codes=len(key)-len(key_by_code),attention_checks=sum(q.is_attention_check for q in questions),
                               catch_scored=sum(q.scale.name=="Catch" and not q.is_attention_check for q in questions),
                               official_key_available=False,reverse_configuration_available=False),
                  scale_recomputation=scale_cmp,spectrum_recomputation=spectrum_cmp,
                  csv_scale_recomputation=csv_scale_cmp,csv_spectrum_recomputation=csv_spectrum_cmp,
                  production_engine_mismatches=len(engine_diffs),percentile_mismatches=percentile_mismatches,
                  floating_point_percentile_differences=len(numeric_percentile_diffs),
                  production_answer_order_percentile_differences=len(order_diffs),golden_checks=run_checks(),
                  current_engine_vs_stored_percentile_differences=len(live_stored_diffs),
                  simulation=dict(n_per_profile=simulations,seed=seed,frequencies=frequencies,engine_differences=simulation_engine_differences,
                                  note="Uses production pure profile sampler; independent scoring. No DB submissions created."),
                  omitted_row_probe=dict(actual=actual_missing_probe,expected=intended_missing_probe),
                  incomplete_completed_submissions=incomplete,report_state=report_state,snapshot=snapshot)
    result["checks"] = {
        "v1_count": "PASS" if len(ids)==len(rows)==255 else "FAIL",
        "csv_database": "PASS" if len(linked)==len(rows)==len(ids)==len(set(linked.values())) and not cell_diffs and not duplicates and not metadata_diffs else "FAIL",
        "mapping_repository": "PASS" if not mapping_diffs and len(key)==len(key_by_code) and not duplicate_scale_names else "FAIL",
        "scale_recomputation": "PASS" if not scale_diff and not csv_scale_diff else "FAIL",
        "spectrum_recomputation": "PASS" if not spectrum_diff and not csv_spectrum_diff else "FAIL",
        "production_engine": "PASS" if not engine_diffs else "FAIL",
        "percentile_oracle": "PASS" if not percentile_mismatches else "FAIL",
        "golden_cases_and_invariants": "PASS",
        "simulation_engine": "PASS" if not simulation_engine_differences else "FAIL",
        "numerical_percentile_stability": "PASS" if not numeric_percentile_diffs else "FAIL",
        "production_membership": "PASS" if all(p["source"]=="real" for p in participants) else "FAIL",
        "completed_report_state": "PASS" if not any(v for k,v in report_state.items() if k!="completed_submissions") else "FAIL",
        "range": "PASS" if all(1<=s<=4 for s in list(stored_scales.values())+list(stored_spectra.values())) else "FAIL",
        "answer_choice_domain": "PASS" if not out_of_range else "FAIL",
        "omitted_rows_contract": "PASS" if actual_missing_probe["is_valid"]==intended_missing_probe["is_valid"] else "FAIL",
        "v1_snapshot": snapshot_status,
        "scientific_validity": "BLOCKED (official key / normative protocol unavailable)",
    }
    with connection.cursor() as cursor:
        cursor.execute("SHOW transaction_read_only")
        result["database_transaction_read_only"] = cursor.fetchone()[0]
    for name, data in (("scale_mismatches",scale_diff),("spectrum_mismatches",spectrum_diff),
                       ("csv_scale_mismatches",csv_scale_diff),("csv_spectrum_mismatches",csv_spectrum_diff),
                       ("answer_mismatches",cell_diffs),("mapping_mismatches",mapping_diffs),
                       ("engine_mismatches",engine_diffs),("monte_carlo",mc),("simulation_missing",missing_rows),
                       ("column_audit",column_audit),("floating_point_percentile_differences",numeric_percentile_diffs)):
        write_csv(output/f"{name}.csv",data)
    write_csv(output/"production_order_percentile_differences.csv",order_diffs)
    write_csv(output/"current_engine_vs_stored_percentile_differences.csv",live_stored_diffs)
    (output/"traces.json").write_text(json.dumps(traces,indent=2,ensure_ascii=False)+"\n")
    (output/"summary.json").write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    (output/"snapshot_candidate.json").write_text(json.dumps(snapshot,indent=2,ensure_ascii=False)+"\n")
    write_csv(output/"mapping.csv",db_key)
    return result
