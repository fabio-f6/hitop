from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

from polls.models import (
    UserAnswer,
    QuestionnaireSubmission,
    SociodemographicAnswer,
    DynamicAnswer
)

from website.models import UserProfile


class Command(BaseCommand):

    help = "Apaga todos os pacientes e respetivos dados"

    def handle(self, *args, **kwargs):

        patient_profiles = UserProfile.objects.filter(
            user_type="patient"
        )

        total_patients = patient_profiles.count()

        for profile in patient_profiles:

            user = profile.user

            UserAnswer.objects.filter(
                user=user
            ).delete()

            QuestionnaireSubmission.objects.filter(
                user=user
            ).delete()

            SociodemographicAnswer.objects.filter(
                user=user
            ).delete()

            DynamicAnswer.objects.filter(
                user=user
            ).delete()

            profile.delete()

            user.delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"{total_patients} pacientes apagados com sucesso."
            )
        )