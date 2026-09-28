import ast
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from django.test import SimpleTestCase
from polls.scoring import calculate_scale_scores_from_answers
from polls.percentiles import _calculate_percentile
from . import reference as ref
from .checks import run_checks


class ReferenceTests(SimpleTestCase):
    def test_golden_and_invariants(self):
        self.assertEqual(run_checks()["invariants"],"PASS")

    def test_oracle_has_no_production_imports(self):
        tree = ast.parse(Path(ref.__file__).read_text())
        imports = [n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        self.assertTrue(all(not (n or "").startswith(("polls","website","django")) for n in imports))

    def test_production_against_manual_goldens(self):
        q = SimpleNamespace(scale="test",is_attention_check=False)
        cases = json.loads(Path(__file__).with_name("golden_cases.json").read_text())
        for c in cases:
            if c.get("reverse_indices"):
                continue  # No reverse configuration exists in production.
            answers = [SimpleNamespace(question=q,answer="5" if a is None else a) for a in c["answers"]]
            self.assertEqual(calculate_scale_scores_from_answers(answers)["test"]["score"],c["score"])
            self.assertEqual(_calculate_percentile(c["distribution"],c["score"]),c["percentile"])

    def test_documented_omitted_rows_defect(self):
        q = SimpleNamespace(scale="test",is_attention_check=False)
        got = calculate_scale_scores_from_answers([SimpleNamespace(question=q,answer="4")])["test"]
        self.assertTrue(got["is_valid"])
        self.assertFalse(ref.scale(["4",None,None,None])["is_valid"])

    def test_documented_invalid_token_defect(self):
        q = SimpleNamespace(scale="test",is_attention_check=False)
        for token in ("0","9"):
            got = calculate_scale_scores_from_answers([SimpleNamespace(question=q,answer=token)])["test"]
            self.assertEqual(got["score"],int(token))
            with self.assertRaises(ValueError):
                ref.scale([token])
        for token in (None,""):
            with self.assertRaises((ValueError,TypeError)):
                calculate_scale_scores_from_answers([SimpleNamespace(question=q,answer=token)])

    def test_snapshot_source_integrity(self):
        import hashlib
        root = Path(__file__).resolve().parents[1]
        fixture = json.loads(Path(__file__).with_name("v1_snapshot.json").read_text())
        for field,path in (("csv_sha256",root/"BD.csv"),("key_sha256",root/"scripts/import_questions.py")):
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),fixture[field])

    def test_full_csv_oracle_matches_reviewed_snapshot(self):
        import csv
        from .audit import digest
        root=Path(__file__).resolve().parents[1]
        key=ref.read_key(root/"scripts/import_questions.py")
        fixture=json.loads(Path(__file__).with_name("v1_snapshot.json").read_text())
        with (root/"BD.csv").open(encoding="utf-8-sig",newline="") as f:
            rows=list(csv.DictReader(f,delimiter=";"))
        scales,spectra=[],[]
        agoraphobia=[]
        for i,row in enumerate(rows,1):
            ss,sp=ref.scores(row,key)
            for target,data in ((scales,ss),(spectra,sp)):
                target.extend((i,n,format(d["score"],".12g")) for n,d in data.items() if d["score"] is not None)
            agoraphobia.append(ss["Agoraphobia"]["score"])
            if i==1:
                self.assertEqual(ss["Agoraphobia"]["score"],1)
                self.assertEqual(ss["Well-being"]["score"],2.2)
                self.assertEqual(ss["Antisocial Behavior"]["score"],1)
        self.assertEqual(len(rows),255)
        self.assertEqual((len(scales),len(spectra)),(23715,1275))
        self.assertEqual(digest(sorted(scales)),fixture["normalized_scale_hash"])
        self.assertEqual(digest(sorted(spectra)),fixture["normalized_spectrum_hash"])
        self.assertEqual(ref.quantile(agoraphobia,.5),1)
        self.assertEqual(ref.quantile(agoraphobia,.95),2.2)
        self.assertEqual(ref.percentile(agoraphobia,1),54)

    def test_documented_report_without_norms_defect(self):
        from polls.report_interpretation import build_report_analysis
        with self.assertRaises(TypeError):
            build_report_analysis([dict(name="scale",is_valid=True,percentile=None)])

    def test_production_invariants_against_independent_reference(self):
        import itertools
        q=SimpleNamespace(scale="s",is_attention_check=False)
        catch=SimpleNamespace(scale="s",is_attention_check=True)
        for values in itertools.product("12345",repeat=4):
            answers=[SimpleNamespace(question=q,answer=v) for v in values]
            actual=calculate_scale_scores_from_answers(answers)["s"]
            expected=ref.scale(values)
            self.assertEqual(actual["score"],expected["score"])
            self.assertEqual(actual["is_valid"],expected["is_valid"])
            answers.append(SimpleNamespace(question=catch,answer="4"))
            self.assertEqual(calculate_scale_scores_from_answers(answers)["s"],actual)
        for x in range(501):
            self.assertEqual(_calculate_percentile([1,1,2,3,4],x/100),ref.percentile([1,1,2,3,4],x/100))
