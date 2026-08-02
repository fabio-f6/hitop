from django.core.management.base import BaseCommand

from polls.models import (
    NormativeParticipant,
    NormativeAnswer,
    NormativeScaleScore,
)

from polls.scoring import (
    calculate_scale_scores_from_answers,
)


class Command(BaseCommand):

    help = "Calcula os valores brutos da base normativa."

    def handle(self, *args, **options):

        NormativeScaleScore.objects.all().delete()

        participants = NormativeParticipant.objects.all()

        self.stdout.write(
            f"A calcular {participants.count()} participantes..."
        )

        for participant in participants:

            answers = (
                NormativeAnswer.objects
                .filter(participant=participant)
                .select_related("question__scale")
            )

            scale_scores = calculate_scale_scores_from_answers(
                answers
            )

            for scale, raw_score in scale_scores.items():

                if raw_score is None:
                    continue

                NormativeScaleScore.objects.create(
                    participant=participant,
                    scale=scale,
                    raw_score=raw_score,
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Foram calculados {NormativeScaleScore.objects.count()} valores."
            )
        )