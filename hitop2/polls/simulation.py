import random

from django.utils import timezone

from polls.models import UserAnswer
from polls.questions import get_questions_for_submission


NULL_PROBABILITY = 0.25


def simulate_submission(submission):

    questions = get_questions_for_submission(submission)

    for question in questions:

        if submission.simulation_mode == "simulated":

            answer = str(random.randint(1, 4))

        elif submission.simulation_mode == "simulated_nulls":

            if random.random() < NULL_PROBABILITY:
                answer = "5"
            else:
                answer = str(random.randint(1, 4))

        else:
            return

        UserAnswer.objects.create(
            user=submission.user,
            submission=submission,
            question=question,
            answer=answer,
        )

    submission.completed = True
    submission.completed_at = timezone.now()
    submission.is_open = False
    submission.save()