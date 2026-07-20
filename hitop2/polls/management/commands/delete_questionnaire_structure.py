from django.core.management.base import BaseCommand

from polls.models import (
    Question,
    Scale,
    Subfactor,
    Spectra,
)


class Command(BaseCommand):

    help = "Apaga toda a estrutura do questionário HiTOP"

    def handle(self, *args, **kwargs):

        total_questions = Question.objects.count()
        total_scales = Scale.objects.count()
        total_subfactors = Subfactor.objects.count()
        total_spectra = Spectra.objects.count()

        Question.objects.all().delete()
        Scale.objects.all().delete()
        Subfactor.objects.all().delete()
        Spectra.objects.all().delete()

        self.stdout.write(
            self.style.SUCCESS(
                (
                    "Estrutura do questionário HiTOP apagada com sucesso.\n\n"
                    f"Questions: {total_questions}\n"
                    f"Scales: {total_scales}\n"
                    f"Subfactors: {total_subfactors}\n"
                    f"Spectra: {total_spectra}"
                )
            )
        )