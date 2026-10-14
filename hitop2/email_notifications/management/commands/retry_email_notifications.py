from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from email_notifications.models import EmailNotification
from email_notifications.services import deliver_notification_safely


class Command(BaseCommand):
    help = "Tenta novamente notificações pendentes/falhadas e envios interrompidos."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        stale_before = timezone.now() - timedelta(minutes=15)
        ids = list(
            EmailNotification.objects.filter(
                status__in=[EmailNotification.Status.PENDING, EmailNotification.Status.FAILED]
            ).values_list("id", flat=True)[: options["limit"]]
        )
        remaining = options["limit"] - len(ids)
        if remaining:
            ids.extend(
                EmailNotification.objects.filter(
                    status=EmailNotification.Status.SENDING,
                    last_attempt_at__lt=stale_before,
                ).values_list("id", flat=True)[:remaining]
            )
        for notification_id in ids:
            deliver_notification_safely(notification_id)
        self.stdout.write(self.style.SUCCESS(f"Processadas {len(ids)} notificação(ões)."))
