from collections import Counter

from django.db.models import Count, F, Q

from polls.models import (
    DynamicChoice,
    DynamicQuestion,
    NormativeDatasetVersion,
    NormativeParticipant,
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


def _problem(severity, code, title, description, count=None, details=None):
    problem = {
        "severity": severity,
        "code": code,
        "title": title,
        "description": description,
    }
    if count is not None:
        problem["count"] = count
    if details:
        problem["details"] = details
    return problem


def _append_count_problem(
    problems,
    *,
    count,
    severity,
    code,
    title,
    description,
    details=None,
):
    if count:
        problems.append(
            _problem(
                severity,
                code,
                title,
                description,
                count,
                details,
            )
        )


def _is_empty(value):
    return not value or not value.strip()


def evaluate_scientific_structure(spectra, subfactors, scales, questions):
    """Evaluate structure rows and return the health report plus node issues.

    This is the canonical scientific-structure health evaluation.  Callers may
    pass already-loaded rows, allowing read-only visualisations to reuse the
    exact health semantics without issuing another set of queries.
    """
    spectra = list(spectra)
    subfactors = list(subfactors)
    scales = list(scales)
    questions = list(questions)
    subfactor_counts = Counter(row["spectra_id"] for row in subfactors)
    scale_counts = Counter(row["subfactor_id"] for row in scales)
    question_counts = Counter(row["scale_id"] for row in questions)
    valid_expected_answers = {value for value, _label in Question.ANSWER_CHOICES}
    spectrum_by_id = {row["id"]: row for row in spectra}
    subfactor_by_id = {row["id"]: row for row in subfactors}
    scale_by_id = {row["id"]: row for row in scales}

    def named(value, entity, entity_id):
        return (
            value.strip()
            if value and value.strip()
            else f"{entity} #{entity_id} (sem nome)"
        )

    def spectrum_detail(row):
        return named(row["name"], "Spectrum", row["id"])

    def subfactor_detail(row):
        spectrum = spectrum_by_id[row["spectra_id"]]
        return (
            f'{named(row["name"], "Subfator", row["id"])} — '
            f'Spectrum: {named(spectrum["name"], "Spectrum", spectrum["id"])}'
        )

    def scale_detail(row):
        subfactor = subfactor_by_id[row["subfactor_id"]]
        spectrum = spectrum_by_id[subfactor["spectra_id"]]
        return (
            f'{named(row["name"], "Escala", row["id"])} — '
            f'Subfator: {named(subfactor["name"], "Subfator", subfactor["id"])}; '
            f'Spectrum: {named(spectrum["name"], "Spectrum", spectrum["id"])}'
        )

    def question_detail(row):
        scale = scale_by_id[row["scale_id"]]
        identifier = (
            row["item_code"].strip()
            if row["item_code"] and row["item_code"].strip()
            else f'Pergunta #{row["id"]}'
        )
        text = row["question_text"].strip() if row["question_text"] else "sem texto"
        if len(text) > 100:
            text = f"{text[:97]}…"
        return f'{identifier} — {text}; Escala: {named(scale["name"], "Escala", scale["id"])}'

    stats = {
        "spectra": {
            "total": len(spectra),
            "empty_name": sum(_is_empty(row["name"]) for row in spectra),
            "without_subfactors": sum(
                not subfactor_counts[row["id"]] for row in spectra
            ),
        },
        "subfactors": {
            "total": len(subfactors),
            "empty_name": sum(_is_empty(row["name"]) for row in subfactors),
            "without_scales": sum(not scale_counts[row["id"]] for row in subfactors),
        },
        "scales": {
            "total": len(scales),
            "empty_name": sum(_is_empty(row["name"]) for row in scales),
            "without_questions": sum(
                not question_counts[row["id"]] for row in scales
            ),
        },
        "questions": {
            "total": len(questions),
            "empty_item_code": sum(_is_empty(row["item_code"]) for row in questions),
            "empty_text": sum(_is_empty(row["question_text"]) for row in questions),
            "attention_missing_expected": sum(
                row["is_attention_check"] and _is_empty(row["expected_answer"])
                for row in questions
            ),
            "attention_invalid_expected": sum(
                row["is_attention_check"]
                and not _is_empty(row["expected_answer"])
                and row["expected_answer"] not in valid_expected_answers
                for row in questions
            ),
            "non_attention_with_expected": sum(
                not row["is_attention_check"]
                and not _is_empty(row["expected_answer"])
                for row in questions
            ),
        },
    }

    problems = []
    for layer, label, layer_stats in (
        ("spectra", "spectra", stats["spectra"]),
        ("subfactors", "subfatores", stats["subfactors"]),
        ("scales", "escalas", stats["scales"]),
        ("questions", "perguntas", stats["questions"]),
    ):
        if layer_stats["total"] == 0:
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

    for item_stats, suffix, label in (
        (stats["spectra"], "spectrum", "spectra"),
        (stats["subfactors"], "subfactor", "subfatores"),
        (stats["scales"], "scale", "escalas"),
    ):
        _append_count_problem(
            problems,
            count=item_stats["empty_name"],
            severity="error",
            code=f"empty_{suffix}_name",
            title=f"Existem {label} sem nome",
            description="Foram encontrados elementos científicos com nome vazio.",
            details={
                "spectrum": [
                    spectrum_detail(row)
                    for row in spectra
                    if _is_empty(row["name"])
                ],
                "subfactor": [
                    subfactor_detail(row)
                    for row in subfactors
                    if _is_empty(row["name"])
                ],
                "scale": [
                    scale_detail(row)
                    for row in scales
                    if _is_empty(row["name"])
                ],
            }[suffix],
        )

    _append_count_problem(
        problems,
        count=stats["spectra"]["without_subfactors"],
        severity="warning",
        code="spectrum_without_subfactors",
        title="Spectra sem subfatores",
        description="Existem spectra que não contêm qualquer subfator.",
        details=[
            spectrum_detail(row)
            for row in spectra
            if not subfactor_counts[row["id"]]
        ],
    )
    _append_count_problem(
        problems,
        count=stats["subfactors"]["without_scales"],
        severity="warning",
        code="subfactor_without_scales",
        title="Subfatores sem escalas",
        description="Existem subfatores que não contêm qualquer escala.",
        details=[
            subfactor_detail(row)
            for row in subfactors
            if not scale_counts[row["id"]]
        ],
    )
    _append_count_problem(
        problems,
        count=stats["scales"]["without_questions"],
        severity="warning",
        code="scale_without_questions",
        title="Escalas sem perguntas",
        description="Existem escalas que não contêm qualquer pergunta.",
        details=[
            scale_detail(row)
            for row in scales
            if not question_counts[row["id"]]
        ],
    )
    _append_count_problem(
        problems,
        count=stats["questions"]["empty_item_code"],
        severity="error",
        code="question_empty_item_code",
        title="Perguntas sem item_code",
        description="Existem perguntas cujo identificador científico está vazio.",
        details=[
            question_detail(row)
            for row in questions
            if _is_empty(row["item_code"])
        ],
    )
    _append_count_problem(
        problems,
        count=stats["questions"]["empty_text"],
        severity="error",
        code="question_empty_text",
        title="Perguntas sem texto",
        description="Existem perguntas cujo texto está vazio.",
        details=[
            question_detail(row)
            for row in questions
            if _is_empty(row["question_text"])
        ],
    )
    _append_count_problem(
        problems,
        count=stats["questions"]["attention_missing_expected"],
        severity="warning",
        code="attention_check_missing_expected_answer",
        title="Attention checks sem resposta esperada",
        description=(
            "Existem perguntas marcadas como attention check sem expected_answer."
        ),
        details=[
            question_detail(row)
            for row in questions
            if row["is_attention_check"] and _is_empty(row["expected_answer"])
        ],
    )
    _append_count_problem(
        problems,
        count=stats["questions"]["attention_invalid_expected"],
        severity="error",
        code="attention_check_invalid_expected_answer",
        title="Attention checks com resposta esperada inválida",
        description=(
            "Existem respostas esperadas fora das opções válidas do questionário."
        ),
        details=[
            question_detail(row)
            for row in questions
            if row["is_attention_check"]
            and not _is_empty(row["expected_answer"])
            and row["expected_answer"] not in valid_expected_answers
        ],
    )
    _append_count_problem(
        problems,
        count=stats["questions"]["non_attention_with_expected"],
        severity="warning",
        code="non_attention_check_with_expected_answer",
        title="Perguntas comuns com resposta esperada",
        description=(
            "Existem perguntas que não são attention checks mas têm "
            "expected_answer configurada."
        ),
        details=[
            question_detail(row)
            for row in questions
            if not row["is_attention_check"]
            and not _is_empty(row["expected_answer"])
        ],
    )

    problem_by_code = {problem["code"]: problem for problem in problems}
    entity_issues = {}

    def attach(entity_type, entity_id, code):
        problem = problem_by_code.get(code)
        if problem:
            entity_issues.setdefault((entity_type, entity_id), []).append(
                {key: value for key, value in problem.items() if key != "count"}
            )

    for row in spectra:
        if _is_empty(row["name"]):
            attach("spectrum", row["id"], "empty_spectrum_name")
        if not subfactor_counts[row["id"]]:
            attach("spectrum", row["id"], "spectrum_without_subfactors")
    for row in subfactors:
        if _is_empty(row["name"]):
            attach("subfactor", row["id"], "empty_subfactor_name")
        if not scale_counts[row["id"]]:
            attach("subfactor", row["id"], "subfactor_without_scales")
    for row in scales:
        if _is_empty(row["name"]):
            attach("scale", row["id"], "empty_scale_name")
        if not question_counts[row["id"]]:
            attach("scale", row["id"], "scale_without_questions")
    for row in questions:
        if _is_empty(row["item_code"]):
            attach("question", row["id"], "question_empty_item_code")
        if _is_empty(row["question_text"]):
            attach("question", row["id"], "question_empty_text")
        if row["is_attention_check"] and _is_empty(row["expected_answer"]):
            attach("question", row["id"], "attention_check_missing_expected_answer")
        if (
            row["is_attention_check"]
            and not _is_empty(row["expected_answer"])
            and row["expected_answer"] not in valid_expected_answers
        ):
            attach("question", row["id"], "attention_check_invalid_expected_answer")
        if not row["is_attention_check"] and not _is_empty(row["expected_answer"]):
            attach("question", row["id"], "non_attention_check_with_expected_answer")

    return {
        "summary": {
            "spectra_count": stats["spectra"]["total"],
            "subfactor_count": stats["subfactors"]["total"],
            "scale_count": stats["scales"]["total"],
            "question_count": stats["questions"]["total"],
        },
        "problems": problems,
        "entity_issues": entity_issues,
    }


def _scientific_structure_health():
    return evaluate_scientific_structure(
        Spectra.objects.values("id", "name"),
        Subfactor.objects.values("id", "name", "spectra_id"),
        Scale.objects.values("id", "name", "subfactor_id"),
        Question.objects.values(
            "id",
            "scale_id",
            "item_code",
            "question_text",
            "is_attention_check",
            "expected_answer",
        ),
    )


def _sociodemographic_health():
    configured_ids = {question["id"] for question in SOCIO_QUESTIONS}
    configured_questions = {question["id"]: question for question in SOCIO_QUESTIONS}
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
            "label",
        )
    }
    criterion_choices = {question_id: set() for question_id in criterion_ids}
    for question_id, value in DynamicChoice.objects.filter(
        question__question_id__in=criterion_ids,
    ).values_list("question__question_id", "value"):
        criterion_choices[question_id].add(value)

    problems = []
    present_configured_ids = set(
        DynamicQuestion.objects.filter(question_id__in=configured_ids).values_list(
            "question_id", flat=True
        )
    )
    missing_configured_ids = configured_ids - present_configured_ids
    inactive_configured = list(
        DynamicQuestion.objects.filter(
            question_id__in=configured_ids, is_active=False
        ).values("question_id", "label")
    )
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
        details=[
            f'{question_id} — {configured_questions[question_id].get("label", "sem texto")}'
            for question_id in sorted(missing_configured_ids)
        ],
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
        details=[
            f'{row["question_id"]} — {row["label"]}'
            for row in inactive_configured
        ],
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
                    details=[f"Identificador esperado: {criterion['question_id']}"],
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
                        details=[f'{criterion["question_id"]} — {question["label"]}'],
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
                        details=[f'{criterion["question_id"]} — {question["label"]}'],
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
                        details=[
                            f'{criterion["question_id"]} — tipo atual: {question["question_type"]}'
                        ],
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
                        [
                            f"Valor em falta: {value}"
                            for value in sorted(missing_values)
                        ],
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

    def version_details(queryset):
        return [
            f'{row["name"]} (versão #{row["id"]}, {row["status"]})'
            for row in queryset.order_by("name", "id").values(
                "id", "name", "status"
            )
        ]

    problems = []
    if version_stats["active"] > 1:
        problems.append(
            _problem(
                "error",
                "multiple_active_normative_versions",
                "Existe mais de uma versão normativa ativa",
                "A aplicação requer no máximo uma versão normativa ativa.",
                version_stats["active"],
                version_details(versions.filter(status=status.ACTIVE)),
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

    for metric, code, title, description, version_filter in (
        (
            "active_without_prepared",
            "active_normative_version_without_prepared_at",
            "Versão ativa sem preparação registada",
            "Existem versões ativas sem prepared_at.",
            Q(status=status.ACTIVE, prepared_at__isnull=True),
        ),
        (
            "active_without_activated",
            "active_normative_version_without_activated_at",
            "Versão ativa sem ativação registada",
            "Existem versões ativas sem activated_at.",
            Q(status=status.ACTIVE, activated_at__isnull=True),
        ),
        (
            "retired_without_prepared",
            "retired_normative_version_without_prepared_at",
            "Versão histórica sem preparação registada",
            "Existem versões históricas sem prepared_at.",
            Q(status=status.RETIRED, prepared_at__isnull=True),
        ),
        (
            "retired_without_activated",
            "retired_normative_version_without_activated_at",
            "Versão histórica sem ativação registada",
            "Existem versões históricas sem activated_at.",
            Q(status=status.RETIRED, activated_at__isnull=True),
        ),
        (
            "draft_with_activated",
            "draft_normative_version_with_activated_at",
            "Rascunho com data de ativação",
            "Existem versões draft com activated_at preenchido.",
            Q(status=status.DRAFT, activated_at__isnull=False),
        ),
        (
            "prepared_after_activation",
            "normative_version_prepared_after_activation",
            "Preparação posterior à ativação",
            "Existem versões cuja preparação é posterior à ativação.",
            Q(prepared_at__gt=F("activated_at")),
        ),
    ):
        _append_count_problem(
            problems,
            count=version_stats[metric],
            severity="error",
            code=code,
            title=title,
            description=description,
            details=version_details(versions.filter(version_filter)),
        )

    if active_version is not None and participant_counts["not_in_active_version"]:
        participant_ids = NormativeParticipant.objects.filter(
            source=NormativeParticipant.Source.REAL,
        ).exclude(version_memberships__version=active_version).order_by(
            "id"
        ).values_list("id", flat=True)
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
                [f"Participante #{participant_id}" for participant_id in participant_ids],
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
