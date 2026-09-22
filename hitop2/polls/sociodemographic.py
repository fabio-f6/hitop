import json

from .models import DynamicAnswer, QuestionCategory


SOCIODEMOGRAPHIC_CATEGORY_NAME = "Dados Sociodemográficos"


def get_sociodemographic_category():
    return QuestionCategory.objects.filter(
        name=SOCIODEMOGRAPHIC_CATEGORY_NAME,
    ).first()


def dynamic_answer_value(answer):
    if answer.question.question_type != "checkbox":
        return answer.answer_value
    try:
        value = json.loads(answer.answer_value)
    except json.JSONDecodeError:
        return [answer.answer_value]
    return value if isinstance(value, list) else [answer.answer_value]


def question_is_visible(question, values):
    if not question.show_if_question:
        return True
    parent_value = values.get(question.show_if_question, "")
    if not isinstance(parent_value, list):
        parent_value = [parent_value]
    return bool(set(parent_value) & set(question.show_if_values))


def replace_dynamic_answers(*, user, submission, questions, values):
    """Replace answers for the supplied configured dynamic questions."""
    questions = list(questions)
    DynamicAnswer.objects.filter(
        user=user,
        submission=submission,
        question__in=questions,
    ).delete()

    answers = []
    for question in questions:
        value = values.get(question.question_id)
        if value in (None, "", []):
            continue
        answers.append(DynamicAnswer(
            user=user,
            submission=submission,
            question=question,
            answer_value=(
                json.dumps(value) if isinstance(value, list) else str(value)
            ),
        ))
    return DynamicAnswer.objects.bulk_create(answers)
