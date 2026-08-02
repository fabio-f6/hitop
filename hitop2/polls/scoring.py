from collections import defaultdict
from polls.models import UserAnswer

def calculate_average(values):

    if not values:
        return None

    return sum(values) / len(values)

def calculate_scale_scores_from_answers(answers):

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

    for scale, values in responses_by_scale.items():

        scale_scores[scale] = calculate_average(values)

    return scale_scores

def calculate_scale_scores(submission):

    answers = UserAnswer.objects.filter(
        submission=submission
    ).select_related(
        "question__scale"
    )

    return calculate_scale_scores_from_answers(
        answers
    )