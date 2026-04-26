from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from polls.utils.reset import reset_patient_data

class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('username', type=str)

    def handle(self, *args, **kwargs):
        username = kwargs['username']

        user = User.objects.get(username=username)
        reset_patient_data(user)

        self.stdout.write(
            self.style.SUCCESS(f"Reset feito para {username}")
        )