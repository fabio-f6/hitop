from django.db import transaction
from django.utils import timezone

from .models import (
    DynamicAnswer,
    NormativeAnswer,
    NormativeParticipant,
    NormativeScaleScore,
    NormativeSpectrumScore,
    QuestionnaireSubmission,
    UserAnswer,
)
from .scoring import calculate_scale_scores_from_answers
from .spectrum_scores import calculate_spectrum_scores


class NormativeExportError(Exception):
    """Base exception for failures that safely abort a normative export."""


class SubmissionAlreadyExported(NormativeExportError):
    """Raised when a submission has already been exported."""


SEX_LABELS = {
    "1": "Feminino",
    "2": "Masculino",
    "4": "Intersexo",
}


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
    locked_submission = QuestionnaireSubmission.objects.select_for_update().get(
        pk=submission.pk
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

    scale_scores = calculate_scale_scores_from_answers(normative_answers)
    spectrum_scores = calculate_spectrum_scores(scale_scores)

    NormativeScaleScore.objects.bulk_create([
        NormativeScaleScore(
            participant=participant,
            scale=scale,
            raw_score=data["score"],
        )
        for scale, data in scale_scores.items()
        if data["score"] is not None
    ])
    NormativeSpectrumScore.objects.bulk_create([
        NormativeSpectrumScore(
            participant=participant,
            spectrum=spectrum,
            raw_score=data["score"],
        )
        for spectrum, data in spectrum_scores.items()
        if data["score"] is not None
    ])

    locked_submission.normative_status = QuestionnaireSubmission.NormativeStatus.EXPORTED
    locked_submission.normative_exported_at = timezone.now()
    locked_submission.save(update_fields=["normative_status", "normative_exported_at"])

    return participant
