from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

from polls.models import (
    UserAnswer,
    QuestionnaireSubmission,
    SociodemographicAnswer
)

from website.models import UserProfile


class Command(BaseCommand):
    help = "Apaga completamente um paciente"

    def add_arguments(self, parser):
        parser.add_argument("username", type=str)

    def handle(self, *args, **kwargs):
        username = kwargs["username"]

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR("Utilizador não encontrado"))
            return

        # respostas HITOP
        UserAnswer.objects.filter(user=user).delete()
        QuestionnaireSubmission.objects.filter(user=user).delete()

        # sociodemográfico
        SociodemographicAnswer.objects.filter(user=user).delete()

        # profile (IMPORTANTE: vem do website)
        UserProfile.objects.filter(user=user).delete()

        # user final
        user.delete()

        self.stdout.write(self.style.SUCCESS(f"Paciente {username} apagado completamente"))