from django.core.management.base import BaseCommand
from polls.models import UserAnswer
from django.contrib.sessions.models import Session

class Command(BaseCommand):
	help = 'Reset completo: respostas + sessões'

	def handle(self, *args, **kwargs):
		answers_count = UserAnswer.objects.count()
		sessions_count = Session.objects.count()

		UserAnswer.objects.all().delete()
		Session.objects.all().delete()

		self.stdout.write(
			self.style.SUCCESS(
				f"{answers_count} respostas e {sessions_count} sessões apagadas com sucesso."
				)
			)