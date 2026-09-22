from django.db import transaction
from django.utils import timezone

from .models import (
    DynamicAnswer,
    NormativeAnswer,
    NormativeParticipant,
    QuestionnaireSubmission,
    UserAnswer,
)


class NormativeExportError(Exception):
    """Base exception for failures that safely abort a normative export."""


class SubmissionAlreadyExported(NormativeExportError):
    """Raised when a submission has already been exported."""


class TestSubmissionExportBlocked(NormativeExportError):
    """Raised when test or simulated data reaches the real export boundary."""


SEX_LABELS = {
    "1": "Feminino",
    "2": "Masculino",
    "4": "Intersexo",
}

# Stable identifiers and stored values from the dynamic sociodemographic
# questionnaire (polls/socio_questions.json).
PORTUGUESE_LANGUAGE_QUESTION_ID = "PT_lang"
PORTUGUESE_LANGUAGE_YES_VALUE = "2"
PORTUGUESE_LANGUAGE_VALUES = {"1", "2"}
MENTAL_DIAGNOSIS_QUESTION_ID = "mental_diagnosis"
MENTAL_DIAGNOSIS_NEVER_VALUE = "1"
MENTAL_DIAGNOSIS_VALUES = {"1", "2", "3"}


def is_test_or_simulated_submission(submission):
    if submission.is_test_data or submission.simulation_mode != "normal":
        return True
    try:
        return submission.user.userprofile.is_test_data
    except AttributeError:
        return False


def evaluate_normative_eligibility(submission):
    """Evaluate the two scientific inclusion criteria without side effects.

    ``eligible`` is None when an answer is missing, duplicated, or contains a
    value that cannot be safely interpreted.
    """
    criteria = (
        (
            PORTUGUESE_LANGUAGE_QUESTION_ID,
            PORTUGUESE_LANGUAGE_YES_VALUE,
            PORTUGUESE_LANGUAGE_VALUES,
            "Português-Europeu",
        ),
        (
            MENTAL_DIAGNOSIS_QUESTION_ID,
            MENTAL_DIAGNOSIS_NEVER_VALUE,
            MENTAL_DIAGNOSIS_VALUES,
            "saúde mental",
        ),
    )
    stored_answers = {}
    for question_id, answer_value in DynamicAnswer.objects.filter(
        submission=submission,
        question__question_id__in=[criterion[0] for criterion in criteria],
    ).values_list("question__question_id", "answer_value"):
        stored_answers.setdefault(question_id, []).append(answer_value.strip())

    unresolved = []
    failed = []
    for question_id, expected, known_values, description in criteria:
        values = stored_answers.get(question_id, [])
        if len(values) != 1:
            unresolved.append(f"resposta de {description} ausente ou ambígua")
            continue
        value = values[0]
        if value not in known_values:
            unresolved.append(f"resposta de {description} não reconhecida")
        elif value != expected:
            failed.append(f"critério de {description} não cumprido")

    # An explicit failure is decisive even if the other criterion is absent.
    if failed:
        return {"eligible": False, "reason": "; ".join(failed)}
    if unresolved:
        return {"eligible": None, "reason": "; ".join(unresolved)}
    return {"eligible": True, "reason": "os dois critérios foram cumpridos"}


def process_normative_eligibility(submission):
    """Evaluate a completed submission and export it exactly once if eligible."""
    submission.refresh_from_db(fields=[
        "completed",
        "normative_status",
        "is_test_data",
        "simulation_mode",
    ])
    if is_test_or_simulated_submission(submission):
        if not submission.completed:
            return {
                "eligible": None,
                "reason": "submission ainda não concluída",
                "exported": False,
                "test_data": True,
            }
        result = evaluate_normative_eligibility(submission)
        return {
            **result,
            "exported": False,
            "test_data": True,
        }

    if submission.normative_status != QuestionnaireSubmission.NormativeStatus.PENDING:
        return {
            "eligible": submission.normative_status
            == QuestionnaireSubmission.NormativeStatus.EXPORTED,
            "reason": f"submission já está {submission.normative_status}",
        }
    if not submission.completed:
        return {"eligible": None, "reason": "submission ainda não concluída"}

    result = evaluate_normative_eligibility(submission)
    if result["eligible"] is False:
        QuestionnaireSubmission.objects.filter(
            pk=submission.pk,
            normative_status=QuestionnaireSubmission.NormativeStatus.PENDING,
        ).update(normative_status=QuestionnaireSubmission.NormativeStatus.INELIGIBLE)
        submission.normative_status = QuestionnaireSubmission.NormativeStatus.INELIGIBLE
    elif result["eligible"] is True:
        export_submission_to_normative(submission)
        submission.normative_status = QuestionnaireSubmission.NormativeStatus.EXPORTED
    return result


def _normative_demographics(submission):
    answers = dict(
        DynamicAnswer.objects.filter(
            submission=submission,
            question__question_id__in=("age", "sex"),
        ).values_list("question__question_id", "answer_value")
    )

    age_value = answers.get("age", "").strip()
    try:
        age = int(age_value) if age_value else None
    except ValueError as exc:
        raise NormativeExportError("A idade normativa não é um número inteiro.") from exc

    sex_value = answers.get("sex", "").strip()
    sex = SEX_LABELS.get(sex_value, "")
    if sex_value and not sex:
        raise NormativeExportError("O sexo normativo tem um valor desconhecido.")

    return {"age": age, "sex": sex}


@transaction.atomic
def export_submission_to_normative(submission):
    """Copy one clinical submission into the anonymous normative data set."""
    locked_submission = (
        QuestionnaireSubmission.objects.select_for_update()
        .select_related("user")
        .get(pk=submission.pk)
    )
    if is_test_or_simulated_submission(locked_submission):
        raise TestSubmissionExportBlocked(
            "Dados de teste ou simulação não podem ser exportados para a "
            "base normativa real."
        )
    if locked_submission.normative_status == QuestionnaireSubmission.NormativeStatus.EXPORTED:
        raise SubmissionAlreadyExported("Esta submissão já foi exportada.")

    participant = NormativeParticipant.objects.create(
        **_normative_demographics(locked_submission)
    )

    clinical_answers = list(
        UserAnswer.objects.filter(submission=locked_submission)
        .select_related("question__scale__subfactor__spectra")
    )
    normative_answers = [
        NormativeAnswer(
            participant=participant,
            question=answer.question,
            answer=answer.answer,
        )
        for answer in clinical_answers
    ]
    NormativeAnswer.objects.bulk_create(normative_answers)

    locked_submission.normative_status = QuestionnaireSubmission.NormativeStatus.EXPORTED
    locked_submission.normative_exported_at = timezone.now()
    locked_submission.save(update_fields=["normative_status", "normative_exported_at"])

    return participant
