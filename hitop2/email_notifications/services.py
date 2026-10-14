import logging
from datetime import timedelta
from urllib.parse import urljoin

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from website.decorators import can_use_general_collections
from website.models import UserProfile

from .models import EmailNotification, EmailNotificationPreferences


logger = logging.getLogger(__name__)

OPTIONAL_TYPES = {
    EmailNotification.Type.PROFESSIONAL_REGISTRATION: "professional_registration",
    EmailNotification.Type.QUESTIONNAIRE_COMPLETED: "questionnaire_completed",
    EmailNotification.Type.COLLECTION_DAILY_SUMMARY: "collection_daily_summary",
}

SUBJECTS = {
    EmailNotification.Type.PROFESSIONAL_REGISTRATION: "HiTOP Platform | Novo registo profissional",
    EmailNotification.Type.PROFESSIONAL_APPROVED: "HiTOP Platform | Conta aprovada",
    EmailNotification.Type.PROFESSIONAL_REJECTED: "HiTOP Platform | Pedido de registo não aprovado",
    EmailNotification.Type.QUESTIONNAIRE_COMPLETED: "HiTOP Platform | Questionário clínico concluído",
    EmailNotification.Type.COLLECTION_DAILY_SUMMARY: "HiTOP Platform | Resumo diário das suas Coletas Gerais",
}


def absolute_url(view_name, *args):
    base = settings.PLATFORM_BASE_URL.rstrip("/") + "/"
    return urljoin(base, reverse(view_name, args=args).lstrip("/"))


def preferences_for(user):
    preferences, _ = EmailNotificationPreferences.objects.get_or_create(user=user)
    return preferences


def _eligible_for_optional(notification):
    user = notification.recipient
    if user is None or not user.is_active:
        return False
    try:
        profile = user.userprofile
    except UserProfile.DoesNotExist:
        return False
    field = OPTIONAL_TYPES.get(notification.notification_type)
    preferences = preferences_for(user)
    if not preferences.email_notifications_enabled or not getattr(preferences, field):
        return False
    if notification.notification_type == EmailNotification.Type.PROFESSIONAL_REGISTRATION:
        return profile.user_type == "admin"
    if notification.notification_type == EmailNotification.Type.QUESTIONNAIRE_COMPLETED:
        return profile.user_type == "professional" and profile.is_verified
    if notification.notification_type == EmailNotification.Type.COLLECTION_DAILY_SUMMARY:
        return can_use_general_collections(user)
    return True


def queue_notification(*, notification_type, logical_key, recipient, context=None):
    notification, created = EmailNotification.objects.get_or_create(
        logical_key=logical_key,
        defaults={
            "notification_type": notification_type,
            "recipient": recipient,
            "recipient_email": recipient.email.strip(),
            "context": context or {},
        },
    )
    if created:
        transaction.on_commit(lambda notification_id=notification.pk: deliver_notification_safely(notification_id))
    return notification, created


def deliver_notification(notification_id):
    with transaction.atomic():
        # Lock only the outbox row. PostgreSQL cannot apply FOR UPDATE to the
        # nullable side of the LEFT JOIN introduced by select_related here.
        notification = EmailNotification.objects.select_for_update().get(
            pk=notification_id
        )
        if notification.status in (EmailNotification.Status.SENT, EmailNotification.Status.CANCELLED):
            return notification
        if (
            notification.status == EmailNotification.Status.SENDING
            and notification.last_attempt_at
            and notification.last_attempt_at > timezone.now() - timedelta(minutes=15)
        ):
            return notification
        if notification.notification_type in OPTIONAL_TYPES and not _eligible_for_optional(notification):
            notification.status = EmailNotification.Status.CANCELLED
            notification.last_error = "Destinatário inelegível ou preferência desativada."
            notification.save(update_fields=["status", "last_error"])
            return notification
        if notification.recipient is None:
            notification.status = EmailNotification.Status.CANCELLED
            notification.last_error = "A conta destinatária já não existe."
            notification.save(update_fields=["status", "last_error"])
            return notification
        current_email = notification.recipient.email.strip()
        if current_email != notification.recipient_email:
            # Account data may have been corrected after the message was
            # queued (notably a missing/invalid address). Retry the current
            # address rather than preserving an unusable snapshot.
            notification.recipient_email = current_email
            notification.save(update_fields=["recipient_email"])
        if not notification.recipient_email:
            notification.status = EmailNotification.Status.FAILED
            notification.last_error = "O destinatário não possui endereço de e-mail."
            notification.save(update_fields=["status", "last_error"])
            return notification
        try:
            validate_email(notification.recipient_email)
        except ValidationError:
            notification.status = EmailNotification.Status.FAILED
            notification.last_error = "O endereço de e-mail do destinatário é inválido."
            notification.save(update_fields=["status", "last_error"])
            return notification
        notification.status = EmailNotification.Status.SENDING
        notification.attempts += 1
        notification.last_attempt_at = timezone.now()
        notification.last_error = ""
        notification.save(update_fields=["status", "attempts", "last_attempt_at", "last_error"])

    template = f"email_notifications/email/{notification.notification_type}"
    render_context = {
        **notification.context,
        "platform_name": "HiTOP Platform",
        "preferences_url": absolute_url("website:notification_preferences"),
    }
    text_body = render_to_string(f"{template}.txt", render_context)
    html_body = render_to_string(f"{template}.html", render_context)
    message = EmailMultiAlternatives(
        subject=SUBJECTS[notification.notification_type],
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[notification.recipient_email],
    )
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=False)

    EmailNotification.objects.filter(pk=notification.pk).update(
        status=EmailNotification.Status.SENT,
        sent_at=timezone.now(),
        last_error="",
    )
    notification.refresh_from_db()
    return notification


def deliver_notification_safely(notification_id):
    try:
        return deliver_notification(notification_id)
    except Exception as exception:
        # Do not retain message contents or SMTP credentials in diagnostic data.
        error = f"{type(exception).__name__}: envio SMTP não concluído"[:500]
        EmailNotification.objects.filter(pk=notification_id).update(
            status=EmailNotification.Status.FAILED,
            last_error=error,
        )
        logger.exception("Falha ao enviar a notificação por e-mail %s", notification_id)
        return None


def notify_professional_registration(professional):
    admins = UserProfile.objects.filter(
        user_type="admin", user__is_active=True
    ).select_related("user")
    for admin in admins:
        queue_notification(
            notification_type=EmailNotification.Type.PROFESSIONAL_REGISTRATION,
            logical_key=f"professional-registration:{professional.pk}:admin:{admin.user_id}",
            recipient=admin.user,
            context={
                "professional_name": professional.user.get_full_name() or professional.user.username,
                "action_url": absolute_url("administration:professional_detail", professional.pk),
            },
        )


def notify_professional_approved(professional):
    return queue_notification(
        notification_type=EmailNotification.Type.PROFESSIONAL_APPROVED,
        logical_key=f"professional-approved:{professional.pk}",
        recipient=professional.user,
        context={"login_url": absolute_url("website:home")},
    )


def notify_professional_rejected(professional):
    return queue_notification(
        notification_type=EmailNotification.Type.PROFESSIONAL_REJECTED,
        logical_key=f"professional-rejected:{professional.pk}",
        recipient=professional.user,
        context={"login_url": absolute_url("website:home")},
    )


def notify_questionnaire_completed(submission):
    if submission.collection_id or submission.is_test_data or submission.simulation_mode != "normal":
        return None
    try:
        professional = submission.user.userprofile.professional
    except (AttributeError, UserProfile.DoesNotExist):
        return None
    if professional is None:
        return None
    return queue_notification(
        notification_type=EmailNotification.Type.QUESTIONNAIRE_COMPLETED,
        logical_key=f"questionnaire-completed:{submission.pk}",
        recipient=professional,
        context={"action_url": absolute_url("website:patient_submissions", submission.user.userprofile.pk)},
    )
