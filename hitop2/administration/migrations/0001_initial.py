# Generated for the first administration-owned persistent model.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AdministrativeAuditLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("professional.approved", "Profissional aprovado"),
                            (
                                "professional.access_revoked",
                                "Acesso de profissional retirado",
                            ),
                            (
                                "normative_version.created",
                                "Versão normativa criada",
                            ),
                            (
                                "normative_version.prepared",
                                "Versão normativa preparada",
                            ),
                            (
                                "normative_version.activated",
                                "Versão normativa ativada",
                            ),
                        ],
                        db_index=True,
                        max_length=64,
                        verbose_name="ação",
                    ),
                ),
                (
                    "object_type",
                    models.CharField(
                        choices=[
                            ("professional", "Profissional"),
                            ("normative_version", "Versão normativa"),
                        ],
                        db_index=True,
                        max_length=64,
                        verbose_name="tipo de objeto",
                    ),
                ),
                (
                    "object_id",
                    models.CharField(
                        db_index=True,
                        max_length=255,
                        verbose_name="identificador do objeto",
                    ),
                ),
                (
                    "object_label",
                    models.CharField(
                        max_length=255,
                        verbose_name="objeto afetado",
                    ),
                ),
                (
                    "result",
                    models.CharField(
                        choices=[("success", "Concluída")],
                        db_index=True,
                        default="success",
                        max_length=20,
                        verbose_name="resultado",
                    ),
                ),
                (
                    "metadata",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        verbose_name="contexto",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        db_index=True,
                        verbose_name="data e hora",
                    ),
                ),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="administrative_audit_logs",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="administrador",
                    ),
                ),
            ],
            options={
                "verbose_name": "registo de auditoria administrativa",
                "verbose_name_plural": "registos de auditoria administrativa",
                "ordering": ("-created_at", "-id"),
            },
        ),
    ]
