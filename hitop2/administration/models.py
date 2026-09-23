from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


MASTER_RESET_ACTION = "system.master_reset"
SYSTEM_OBJECT_TYPE = "system"


class AdministrativeAuditLog(models.Model):
    class Action(models.TextChoices):
        PROFESSIONAL_APPROVED = (
            "professional.approved",
            "Profissional aprovado",
        )
        PROFESSIONAL_ACCESS_REVOKED = (
            "professional.access_revoked",
            "Acesso de profissional retirado",
        )
        NORMATIVE_VERSION_CREATED = (
            "normative_version.created",
            "Versão normativa criada",
        )
        NORMATIVE_VERSION_PREPARED = (
            "normative_version.prepared",
            "Versão normativa preparada",
        )
        NORMATIVE_VERSION_ACTIVATED = (
            "normative_version.activated",
            "Versão normativa ativada",
        )

    class ObjectType(models.TextChoices):
        PROFESSIONAL = "professional", "Profissional"
        NORMATIVE_VERSION = "normative_version", "Versão normativa"

    class Result(models.TextChoices):
        SUCCESS = "success", "Concluída"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="administrative_audit_logs",
        verbose_name="administrador",
    )
    action = models.CharField(
        max_length=64,
        choices=Action.choices,
        db_index=True,
        verbose_name="ação",
    )
    object_type = models.CharField(
        max_length=64,
        choices=ObjectType.choices,
        db_index=True,
        verbose_name="tipo de objeto",
    )
    object_id = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name="identificador do objeto",
    )
    object_label = models.CharField(
        max_length=255,
        verbose_name="objeto afetado",
    )
    result = models.CharField(
        max_length=20,
        choices=Result.choices,
        default=Result.SUCCESS,
        db_index=True,
        verbose_name="resultado",
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="contexto",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="data e hora",
    )

    class Meta:
        ordering = ("-created_at", "-id")
        verbose_name = "registo de auditoria administrativa"
        verbose_name_plural = "registos de auditoria administrativa"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(
                "Os registos de auditoria administrativa são imutáveis."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Os registos de auditoria administrativa não podem ser eliminados."
        )

    def get_action_display(self):
        if self.action == MASTER_RESET_ACTION:
            return "Master Reset"
        return dict(self.Action.choices).get(self.action, self.action)

    def get_object_type_display(self):
        if self.object_type == SYSTEM_OBJECT_TYPE:
            return "Sistema"
        return dict(self.ObjectType.choices).get(self.object_type, self.object_type)

    def __str__(self):
        return f"{self.get_action_display()} — {self.object_label}"
