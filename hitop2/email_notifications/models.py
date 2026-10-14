from django.conf import settings
from django.db import models


class EmailNotificationPreferences(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_notification_preferences",
    )
    email_notifications_enabled = models.BooleanField(default=True)
    professional_registration = models.BooleanField(default=True)
    questionnaire_completed = models.BooleanField(default=True)
    collection_daily_summary = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "preferências de notificações por e-mail"
        verbose_name_plural = "preferências de notificações por e-mail"


class EmailNotification(models.Model):
    class Type(models.TextChoices):
        PROFESSIONAL_REGISTRATION = "professional_registration", "Novo registo profissional"
        PROFESSIONAL_APPROVED = "professional_approved", "Profissional aprovado"
        PROFESSIONAL_REJECTED = "professional_rejected", "Profissional rejeitado"
        QUESTIONNAIRE_COMPLETED = "questionnaire_completed", "Questionário concluído"
        COLLECTION_DAILY_SUMMARY = "collection_daily_summary", "Resumo diário de coletas"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        SENDING = "sending", "Em envio"
        SENT = "sent", "Aceite pelo SMTP"
        FAILED = "failed", "Falhou"
        CANCELLED = "cancelled", "Cancelada"

    notification_type = models.CharField(max_length=40, choices=Type.choices, db_index=True)
    logical_key = models.CharField(max_length=255, unique=True)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="email_notifications",
    )
    recipient_email = models.EmailField(blank=True)
    context = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("created_at", "id")
        verbose_name = "notificação por e-mail"
        verbose_name_plural = "notificações por e-mail"
