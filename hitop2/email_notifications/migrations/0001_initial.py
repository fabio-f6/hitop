from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def create_default_preferences(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Preferences = apps.get_model(
        "email_notifications", "EmailNotificationPreferences"
    )
    Preferences.objects.bulk_create(
        [Preferences(user_id=user_id) for user_id in User.objects.values_list("id", flat=True)],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    initial = True
    dependencies = [("auth", "0012_alter_user_first_name_max_length")]
    operations = [
        migrations.CreateModel(
            name="EmailNotificationPreferences",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email_notifications_enabled", models.BooleanField(default=True)),
                ("professional_registration", models.BooleanField(default=True)),
                ("questionnaire_completed", models.BooleanField(default=True)),
                ("collection_daily_summary", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="email_notification_preferences", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "preferências de notificações por e-mail", "verbose_name_plural": "preferências de notificações por e-mail"},
        ),
        migrations.CreateModel(
            name="EmailNotification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("notification_type", models.CharField(choices=[("professional_registration", "Novo registo profissional"), ("professional_approved", "Profissional aprovado"), ("professional_rejected", "Profissional rejeitado"), ("questionnaire_completed", "Questionário concluído"), ("collection_daily_summary", "Resumo diário de coletas")], db_index=True, max_length=40)),
                ("logical_key", models.CharField(max_length=255, unique=True)),
                ("recipient_email", models.EmailField(blank=True, max_length=254)),
                ("context", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("pending", "Pendente"), ("sending", "Em envio"), ("sent", "Aceite pelo SMTP"), ("failed", "Falhou"), ("cancelled", "Cancelada")], db_index=True, default="pending", max_length=12)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("last_error", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("recipient", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="email_notifications", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "notificação por e-mail", "verbose_name_plural": "notificações por e-mail", "ordering": ("created_at", "id")},
        ),
        migrations.RunPython(
            create_default_preferences,
            migrations.RunPython.noop,
        ),
    ]
