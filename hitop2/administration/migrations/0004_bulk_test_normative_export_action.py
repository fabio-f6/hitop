from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("administration", "0003_audit_test_environment_cleanup_actions"),
    ]

    operations = [
        migrations.AlterField(
            model_name="administrativeauditlog",
            name="action",
            field=models.CharField(
                choices=[
                    ("professional.approved", "Profissional aprovado"),
                    ("professional.access_revoked", "Acesso de profissional retirado"),
                    ("normative_version.created", "Versão normativa criada"),
                    ("normative_version.prepared", "Versão normativa preparada"),
                    ("normative_version.activated", "Versão normativa ativada"),
                    (
                        "normative_test.synthetic_batch_created",
                        "Batch normativo sintético criado",
                    ),
                    ("normative_test.cleared", "Ambiente normativo de teste limpo"),
                    (
                        "normative_test.submission_exported",
                        "Submissão exportada para a base normativa de teste",
                    ),
                    (
                        "normative_test.submissions_bulk_exported",
                        "Submissões reexportadas para a base normativa de teste",
                    ),
                    (
                        "professional_test.cleared",
                        "Ambiente Profissional de Teste limpo",
                    ),
                ],
                db_index=True,
                max_length=64,
                verbose_name="ação",
            ),
        ),
    ]
