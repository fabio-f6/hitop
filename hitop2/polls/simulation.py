import random
from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from polls.models import QuestionnaireSubmission, UserAnswer
from polls.normative_export import (
    MENTAL_DIAGNOSIS_NEVER_VALUE,
    MENTAL_DIAGNOSIS_QUESTION_ID,
    PORTUGUESE_LANGUAGE_QUESTION_ID,
    PORTUGUESE_LANGUAGE_YES_VALUE,
    process_normative_eligibility,
)
from polls.questions import get_questions_for_submission
from polls.sociodemographic import (
    get_sociodemographic_category,
    question_is_visible,
    replace_dynamic_answers,
)


HITOP_RESPONSE_VALUES = ("1", "2", "3", "4")
VALID_HITOP_ANSWERS = {
    value for value, _label in UserAnswer._meta.get_field("answer").choices
}
PROFILE_WEIGHTS = {
    QuestionnaireSubmission.SimulationResponseProfile.RANDOM: (1, 1, 1, 1),
    QuestionnaireSubmission.SimulationResponseProfile.LOW: (45, 35, 15, 5),
    QuestionnaireSubmission.SimulationResponseProfile.MEDIUM: (10, 40, 40, 10),
    QuestionnaireSubmission.SimulationResponseProfile.HIGH: (5, 15, 35, 45),
}


class SimulationConfigurationError(ValueError):
    pass


class SimulationPermissionError(SimulationConfigurationError):
    pass


def _profile_answer(rng, profile):
    weights = PROFILE_WEIGHTS.get(profile, PROFILE_WEIGHTS["random"])
    return rng.choices(HITOP_RESPONSE_VALUES, weights=weights, k=1)[0]


def _incorrect_attention_answer(rng, expected_answer):
    alternatives = [
        value for value in HITOP_RESPONSE_VALUES if value != expected_answer
    ]
    return rng.choice(alternatives)


def _attention_answers(questions, rng, mode):
    attention_questions = [
        question for question in questions if question.is_attention_check
    ]
    answers = {}
    for question in attention_questions:
        if question.expected_answer in VALID_HITOP_ANSWERS:
            answers[question.id] = question.expected_answer
        else:
            # Invalid scientific configuration is already reported by system health.
            # A valid questionnaire answer keeps simulation storage predictable.
            answers[question.id] = _profile_answer(rng, "random")

    failure_count = 0
    if mode == QuestionnaireSubmission.SimulationAttentionMode.ONE_FAILURE:
        failure_count = min(1, len(attention_questions))
    elif mode == QuestionnaireSubmission.SimulationAttentionMode.MULTIPLE_FAILURES:
        failure_count = min(2, len(attention_questions))

    for question in rng.sample(attention_questions, failure_count):
        answers[question.id] = _incorrect_attention_answer(
            rng,
            question.expected_answer,
        )
    return answers


def _apply_missing_answers(questions, answers, rng, percentage):
    if not percentage:
        return

    by_scale = defaultdict(list)
    for question in questions:
        if not question.is_attention_check:
            by_scale[question.scale_id].append(question)

    for scale_questions in by_scale.values():
        # A fixed sample size makes boundary scenarios reproducible while staying
        # as close as the scale's discrete item count permits to the requested rate.
        missing_count = int((len(scale_questions) * percentage / 100) + 0.5)
        missing_count = min(missing_count, len(scale_questions))
        for question in rng.sample(scale_questions, missing_count):
            answers[question.id] = "5"


def _simulate_hitop_answers(submission, rng):
    questions = list(
        get_questions_for_submission(submission)
        .select_related("scale")
        .order_by("id")
    )
    answers = {
        question.id: _profile_answer(rng, submission.simulation_response_profile)
        for question in questions
        if not question.is_attention_check
    }
    answers.update(_attention_answers(
        questions,
        rng,
        submission.simulation_attention_mode,
    ))
    _apply_missing_answers(
        questions,
        answers,
        rng,
        submission.effective_simulation_missing_percentage,
    )

    UserAnswer.objects.filter(
        submission=submission,
        question__in=questions,
    ).delete()
    UserAnswer.objects.bulk_create([
        UserAnswer(
            user=submission.user,
            submission=submission,
            question=question,
            answer=answers[question.id],
        )
        for question in questions
    ])


def _criterion_values(mode):
    modes = QuestionnaireSubmission.SociodemographicSimulationMode
    language_value = PORTUGUESE_LANGUAGE_YES_VALUE
    mental_value = MENTAL_DIAGNOSIS_NEVER_VALUE

    if mode in (modes.INELIGIBLE_LANGUAGE, modes.INELIGIBLE_BOTH):
        language_value = None
    if mode in (modes.INELIGIBLE_MENTAL_HEALTH, modes.INELIGIBLE_BOTH):
        mental_value = None
    if mode == modes.PENDING_MISSING:
        mental_value = "__missing__"

    return {
        PORTUGUESE_LANGUAGE_QUESTION_ID: language_value,
        MENTAL_DIAGNOSIS_QUESTION_ID: mental_value,
    }


def _configured_choice_values(question):
    choices = sorted(
        question.choices.all(),
        key=lambda choice: (choice.order, choice.id),
    )
    return [choice.value for choice in choices]


def _criterion_answer(question, requested_value, rng):
    choices = _configured_choice_values(question)
    if requested_value == "__missing__":
        return None
    if requested_value is not None:
        if requested_value not in choices:
            raise SimulationConfigurationError(
                f"A opção normativa {requested_value!r} não existe em "
                f"{question.question_id!r}."
            )
        return requested_value

    expected = {
        PORTUGUESE_LANGUAGE_QUESTION_ID: PORTUGUESE_LANGUAGE_YES_VALUE,
        MENTAL_DIAGNOSIS_QUESTION_ID: MENTAL_DIAGNOSIS_NEVER_VALUE,
    }[question.question_id]
    alternatives = [value for value in choices if value != expected]
    if not alternatives:
        raise SimulationConfigurationError(
            f"{question.question_id!r} não tem uma opção que falhe o critério."
        )
    return rng.choice(alternatives)


def _generic_dynamic_answer(question, rng):
    choices = _configured_choice_values(question)
    if question.question_type == "radio":
        return rng.choice(choices) if choices else None
    if question.question_type == "checkbox":
        # Without exclusivity metadata, one configured option is the only
        # combination guaranteed to be semantically valid.
        return [rng.choice(choices)] if choices else None
    if question.question_type == "number":
        return str(rng.randint(18, 80))
    if question.question_type == "text":
        return "Resposta simulada"
    if question.question_type == "matrix":
        return rng.choice(choices) if choices else None
    return None


def _questions_in_dependency_order(questions):
    remaining = list(questions)
    ordered = []
    processed_ids = set()
    configured_ids = {question.question_id for question in remaining}

    while remaining:
        ready = [
            question for question in remaining
            if not question.show_if_question
            or question.show_if_question in processed_ids
            or question.show_if_question not in configured_ids
        ]
        if not ready:
            # Cyclic dependencies cannot be displayed by the real form either.
            ordered.extend(remaining)
            break
        for question in ready:
            ordered.append(question)
            processed_ids.add(question.question_id)
            remaining.remove(question)
    return ordered


def _simulate_sociodemographic_answers(submission, rng):
    mode = submission.sociodemographic_simulation_mode
    if mode == QuestionnaireSubmission.SociodemographicSimulationMode.NORMAL:
        return

    category = get_sociodemographic_category()
    if category is None:
        raise SimulationConfigurationError(
            "O questionário sociodemográfico não está configurado."
        )

    questions = list(
        category.questions.filter(is_active=True)
        .prefetch_related("choices")
        .order_by("order", "id")
    )
    by_id = {question.question_id: question for question in questions}
    missing_criteria = {
        question_id
        for question_id in (
            PORTUGUESE_LANGUAGE_QUESTION_ID,
            MENTAL_DIAGNOSIS_QUESTION_ID,
        )
        if question_id not in by_id
    }
    if missing_criteria:
        raise SimulationConfigurationError(
            "Faltam perguntas normativas configuradas: "
            + ", ".join(sorted(missing_criteria))
        )

    criteria = _criterion_values(mode)
    values = {}
    for question in _questions_in_dependency_order(questions):
        if not question_is_visible(question, values):
            continue
        if question.question_id in criteria:
            value = _criterion_answer(
                question,
                criteria[question.question_id],
                rng,
            )
        else:
            value = _generic_dynamic_answer(question, rng)
        if value not in (None, "", []):
            values[question.question_id] = value

    replace_dynamic_answers(
        user=submission.user,
        submission=submission,
        questions=questions,
        values=values,
    )

    section_count = len({
        question.section or category.name for question in questions
    })
    submission.sociodemographic_completed = True
    submission.sociodemographic_step = section_count
    submission.save(update_fields=[
        "sociodemographic_completed",
        "sociodemographic_step",
    ])


@transaction.atomic
def simulate_submission(submission):
    """Generate configured test data and run the real completion pipeline."""
    if submission.simulation_mode == "normal":
        return None

    try:
        patient_profile = submission.user.userprofile
        test_owner = patient_profile.test_environment_owner
        owner_is_administrator = (
            test_owner is not None
            and test_owner.userprofile.user_type == "admin"
        )
    except AttributeError:
        patient_profile = None
        owner_is_administrator = False
    if (
        not submission.is_test_data
        or patient_profile is None
        or not patient_profile.is_test_data
        or not owner_is_administrator
    ):
        raise SimulationPermissionError(
            "A simulação está reservada ao Ambiente de Teste Profissional."
        )

    rng = random.Random(submission.simulation_seed)
    _simulate_sociodemographic_answers(submission, rng)
    _simulate_hitop_answers(submission, rng)

    submission.completed = True
    submission.completed_at = timezone.now()
    submission.is_open = False
    submission.save(update_fields=["completed", "completed_at", "is_open"])

    return process_normative_eligibility(submission)
