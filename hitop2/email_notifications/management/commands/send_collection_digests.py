from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from email_notifications.digests import queue_collection_digests


class Command(BaseCommand):
    help = "Prepara e envia um resumo diário por investigador para o dia civil indicado."

    def add_arguments(self, parser):
        parser.add_argument("--date", dest="digest_date", help="Dia a resumir (AAAA-MM-DD). Por omissão, ontem.")

    def handle(self, *args, **options):
        value = options["digest_date"]
        try:
            day = date.fromisoformat(value) if value else timezone.localdate() - timedelta(days=1)
        except ValueError as exception:
            raise CommandError("A data deve usar o formato AAAA-MM-DD.") from exception
        queued = queue_collection_digests(day)
        self.stdout.write(self.style.SUCCESS(
            f"Resumo de {day.isoformat()}: {len(queued)} notificação(ões) nova(s) preparada(s)."
        ))
