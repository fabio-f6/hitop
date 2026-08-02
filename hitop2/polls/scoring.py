from collections import defaultdict

from polls.models import UserAnswer

from polls.questions import get_questions_for_submission

def calculate_average(values):

    if not values:
        return None

    return sum(values) / len(values)


def calculate_scale_scores(submission):

    questions = get_questions_for_submission(
        submission
    )

    scales = {
        question.scale
        for question in questions
    }

    answers = UserAnswer.objects.filter(
        submission=submission
    ).select_related(
        "question__scale"
    )

    responses_by_scale = defaultdict(list)

    for answer in answers:

        if answer.answer == "5":
            continue

        responses_by_scale[
            answer.question.scale
        ].append(
            int(answer.answer)
        )

    scale_scores = {}

    for scale in scales:

        values = responses_by_scale[scale]

        scale_scores[scale] = calculate_average(values)

    return scale_scores