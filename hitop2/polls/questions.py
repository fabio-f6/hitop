from polls.models import Question


def get_questions_for_submission(submission):

    return Question.objects.filter(
        scale__subfactor__spectra__in=submission.spectra.all()
    ).distinct()