from django.core.management.base import BaseCommand

from polls.models import (
    NormativeAnswer,
    NormativeParticipant,
    NormativeScaleScore,
    NormativeSpectrumScore,
)
from polls.scoring import (
    calculate_scale_scores_from_answers,
)
from polls.spectrum_scores import (
    calculate_spectrum_scores,
)


class Command(BaseCommand):

    help = "Calcula os valores brutos da base normativa."

    def handle(self, *args, **options):

        NormativeScaleScore.objects.all().delete()
        NormativeSpectrumScore.objects.all().delete()

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

            spectrum_scores = calculate_spectrum_scores(
                scale_scores
            )

            for scale, scale_data in scale_scores.items():

                raw_score = scale_data["score"]

                if raw_score is None:
                    continue

                NormativeScaleScore.objects.create(
                    participant=participant,
                    scale=scale,
                    raw_score=raw_score,
                )

            for spectrum, spectrum_data in spectrum_scores.items():

                raw_score = spectrum_data["score"]

                if raw_score is None:
                    continue

                NormativeSpectrumScore.objects.create(
                    participant=participant,
                    spectrum=spectrum,
                    raw_score=raw_score,
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Foram calculados "
                f"{NormativeScaleScore.objects.count()} valores de escalas e "
                f"{NormativeSpectrumScore.objects.count()} valores de espectros."
            )
        )