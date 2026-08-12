from collections import defaultdict

from polls.models import UserAnswer


def calculate_average(values):

    if not values:
        return None

    return sum(values) / len(values)

def calculate_scale_scores_from_answers(answers):

    responses_by_scale = defaultdict(list)
    total_items_by_scale = defaultdict(int)

    for answer in answers:

        scale = answer.question.scale

        # Conta todos os itens da escala
        total_items_by_scale[scale] += 1

        # Ignora "Não sei / Não aplicável"
        if answer.answer == "5":
            continue

        responses_by_scale[scale].append(
            int(answer.answer)
        )

    scale_scores = {}

    for scale, total_items in total_items_by_scale.items():

        valid_answers = responses_by_scale[scale]

        missing_answers = (
            total_items - len(valid_answers)
        )

        missing_percentage = (
            missing_answers / total_items
        ) * 100

        is_valid = (
            missing_percentage < 25
        )

        scale_scores[scale] = {

            "score": (
                calculate_average(valid_answers)
                if is_valid
                else None
            ),

            "missing_answers":
                missing_answers,

            "missing_percentage":
                missing_percentage,

            "total_items":
                total_items,

            "is_valid":
                is_valid,

        }

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