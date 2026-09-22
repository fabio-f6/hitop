from collections import Counter

from django.db.models import Count, F, Q

from polls.models import (
    DynamicChoice,
    DynamicQuestion,
    NormativeDatasetVersion,
    Question,
    QuestionCategory,
    Scale,
    Spectra,
    Subfactor,
)
from polls.normative_export import (
    MENTAL_DIAGNOSIS_NEVER_VALUE,
    MENTAL_DIAGNOSIS_QUESTION_ID,
    MENTAL_DIAGNOSIS_VALUES,
    PORTUGUESE_LANGUAGE_QUESTION_ID,
    PORTUGUESE_LANGUAGE_VALUES,
    PORTUGUESE_LANGUAGE_YES_VALUE,
)
from polls.normative_versions import (
    get_active_normative_version,
    get_normative_participant_counts,
    get_normative_versions,
)
from polls.socio_config import SOCIO_QUESTIONS


EMPTY_VALUE_PATTERN = r"^\s*$"
_NOT_PROVIDED = object()


def _problem(severity, code, title, description, count=None):
    problem = {
        "severity": severity,
        "code": code,
        "title": title,
        "description": description,
    }
    if count is not None:
        problem["count"] = count
    return problem


def _append_count_problem(
    problems,
    *,
    count,
    severity,
    code,
    title,
    description,
):
    if count:
        problems.append(
            _problem(
                severity,
                code,
                title,
                description,
                count,
            )
        )


def _scientific_structure_health():
    spectra = Spectra.objects.aggregate(
        total=Count("id", distinct=True),
        empty_name=Count(
            "id",
            filter=Q(name__regex=EMPTY_VALUE_PATTERN),
            distinct=True,
        ),
        without_subfactors=Count(
            "id",
            filter=Q(subfactors__isnull=True),
            distinct=True,
        ),
    )
    subfactors = Subfactor.objects.aggregate(
        total=Count("id", distinct=True),
        empty_name=Count(
            "id",
            filter=Q(name__regex=EMPTY_VALUE_PATTERN),
            distinct=True,
        ),
        without_scales=Count(
            "id",
            filter=Q(scales__isnull=True),
            distinct=True,
        ),
    )
    scales = Scale.objects.aggregate(
        total=Count("id", distinct=True),
        empty_name=Count(
            "id",
            filter=Q(name__regex=EMPTY_VALUE_PATTERN),
            distinct=True,
        ),
        without_questions=Count(
            "id",
            filter=Q(questions__isnull=True),
            distinct=True,
        ),
    )

    valid_expected_answers = [value for value, _label in Question.ANSWER_CHOICES]
    questions = Question.objects.aggregate(
        total=Count("id"),
        empty_item_code=Count(
            "id",
            filter=Q(item_code__regex=EMPTY_VALUE_PATTERN),
        ),
        empty_text=Count(
            "id",
            filter=Q(question_text__regex=EMPTY_VALUE_PATTERN),
        ),
        attention_missing_expected=Count(
            "id",
            filter=Q(
                is_attention_check=True,
                expected_answer__regex=EMPTY_VALUE_PATTERN,
            ),
        ),
        attention_invalid_expected=Count(
            "id",
            filter=(
                Q(is_attention_check=True)
                & ~Q(expected_answer__in=valid_expected_answers)
                & ~Q(expected_answer__regex=EMPTY_VALUE_PATTERN)
            ),
        ),
        non_attention_with_expected=Count(
            "id",
            filter=(
                Q(is_attention_check=False)
                & ~Q(expected_answer__regex=EMPTY_VALUE_PATTERN)
            ),
        ),
    )

    problems = []
    for layer, label, stats in (
        ("spectra", "spectra", spectra),
        ("subfactors", "subfatores", subfactors),
        ("scales", "escalas", scales),
        ("questions", "perguntas", questions),
    ):
        if stats["total"] == 0:
            problems.append(
                _problem(
                    "error",
                    f"scientific_structure_missing_{layer}",
                    f"Não existem {label} configurados",
                    (
                        "A estrutura científica necessária ao questionário está "
                        "incompleta."
                    ),
                )
            )

    for stats, suffix, label in (
        (spectra, "spectrum", "spectra"),
        (subfactors, "subfactor", "subfatores"),
        (scales, "scale", "escalas"),
    ):
        _append_count_problem(
            problems,
            count=stats["empty_name"],
            severity="error",
            code=f"empty_{suffix}_name",
            title=f"Existem {label} sem nome",
            description="Foram encontrados elementos científicos com nome vazio.",
        )

    _append_count_problem(
        problems,
        count=spectra["without_subfactors"],
        severity="warning",
        code="spectrum_without_subfactors",
        title="Spectra sem subfatores",
        description="Existem spectra que não contêm qualquer subfator.",
    )
    _append_count_problem(
        problems,
        count=subfactors["without_scales"],
        severity="warning",
        code="subfactor_without_scales",
        title="Subfatores sem escalas",
        description="Existem subfatores que não contêm qualquer escala.",
    )
    _append_count_problem(
        problems,
        count=scales["without_questions"],
        severity="warning",
        code="scale_without_questions",
        title="Escalas sem perguntas",
        description="Existem escalas que não contêm qualquer pergunta.",
    )
    _append_count_problem(
        problems,
        count=questions["empty_item_code"],
        severity="error",
        code="question_empty_item_code",
        title="Perguntas sem item_code",
        description="Existem perguntas cujo identificador científico está vazio.",
    )
    _append_count_problem(
        problems,
        count=questions["empty_text"],
        severity="error",
        code="question_empty_text",
        title="Perguntas sem texto",
        description="Existem perguntas cujo texto está vazio.",
    )
    _append_count_problem(
        problems,
        count=questions["attention_missing_expected"],
        severity="warning",
        code="attention_check_missing_expected_answer",
        title="Attention checks sem resposta esperada",
        description=(
            "Existem perguntas marcadas como attention check sem expected_answer."
        ),
    )
    _append_count_problem(
        problems,
        count=questions["attention_invalid_expected"],
        severity="error",
        code="attention_check_invalid_expected_answer",
        title="Attention checks com resposta esperada inválida",
        description=(
            "Existem respostas esperadas fora das opções válidas do questionário."
        ),
    )
    _append_count_problem(
        problems,
        count=questions["non_attention_with_expected"],
        severity="warning",
        code="non_attention_check_with_expected_answer",
        title="Perguntas comuns com resposta esperada",
        description=(
            "Existem perguntas que não são attention checks mas têm "
            "expected_answer configurada."
        ),
    )

    return {
        "summary": {
            "spectra_count": spectra["total"],
            "subfactor_count": subfactors["total"],
            "scale_count": scales["total"],
            "question_count": questions["total"],
        },
        "problems": problems,
    }


def _sociodemographic_health():
    configured_ids = {question["id"] for question in SOCIO_QUESTIONS}
    question_stats = DynamicQuestion.objects.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(is_active=True)),
        configured_present=Count(
            "id",
            filter=Q(question_id__in=configured_ids),
        ),
        configured_active=Count(
            "id",
            filter=Q(question_id__in=configured_ids, is_active=True),
        ),
    )
    category_count = QuestionCategory.objects.count()
    sociodemographic_category_count = (
        QuestionCategory.objects.filter(
            questions__question_id__in=configured_ids,
        )
        .distinct()
        .count()
    )

    criteria = (
        {
            "key": "portuguese_language",
            "label": "Português-Europeu",
            "question_id": PORTUGUESE_LANGUAGE_QUESTION_ID,
            "expected_value": PORTUGUESE_LANGUAGE_YES_VALUE,
            "known_values": set(PORTUGUESE_LANGUAGE_VALUES),
        },
        {
            "key": "mental_diagnosis",
            "label": "Diagnóstico de saúde mental",
            "question_id": MENTAL_DIAGNOSIS_QUESTION_ID,
            "expected_value": MENTAL_DIAGNOSIS_NEVER_VALUE,
            "known_values": set(MENTAL_DIAGNOSIS_VALUES),
        },
    )
    criterion_ids = [criterion["question_id"] for criterion in criteria]
    criterion_questions = {
        row["question_id"]: row
        for row in DynamicQuestion.objects.filter(
            question_id__in=criterion_ids,
        ).values(
            "question_id",
            "question_type",
            "required",
            "is_active",
        )
    }
    criterion_choices = {question_id: set() for question_id in criterion_ids}
    for question_id, value in DynamicChoice.objects.filter(
        question__question_id__in=criterion_ids,
    ).values_list("question__question_id", "value"):
        criterion_choices[question_id].add(value)

    problems = []
    missing_configured_count = len(configured_ids) - question_stats["configured_present"]
    inactive_configured_count = (
        question_stats["configured_present"] - question_stats["configured_active"]
    )
    _append_count_problem(
        problems,
        count=missing_configured_count,
        severity="error",
        code="sociodemographic_configured_questions_missing",
        title="Perguntas sociodemográficas configuradas em falta",
        description=(
            "Nem todas as perguntas definidas em SOCIO_QUESTIONS existem na base "
            "de dados."
        ),
    )
    _append_count_problem(
        problems,
        count=inactive_configured_count,
        severity="warning",
        code="sociodemographic_configured_questions_inactive",
        title="Perguntas sociodemográficas configuradas inativas",
        description=(
            "Existem perguntas definidas em SOCIO_QUESTIONS que estão inativas."
        ),
    )

    criteria_status = []
    eligibility_configuration_ready = True
    for criterion in criteria:
        key = criterion["key"]
        question = criterion_questions.get(criterion["question_id"])
        criterion_ready = True

        if question is None:
            criterion_ready = False
            problems.append(
                _problem(
                    "error",
                    f"normative_eligibility_{key}_question_missing",
                    f"Pergunta normativa de {criterion['label']} ausente",
                    (
                        "Não foi localizada a pergunta pelo identificador estável "
                        f"{criterion['question_id']}."
                    ),
                )
            )
        else:
            if not question["is_active"]:
                criterion_ready = False
                problems.append(
                    _problem(
                        "error",
                        f"normative_eligibility_{key}_question_inactive",
                        f"Pergunta normativa de {criterion['label']} inativa",
                        "A pergunta necessária à elegibilidade não está ativa.",
                    )
                )
            if not question["required"]:
                criterion_ready = False
                problems.append(
                    _problem(
                        "warning",
                        f"normative_eligibility_{key}_question_not_required",
                        f"Pergunta normativa de {criterion['label']} não obrigatória",
                        (
                            "A pergunta necessária à elegibilidade está configurada "
                            "como opcional."
                        ),
                    )
                )
            if question["question_type"] != "radio":
                criterion_ready = False
                problems.append(
                    _problem(
                        "error",
                        f"normative_eligibility_{key}_invalid_type",
                        f"Tipo inválido na pergunta de {criterion['label']}",
                        "A pergunta normativa deve disponibilizar opções radio.",
                    )
                )

            missing_values = criterion["known_values"] - criterion_choices[
                criterion["question_id"]
            ]
            if missing_values:
                criterion_ready = False
                problems.append(
                    _problem(
                        "error",
                        f"normative_eligibility_{key}_options_missing",
                        f"Opções normativas de {criterion['label']} em falta",
                        (
                            "Não estão configurados todos os valores reconhecidos "
                            "pelo serviço de elegibilidade."
                        ),
                        len(missing_values),
                    )
                )

        eligibility_configuration_ready &= criterion_ready
        criteria_status.append(
            {
                "label": criterion["label"],
                "question_id": criterion["question_id"],
                "expected_value": criterion["expected_value"],
                "ready": criterion_ready,
            }
        )

    return {
        "summary": {
            "category_count": category_count,
            "sociodemographic_category_count": sociodemographic_category_count,
            "question_count": question_stats["total"],
            "active_question_count": question_stats["active"],
            "configured_question_count": len(configured_ids),
            "configured_question_present_count": question_stats[
                "configured_present"
            ],
            "eligibility_configuration_ready": eligibility_configuration_ready,
            "criteria": criteria_status,
        },
        "problems": problems,
    }


def _normative_versions_health(
    *,
    active_version=_NOT_PROVIDED,
    participant_counts=None,
):
    versions = get_normative_versions()
    status = NormativeDatasetVersion.Status
    version_stats = versions.aggregate(
        total=Count("id", distinct=True),
        active=Count(
            "id",
            filter=Q(status=status.ACTIVE),
            distinct=True,
        ),
        drafts=Count(
            "id",
            filter=Q(status=status.DRAFT),
            distinct=True,
        ),
        retired=Count(
            "id",
            filter=Q(status=status.RETIRED),
            distinct=True,
        ),
        active_without_prepared=Count(
            "id",
            filter=Q(status=status.ACTIVE, prepared_at__isnull=True),
            distinct=True,
        ),
        active_without_activated=Count(
            "id",
            filter=Q(status=status.ACTIVE, activated_at__isnull=True),
            distinct=True,
        ),
        retired_without_prepared=Count(
            "id",
            filter=Q(status=status.RETIRED, prepared_at__isnull=True),
            distinct=True,
        ),
        retired_without_activated=Count(
            "id",
            filter=Q(status=status.RETIRED, activated_at__isnull=True),
            distinct=True,
        ),
        draft_with_activated=Count(
            "id",
            filter=Q(status=status.DRAFT, activated_at__isnull=False),
            distinct=True,
        ),
        prepared_after_activation=Count(
            "id",
            filter=Q(prepared_at__gt=F("activated_at")),
            distinct=True,
        ),
    )
    if active_version is _NOT_PROVIDED:
        active_version = get_active_normative_version()
    if participant_counts is None:
        participant_counts = get_normative_participant_counts()

    problems = []
    if version_stats["active"] > 1:
        problems.append(
            _problem(
                "error",
                "multiple_active_normative_versions",
                "Existe mais de uma versão normativa ativa",
                "A aplicação requer no máximo uma versão normativa ativa.",
                version_stats["active"],
            )
        )
    elif version_stats["active"] == 0:
        problems.append(
            _problem(
                "warning",
                "no_active_normative_version",
                "Não existe versão normativa ativa",
                (
                    "Os relatórios não dispõem de uma base normativa ativa para "
                    "novas associações."
                ),
            )
        )

    for metric, code, title, description in (
        (
            "active_without_prepared",
            "active_normative_version_without_prepared_at",
            "Versão ativa sem preparação registada",
            "Existem versões ativas sem prepared_at.",
        ),
        (
            "active_without_activated",
            "active_normative_version_without_activated_at",
            "Versão ativa sem ativação registada",
            "Existem versões ativas sem activated_at.",
        ),
        (
            "retired_without_prepared",
            "retired_normative_version_without_prepared_at",
            "Versão histórica sem preparação registada",
            "Existem versões históricas sem prepared_at.",
        ),
        (
            "retired_without_activated",
            "retired_normative_version_without_activated_at",
            "Versão histórica sem ativação registada",
            "Existem versões históricas sem activated_at.",
        ),
        (
            "draft_with_activated",
            "draft_normative_version_with_activated_at",
            "Rascunho com data de ativação",
            "Existem versões draft com activated_at preenchido.",
        ),
        (
            "prepared_after_activation",
            "normative_version_prepared_after_activation",
            "Preparação posterior à ativação",
            "Existem versões cuja preparação é posterior à ativação.",
        ),
    ):
        _append_count_problem(
            problems,
            count=version_stats[metric],
            severity="error",
            code=code,
            title=title,
            description=description,
        )

    if active_version is not None and participant_counts["not_in_active_version"]:
        problems.append(
            _problem(
                "info",
                "normative_participants_not_in_active_version",
                "Existem novos participantes normativos",
                (
                    "Estes participantes ainda não fazem parte do snapshot da "
                    "versão normativa ativa."
                ),
                participant_counts["not_in_active_version"],
            )
        )

    return {
        "summary": {
            "total_version_count": version_stats["total"],
            "active_version_count": version_stats["active"],
            "draft_version_count": version_stats["drafts"],
            "retired_version_count": version_stats["retired"],
            "active_version": active_version,
            "active_participant_count": participant_counts["active_version"],
            "total_participant_count": participant_counts["total"],
            "new_participant_count": participant_counts[
                "not_in_active_version"
            ],
        },
        "problems": problems,
    }


def get_system_health_report(
    *,
    active_normative_version=_NOT_PROVIDED,
    normative_participant_counts=None,
):
    structure = _scientific_structure_health()
    sociodemographic = _sociodemographic_health()
    normative = _normative_versions_health(
        active_version=active_normative_version,
        participant_counts=normative_participant_counts,
    )
    problems = [
        *structure["problems"],
        *sociodemographic["problems"],
        *normative["problems"],
    ]
    issue_counts = Counter(problem["severity"] for problem in problems)

    return {
        "structure": structure["summary"],
        "sociodemographic": sociodemographic["summary"],
        "normative": normative["summary"],
        "problems": problems,
        "issue_counts": {
            "error": issue_counts["error"],
            "warning": issue_counts["warning"],
            "info": issue_counts["info"],
            "total": len(problems),
        },
    }


def run_configuration_health_checks():
    """Return stable, structured checks for reuse outside the HTML view."""
    return get_system_health_report()["problems"]
