from django.db.models import Q

from polls.models import Question, Spectra


def get_scientific_spectra():
    """Return selectable HiTOP spectra, excluding attention-check-only branches."""
    return Spectra.objects.filter(
        subfactors__scales__questions__is_attention_check=False,
    ).distinct()


def get_questions_for_submission(submission):
    """Combine selected scientific questions with automatic attention checks."""
    return Question.objects.filter(
        Q(
            is_attention_check=False,
            scale__subfactor__spectra__in=submission.spectra.all(),
        )
        | Q(is_attention_check=True)
    ).distinct()
