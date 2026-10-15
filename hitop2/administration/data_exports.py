"""Read-only, portable scientific exports for operational administrators.

The functions in this module deliberately do not call normative lifecycle or
report-pinning services.  Their only database writes are performed by the view
layer, after a successful download package has been built, in the administrative
audit log.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from django.db.models import Q, QuerySet
from django.utils import timezone

from polls.models import (
    DynamicAnswer,
    DynamicQuestion,
    NormativeAnswer,
    NormativeDatasetMembership,
    NormativeDatasetVersion,
    NormativeParticipant,
    NormativeScaleScore,
    NormativeSpectrumScore,
    Question,
    QuestionnaireSubmission,
    Scale,
    Spectra,
    Subfactor,
    UserAnswer,
)
from polls.percentiles import _calculate_percentile
from polls.scoring import calculate_scale_scores_from_answers
from polls.sociodemographic import dynamic_answer_value, question_is_visible
from polls.spectrum_scores import calculate_spectrum_scores


EXPORT_SCHEMA_VERSION = "1.0"
MAX_SYNCHRONOUS_SUBMISSIONS = 10_000
CSV_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
SOCIODEMOGRAPHIC_EXCLUDED_TYPES = {"text"}
SOCIODEMOGRAPHIC_EXCLUDED_IDS = {
    # Free-form or unusually identifying fields are excluded even if their
    # configured type changes later.
    "country_born",
    "country_residence",
    "freguesia",
    "Diagnosis_descript",
    "Diagnosis_med_name",
    "Diagnosis_med_freq_other",
    "PT_residence_years_other",
}
SOCIODEMOGRAPHIC_SENSITIVE_PREFIXES = (
    "subs_use_",
    "mental_",
    "Diagnosis",
    "Medication",
)
SOCIODEMOGRAPHIC_SENSITIVE_IDS = {
    "race",
    "gender",
    "sex",
    "income",
    "spirituality",
    "life_events",
    "Health",
}


@dataclass(frozen=True)
class ScientificExportOptions:
    origin: str = "all"
    environment: str = "production"
    date_from: date | None = None
    date_to: date | None = None
    completed_only: bool = True
    include_answers: bool = True
    include_sociodemographics: bool = False
    include_results: bool = True


@dataclass
class ExportPackage:
    file: tempfile.SpooledTemporaryFile
    filename: str
    row_counts: dict[str, int]
    metadata: dict

    def close(self):
        self.file.close()


def _csv_safe(value):
    """Make a CSV cell safe for spreadsheets with a reversible prefix.

    RFC 4180 quoting does not stop spreadsheet formula evaluation.  A leading
    apostrophe is added only to dangerous textual cells.  metadata.json and the
    README document how to reverse it without ambiguity.
    """
    if value is None:
        return "", False
    if isinstance(value, bool):
        return ("true" if value else "false"), False
    if isinstance(value, (datetime, date)):
        return value.isoformat(), False
    text = str(value)
    if text.startswith(CSV_DANGEROUS_PREFIXES):
        return "'" + text, True
    return text, False


def _csv_bytes(headers, rows):
    stream = io.StringIO(newline="")
    safety_header = "csv_injection_escaped_fields"
    output_headers = [*headers, safety_header]
    writer = csv.DictWriter(stream, fieldnames=output_headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        safe_row = {}
        escaped_fields = []
        for key in headers:
            safe_row[key], escaped = _csv_safe(row.get(key))
            if escaped:
                escaped_fields.append(key)
        safe_row[safety_header] = json.dumps(escaped_fields, ensure_ascii=False)
        writer.writerow(safe_row)
    return stream.getvalue().encode("utf-8")


def _json_bytes(value):
    return json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=True, default=str
    ).encode("utf-8")


def _code_version():
    git_dir = Path(settings.BASE_DIR) / ".git"
    try:
        head = (git_dir / "HEAD").read_text(encoding="ascii").strip()
        if head.startswith("ref: "):
            return (git_dir / head[5:]).read_text(encoding="ascii").strip()
        return head
    except (OSError, UnicodeError):
        return ""


def _format_number(value):
    if value is None:
        return ""
    return format(float(value), ".17g")


def _structure_files():
    questions = []
    for item in Question.objects.select_related(
        "scale__subfactor__spectra"
    ).order_by("item_code").iterator():
        scientific = not item.is_attention_check
        questions.append({
            "item_code": item.item_code,
            "question_text": item.question_text,
            "scale_code": item.scale.name if scientific else "",
            "subfactor_code": item.scale.subfactor.name if scientific else "",
            "spectrum_code": item.scale.subfactor.spectra.name if scientific else "",
            "is_attention_check": item.is_attention_check,
            "expected_answer": item.expected_answer if item.is_attention_check else "",
            "answer_options": json.dumps(
                dict(Question.ANSWER_CHOICES), ensure_ascii=False, sort_keys=True
            ),
        })
    scales = [
        {
            "scale_code": item.name,
            "scale_name": item.name,
            "subfactor_code": item.subfactor.name,
            "spectrum_code": item.subfactor.spectra.name,
        }
        for item in Scale.objects.filter(
            questions__is_attention_check=False
        ).exclude(subfactor__spectra__name__iexact="catch").select_related(
            "subfactor__spectra"
        ).distinct().order_by(
            "subfactor__spectra__name", "subfactor__name", "name"
        )
    ]
    subfactors = [
        {
            "subfactor_code": item.name,
            "subfactor_name": item.name,
            "spectrum_code": item.spectra.name,
        }
        for item in Subfactor.objects.filter(
            scales__questions__is_attention_check=False
        ).exclude(spectra__name__iexact="catch").select_related("spectra").distinct().order_by(
            "spectra__name", "name"
        )
    ]
    spectra = [
        {"spectrum_code": item.name, "spectrum_name": item.name}
        for item in Spectra.objects.order_by("name")
        if item.name.casefold() != "catch"
    ]
    return {
        "questions.csv": (
            [
                "item_code", "question_text", "scale_code", "subfactor_code",
                "spectrum_code", "is_attention_check", "expected_answer",
                "answer_options",
            ],
            questions,
        ),
        "scales.csv": (
            ["scale_code", "scale_name", "subfactor_code", "spectrum_code"],
            scales,
        ),
        "subfactors.csv": (
            ["subfactor_code", "subfactor_name", "spectrum_code"],
            subfactors,
        ),
        "spectra.csv": (
            ["spectrum_code", "spectrum_name"],
            spectra,
        ),
    }


def scientific_submission_queryset(options: ScientificExportOptions) -> QuerySet:
    queryset = QuestionnaireSubmission.objects.filter(questionnaire_type="hitop")
    queryset = queryset.filter(is_test_data=(options.environment == "test"))
    if options.environment == "production":
        queryset = queryset.filter(simulation_mode="normal").filter(
            Q(user__userprofile__is_test_data=False) | Q(collection__is_test_data=False)
        )
    if options.origin == "clinical":
        queryset = queryset.filter(user__isnull=False, collection__isnull=True)
    elif options.origin == "collection":
        queryset = queryset.filter(user__isnull=True, collection__isnull=False)
    if options.date_from:
        queryset = queryset.filter(started_at__date__gte=options.date_from)
    if options.date_to:
        queryset = queryset.filter(started_at__date__lte=options.date_to)
    if options.completed_only:
        queryset = queryset.filter(completed=True)
    return queryset.order_by("pk")


def preview_scientific_export(options: ScientificExportOptions):
    queryset = scientific_submission_queryset(options)
    return {
        "submissions": queryset.count(),
        "clinical_submissions": queryset.filter(user__isnull=False).count(),
        "collection_submissions": queryset.filter(collection__isnull=False).count(),
        "answers": UserAnswer.objects.filter(submission__in=queryset).count()
        if options.include_answers else 0,
        "sociodemographic_answers": DynamicAnswer.objects.filter(
            submission__in=queryset
        ).count() if options.include_sociodemographics else 0,
    }


def _participant_maps(submissions):
    keys = []
    seen = set()
    for submission in submissions:
        if submission.user_id:
            key = ("clinical", submission.user_id)
        else:
            key = ("collection", submission.collection_id, submission.participant_number)
        if key not in seen:
            seen.add(key)
            keys.append(key)
    participant_ids = {key: f"P{index:06d}" for index, key in enumerate(keys, 1)}
    submission_ids = {
        submission.pk: f"S{index:06d}"
        for index, submission in enumerate(submissions, 1)
    }
    return participant_ids, submission_ids


def _participant_key(submission):
    if submission.user_id:
        return ("clinical", submission.user_id)
    return ("collection", submission.collection_id, submission.participant_number)


def _scientific_core_rows(submissions, participant_ids, submission_ids):
    participant_rows = {}
    submission_rows = []
    for submission in submissions:
        key = _participant_key(submission)
        participant_id = participant_ids[key]
        row = participant_rows.setdefault(participant_id, {
            "participant_id": participant_id,
            "origin": key[0],
            "environment": "test" if submission.is_test_data else "production",
            "submission_count": 0,
        })
        row["submission_count"] += 1
        submission_rows.append({
            "submission_id": submission_ids[submission.pk],
            "participant_id": participant_id,
            "origin": key[0],
            "environment": "test" if submission.is_test_data else "production",
            "questionnaire_type": submission.questionnaire_type,
            "started_date": timezone.localtime(submission.started_at).date(),
            "completed_date": (
                timezone.localtime(submission.completed_at).date()
                if submission.completed_at else ""
            ),
            "completed": submission.completed,
            "archived": bool(
                submission.user_id
                and getattr(submission.user, "userprofile", None)
                and submission.user.userprofile.archived_at
            ),
            "normative_status": submission.normative_status,
            "report_normative_version": (
                submission.report_normative_version_name
                or (submission.report_normative_version.name
                    if submission.report_normative_version else "")
            ),
            "report_normative_environment": (
                submission.report_normative_version_environment
                or (submission.report_normative_version.environment
                    if submission.report_normative_version else "")
            ),
            "normative_version_status": (
                "pinned" if (
                    submission.report_normative_version_id
                    or submission.report_normative_version_name
                ) else "not_assigned"
            ),
        })
    return list(participant_rows.values()), submission_rows


def _scientific_answer_rows(submissions, submission_ids):
    questions = list(Question.objects.select_related(
        "scale__subfactor__spectra"
    ).order_by("item_code"))
    actual_by_submission = {}
    for answer in UserAnswer.objects.filter(
        submission_id__in=[item.pk for item in submissions]
    ).select_related("question__scale__subfactor__spectra").order_by("pk"):
        actual_by_submission.setdefault(answer.submission_id, {})[answer.question_id] = answer
    rows = []
    for submission in submissions:
        actual = actual_by_submission.get(submission.pk, {})
        spectrum_ids = {spectrum.pk for spectrum in submission.spectra.all()}
        included_ids = {
            question.pk for question in questions
            if question.is_attention_check
            or question.scale.subfactor.spectra_id in spectrum_ids
        }
        # Current structure is emitted in full so that a missing row never has
        # to mean both "unanswered" and "not included".
        for question in questions:
            answer = actual.get(question.pk)
            included = question.pk in included_ids or answer is not None
            if answer is not None:
                status = (
                    "explicitly_omitted" if answer.answer == "5" else "answered_valid"
                )
                value = answer.answer
            elif included:
                status = "presented_unanswered"
                value = ""
            else:
                status = "not_included"
                value = ""
            rows.append({
                "submission_id": submission_ids[submission.pk],
                "item_code": question.item_code,
                "answer": value,
                "response_status": status,
                "included_in_application": included,
                "is_attention_check": question.is_attention_check,
            })
    return rows


def _sociodemographic_rows(submissions, submission_ids):
    questions = list(
        DynamicQuestion.objects.prefetch_related("choices").order_by(
            "category__name", "order", "question_id"
        )
    )
    answers_by_submission = {}
    for answer in DynamicAnswer.objects.filter(
        submission_id__in=[item.pk for item in submissions]
    ).select_related("question").order_by("pk"):
        answers_by_submission.setdefault(answer.submission_id, {})[
            answer.question_id
        ] = answer
    rows = []
    for submission in submissions:
        answers = answers_by_submission.get(submission.pk, {})
        visibility_values = {
            answer.question.question_id: dynamic_answer_value(answer)
            for answer in answers.values()
        }
        for question in questions:
            if (
                question.question_type in SOCIODEMOGRAPHIC_EXCLUDED_TYPES
                or question.question_id in SOCIODEMOGRAPHIC_EXCLUDED_IDS
                or question.question_id in SOCIODEMOGRAPHIC_SENSITIVE_IDS
                or question.question_id.startswith(SOCIODEMOGRAPHIC_SENSITIVE_PREFIXES)
            ):
                continue
            visible = question_is_visible(question, visibility_values)
            answer = answers.get(question.pk)
            answer_value = ""
            answer_label = ""
            if not visible:
                status = "not_presented_conditional"
            elif answer is None:
                status = "presented_unanswered"
            else:
                raw_value = dynamic_answer_value(answer)
                answer_value = (
                    json.dumps(raw_value, ensure_ascii=False)
                    if isinstance(raw_value, list) else raw_value
                )
                choice_labels = {
                    choice.value: choice.label for choice in question.choices.all()
                }
                if isinstance(raw_value, list):
                    labels = [choice_labels.get(value, value) for value in raw_value]
                    answer_label = json.dumps(labels, ensure_ascii=False)
                else:
                    answer_label = choice_labels.get(str(raw_value), str(raw_value))
                status = (
                    "explicitly_not_applicable"
                    if "não aplicável" in answer_label.casefold()
                    else "answered"
                )
            rows.append({
                "submission_id": submission_ids[submission.pk],
                "question_id": question.question_id,
                "question_type": question.question_type,
                "answer_value": answer_value,
                "answer_label": answer_label,
                "response_status": status,
            })
    return rows


def _scientific_score_rows(submissions, submission_ids):
    scale_rows = []
    spectrum_rows = []
    referenced_versions = set()
    answers_by_submission = {}
    for answer in UserAnswer.objects.filter(
        submission_id__in=[item.pk for item in submissions]
    ).select_related("question__scale__subfactor__spectra").order_by("pk"):
        answers_by_submission.setdefault(answer.submission_id, []).append(answer)

    version_ids = {
        submission.report_normative_version_id
        for submission in submissions
        if submission.report_normative_version_id
    }
    normative_scale_values = {}
    for version_id, scale_id, raw_score in NormativeScaleScore.objects.filter(
        version_id__in=version_ids
    ).values_list("version_id", "scale_id", "raw_score").iterator():
        normative_scale_values.setdefault((version_id, scale_id), []).append(raw_score)
    normative_spectrum_values = {}
    for version_id, spectrum_id, raw_score in NormativeSpectrumScore.objects.filter(
        version_id__in=version_ids
    ).values_list("version_id", "spectrum_id", "raw_score").iterator():
        normative_spectrum_values.setdefault((version_id, spectrum_id), []).append(raw_score)

    for submission in submissions:
        if not submission.completed:
            # A partial result is not presented as a completed scientific score.
            continue
        spectrum_ids = {spectrum.pk for spectrum in submission.spectra.all()}
        answers = [
            answer for answer in answers_by_submission.get(submission.pk, [])
            if answer.question.is_attention_check
            or answer.question.scale.subfactor.spectra_id in spectrum_ids
        ]
        scale_scores = calculate_scale_scores_from_answers(answers)
        spectrum_scores = calculate_spectrum_scores(scale_scores)
        version = submission.report_normative_version
        version_name = submission.report_normative_version_name or (
            version.name if version else ""
        )
        version_environment = submission.report_normative_version_environment or (
            version.environment if version else ""
        )
        if version_name:
            referenced_versions.add((version_name, version_environment))
        for scale, data in scale_scores.items():
            scale_rows.append({
                "submission_id": submission_ids[submission.pk],
                "scale_code": scale.name,
                "raw_score": _format_number(data["score"]),
                "percentile": (
                    _calculate_percentile(
                        normative_scale_values.get((version.pk, scale.pk), []),
                        data["score"],
                    )
                    if data["is_valid"] and version is not None else ""
                ),
                "is_valid": data["is_valid"],
                "missing_answers": data["missing_answers"],
                "missing_percentage": _format_number(data["missing_percentage"]),
                "total_items": data["total_items"],
                "normative_version": version_name,
                "normative_environment": version_environment,
                "calculation_provenance": "calculated_at_export_with_current_scoring_service",
            })
        for spectrum, data in spectrum_scores.items():
            if spectrum.name.casefold() == "catch":
                continue
            spectrum_rows.append({
                "submission_id": submission_ids[submission.pk],
                "spectrum_code": spectrum.name,
                "raw_score": _format_number(data["score"]),
                "percentile": (
                    _calculate_percentile(
                        normative_spectrum_values.get((version.pk, spectrum.pk), []),
                        data["score"],
                    ) if data["is_valid"] and version is not None else ""
                ),
                "is_valid": data["is_valid"],
                "missing_answers": data["missing_answers"],
                "missing_percentage": _format_number(data["missing_percentage"]),
                "total_items": data["total_items"],
                "normative_version": version_name,
                "normative_environment": version_environment,
                "calculation_provenance": "calculated_at_export_with_current_scoring_service",
            })
    version_rows = [
        {"version_name": name, "environment": environment}
        for name, environment in sorted(referenced_versions)
    ]
    return scale_rows, spectrum_rows, version_rows


def _readme(export_type):
    common = """HiTOP Platform — exportação científica portátil

Todos os CSV usam UTF-8, cabeçalhos explícitos e o formato RFC 4180. Uma célula
textual que começasse por =, +, -, @, tab ou carriage return recebeu um apóstrofo
inicial para impedir formula injection em folhas de cálculo. Para recuperar o
valor original, consulte csv_injection_escaped_fields e remova exatamente esse
apóstrofo apenas nos campos listados nessa coluna.

Valores ausentes são strings vazias. Consulte response_status para distinguir
omissão explícita, ausência de resposta, condição não apresentada e item não
incluído. Identificadores P/S/N são locais a este ZIP e não permitem reverter a
identidade. Pseudonimização não equivale a anonimização.

O manifesto contém SHA-256 e contagem de linhas de cada ficheiro de dados.
questions.csv descreve a estrutura atual: a base de dados não mantém uma versão
histórica completa do instrumento.
"""
    if export_type == "scientific_data":
        return common + """

participants.csv liga participantes pseudonimizados a submissions.csv.
answers.csv contém o dado bruto; não aplica reverse scoring. scale_scores.csv e
spectrum_scores.csv, quando presentes, foram calculados no momento da exportação
pelos serviços científicos atuais. Percentis só são produzidos se a submissão já
tiver uma versão normativa associada; a exportação nunca atribui uma versão.

Exemplo Python/pandas:
  import pandas as pd
  submissions = pd.read_csv("submissions.csv", dtype=str)
  answers = pd.read_csv("answers.csv", dtype=str)
  data = answers.merge(submissions, on="submission_id", validate="many_to_one")

Exemplo R:
  submissions <- read.csv("submissions.csv", colClasses="character")
  answers <- read.csv("answers.csv", colClasses="character")
  data <- merge(answers, submissions, by="submission_id")
"""
    return common + """

normative_memberships.csv define exclusivamente o snapshot selecionado.
normative_answers.csv preserva respostas armazenadas e normative_*_scores.csv
preservam os scores persistidos da versão, sem recálculo. A ausência de uma linha
de score numa versão draft significa que o score não está persistido.
"""


def _build_zip(files, metadata, filename):
    generated = {}
    row_counts = {}
    for name, (headers, rows) in files.items():
        content = _csv_bytes(headers, rows)
        generated[name] = content
        row_counts[name] = len(rows)

    metadata = dict(metadata)
    metadata["files"] = sorted([*generated, "metadata.json", "README.txt", "manifest.csv"])
    metadata["row_counts"] = row_counts
    generated["metadata.json"] = _json_bytes(metadata)
    generated["README.txt"] = _readme(metadata["export_type"]).encode("utf-8")

    manifest_rows = [
        {
            "filename": name,
            "rows": row_counts.get(name, ""),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for name, content in sorted(generated.items())
    ]
    generated["manifest.csv"] = _csv_bytes(
        ["filename", "rows", "sha256"], manifest_rows
    )
    row_counts["manifest.csv"] = len(manifest_rows)

    output = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in generated.items():
            archive.writestr(name, content)
    output.seek(0)
    return ExportPackage(output, filename, row_counts, metadata)


def build_scientific_export(options: ScientificExportOptions):
    submissions = list(
        scientific_submission_queryset(options).select_related(
            "user__userprofile", "collection", "report_normative_version"
        ).prefetch_related("spectra")[: MAX_SYNCHRONOUS_SUBMISSIONS + 1]
    )
    if len(submissions) > MAX_SYNCHRONOUS_SUBMISSIONS:
        raise ValueError(
            f"A exportação excede o limite síncrono de {MAX_SYNCHRONOUS_SUBMISSIONS} submissões."
        )
    participant_ids, submission_ids = _participant_maps(submissions)
    participants, submission_rows = _scientific_core_rows(
        submissions, participant_ids, submission_ids
    )
    files = {
        "participants.csv": (
            ["participant_id", "origin", "environment", "submission_count"],
            participants,
        ),
        "submissions.csv": (
            [
                "submission_id", "participant_id", "origin", "environment",
                "questionnaire_type", "started_date", "completed_date", "completed",
                "archived", "normative_status", "report_normative_version",
                "report_normative_environment", "normative_version_status",
            ],
            submission_rows,
        ),
        **_structure_files(),
    }
    if options.include_answers:
        files["answers.csv"] = (
            [
                "submission_id", "item_code", "answer", "response_status",
                "included_in_application", "is_attention_check",
            ],
            _scientific_answer_rows(submissions, submission_ids),
        )
    if options.include_sociodemographics:
        files["sociodemographic_answers.csv"] = (
            [
                "submission_id", "question_id", "question_type", "answer_value",
                "answer_label", "response_status",
            ],
            _sociodemographic_rows(submissions, submission_ids),
        )
    referenced_versions = []
    if options.include_results:
        scale_rows, spectrum_rows, referenced_versions = _scientific_score_rows(
            submissions, submission_ids
        )
        files["scale_scores.csv"] = (
            [
                "submission_id", "scale_code", "raw_score", "percentile",
                "is_valid", "missing_answers", "missing_percentage", "total_items",
                "normative_version", "normative_environment", "calculation_provenance",
            ],
            scale_rows,
        )
        files["spectrum_scores.csv"] = (
            [
                "submission_id", "spectrum_code", "raw_score", "percentile",
                "is_valid", "missing_answers", "missing_percentage", "total_items",
                "normative_version", "normative_environment", "calculation_provenance",
            ],
            spectrum_rows,
        )
        if referenced_versions:
            files["normative_versions.csv"] = (
                ["version_name", "environment"], referenced_versions
            )

    now = timezone.now()
    metadata = {
        "platform": "HiTOP Platform",
        "export_type": "scientific_data",
        "schema_version": EXPORT_SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "timezone": settings.TIME_ZONE,
        "environment": options.environment,
        "filters": asdict(options),
        "participant_count": len(participants),
        "submission_count": len(submissions),
        "referenced_normative_versions": referenced_versions,
        "code_version": _code_version(),
        "missing_value": "empty CSV cell; interpret with response_status",
        "numeric_precision": "Python float round-trip representation (.17g)",
        "csv_injection_protection": (
            "reversible leading apostrophe for = + - @ TAB CR; transformed field "
            "names are listed in csv_injection_escaped_fields"
        ),
        "scoring_provenance": (
            "calculated_at_export_with_current_scoring_service"
            if options.include_results else "not_included"
        ),
        "instrument_history_limitation": (
            "The database has no complete versioned instrument snapshot; structure CSVs "
            "describe the structure present at export time."
        ),
        "sociodemographic_minimization": (
            "Direct identifiers, free-text questions, and high-sensitivity configured "
            "variables (diagnosis, treatment, substance use, race, gender, sex, income, "
            "spirituality, life events and health) are excluded. Dates are reduced to "
            "calendar dates. Legacy user-level sociodemographic answers are not associated "
            "with a submission and are not exported to avoid false historical linkage."
        ),
    }
    filename = f"HiTOP_Scientific_Export_{timezone.localdate().isoformat()}.zip"
    return _build_zip(files, metadata, filename)


def preview_normative_export(version):
    memberships = NormativeDatasetMembership.objects.filter(version=version)
    participant_ids = memberships.values_list("participant_id", flat=True)
    return {
        "participants": memberships.count(),
        "answers": NormativeAnswer.objects.filter(participant_id__in=participant_ids).count(),
        "scale_scores": NormativeScaleScore.objects.filter(version=version).count(),
        "spectrum_scores": NormativeSpectrumScore.objects.filter(version=version).count(),
    }


def build_normative_export(version):
    memberships = list(
        NormativeDatasetMembership.objects.filter(version=version)
        .select_related("participant")
        .order_by("participant_id")
    )
    if (
        version.environment == NormativeDatasetVersion.Environment.PRODUCTION
        and any(
            item.participant.source == NormativeParticipant.Source.SYNTHETIC
            for item in memberships
        )
    ):
        raise ValueError(
            "A versão de produção contém uma associação sintética inválida e não pode ser exportada."
        )
    participant_ids = [item.participant_id for item in memberships]
    exported_ids = {
        participant_id: f"N{index:06d}"
        for index, participant_id in enumerate(participant_ids, 1)
    }
    participant_rows = [
        {
            "participant_id": exported_ids[item.participant_id],
            "source": item.participant.source,
            "age": item.participant.age,
            "sex": item.participant.sex,
            "created_date": timezone.localtime(item.participant.created_at).date(),
        }
        for item in memberships
    ]
    membership_rows = [
        {
            "version_name": version.name,
            "environment": version.environment,
            "participant_id": exported_ids[item.participant_id],
            "participant_source": item.participant.source,
        }
        for item in memberships
    ]
    answer_rows = [
        {
            "participant_id": exported_ids[item.participant_id],
            "item_code": item.question.item_code,
            "answer": item.answer,
            "response_status": (
                "explicitly_omitted" if item.answer == "5" else "answered_valid"
            ),
        }
        for item in NormativeAnswer.objects.filter(
            participant_id__in=participant_ids
        ).select_related("question").order_by("participant_id", "question__item_code")
    ]
    scale_score_objects = list(
        NormativeScaleScore.objects.filter(version=version).select_related(
            "scale"
        ).order_by("participant_id", "scale__name")
    )
    spectrum_score_objects = list(
        NormativeSpectrumScore.objects.filter(version=version).select_related(
            "spectrum"
        ).order_by("participant_id", "spectrum__name")
    )
    member_id_set = set(participant_ids)
    unexpected_score_participants = {
        item.participant_id for item in [*scale_score_objects, *spectrum_score_objects]
        if item.participant_id not in member_id_set
    }
    if unexpected_score_participants:
        raise ValueError(
            "A versão contém scores associados a participantes fora do snapshot e não pode ser exportada."
        )
    scale_rows = [
        {
            "participant_id": exported_ids[item.participant_id],
            "scale_code": item.scale.name,
            "raw_score": _format_number(item.raw_score),
            "score_provenance": "persisted_normative_version_snapshot",
        }
        for item in scale_score_objects
    ]
    spectrum_rows = [
        {
            "participant_id": exported_ids[item.participant_id],
            "spectrum_code": item.spectrum.name,
            "raw_score": _format_number(item.raw_score),
            "score_provenance": "persisted_normative_version_snapshot",
        }
        for item in spectrum_score_objects
        if item.spectrum.name.casefold() != "catch"
    ]
    files = {
        "normative_participants.csv": (
            ["participant_id", "source", "age", "sex", "created_date"],
            participant_rows,
        ),
        "normative_memberships.csv": (
            ["version_name", "environment", "participant_id", "participant_source"],
            membership_rows,
        ),
        "normative_answers.csv": (
            ["participant_id", "item_code", "answer", "response_status"],
            answer_rows,
        ),
        "normative_scale_scores.csv": (
            ["participant_id", "scale_code", "raw_score", "score_provenance"],
            scale_rows,
        ),
        "normative_spectrum_scores.csv": (
            ["participant_id", "spectrum_code", "raw_score", "score_provenance"],
            spectrum_rows,
        ),
        **_structure_files(),
    }
    metadata = {
        "platform": "HiTOP Platform",
        "export_type": "normative_dataset",
        "schema_version": EXPORT_SCHEMA_VERSION,
        "generated_at": timezone.now().isoformat(),
        "timezone": settings.TIME_ZONE,
        "environment": version.environment,
        "normative_version": {
            "name": version.name,
            "environment": version.environment,
            "status": version.status,
            "created_at": version.created_at.isoformat(),
            "prepared_at": version.prepared_at.isoformat() if version.prepared_at else None,
            "activated_at": version.activated_at.isoformat() if version.activated_at else None,
            "baseline_version": version.baseline_version.name if version.baseline_version else None,
        },
        "participant_count": len(participant_rows),
        "code_version": _code_version(),
        "missing_value": "empty CSV cell; missing score rows are not fabricated",
        "numeric_precision": "stored Python float round-trip representation (.17g)",
        "csv_injection_protection": (
            "reversible leading apostrophe for = + - @ TAB CR; transformed field "
            "names are listed in csv_injection_escaped_fields"
        ),
        "score_provenance": "persisted_normative_version_snapshot; no recalculation",
        "instrument_history_limitation": (
            "The database has no complete versioned instrument snapshot; structure CSVs "
            "describe the structure present at export time. Scale, subfactor and spectrum "
            "models expose names rather than dedicated stable code fields. Normative answers "
            "and demographics are participant-scoped rather than version-scoped; scores and "
            "memberships are version-specific snapshots."
        ),
    }
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", version.name).strip("._") or "version"
    filename = f"HiTOP_Normative_Export_{safe_name}_{version.environment}.zip"
    return _build_zip(files, metadata, filename)
