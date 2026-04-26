from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

from polls.models import QuestionnaireSubmission, UserAnswer


class Command(BaseCommand):
    help = "Reseta todas as submissões HiTOP de um paciente"

    def add_arguments(self, parser):
        parser.add_argument('username', type=str)

    def handle(self, *args, **kwargs):
        username = kwargs['username']

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR("Utilizador não encontrado"))
            return

        submissions = QuestionnaireSubmission.objects.filter(
            user=user,
            questionnaire_type="hitop"
        )

        answers_deleted, _ = UserAnswer.objects.filter(
            submission__in=submissions
        ).delete()

        submissions_deleted, _ = submissions.delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Reset concluído para {username} | "
                f"Submissões apagadas: {submissions_deleted} | "
                f"Respostas apagadas: {answers_deleted}"
            )
        )