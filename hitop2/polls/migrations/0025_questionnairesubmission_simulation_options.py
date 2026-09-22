from django.db import migrations, models


def map_legacy_null_percentage(apps, schema_editor):
    QuestionnaireSubmission = apps.get_model("polls", "QuestionnaireSubmission")
    QuestionnaireSubmission.objects.filter(
        simulation_mode="simulated_nulls",
        simulation_missing_percentage=0,
    ).update(simulation_missing_percentage=10)


class Migration(migrations.Migration):

    dependencies = [
        ("polls", "0024_normative_dataset_versions"),
    ]

    operations = [
        migrations.AddField(
            model_name="questionnairesubmission",
            name="sociodemographic_simulation_mode",
            field=models.CharField(
                choices=[
                    ("normal", "Não simular"),
                    ("eligible", "Elegível para base normativa"),
                    ("ineligible_language", "Não elegível: Português-Europeu"),
                    ("ineligible_mental_health", "Não elegível: saúde mental"),
                    ("ineligible_both", "Não elegível: ambos"),
                    (
                        "pending_missing",
                        "Indeterminado / resposta normativa em falta",
                    ),
                ],
                default="normal",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="questionnairesubmission",
            name="simulation_attention_mode",
            field=models.CharField(
                choices=[
                    ("all_correct", "Todos corretos"),
                    ("one_failure", "Uma falha"),
                    ("multiple_failures", "Múltiplas falhas"),
                ],
                default="all_correct",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="questionnairesubmission",
            name="simulation_missing_percentage",
            field=models.PositiveSmallIntegerField(
                choices=[(0, "0%"), (10, "10%"), (25, "25%"), (30, "30%")],
                default=0,
            ),
        ),
        migrations.AddField(
            model_name="questionnairesubmission",
            name="simulation_response_profile",
            field=models.CharField(
                choices=[
                    ("random", "Aleatório"),
                    ("low", "Baixo"),
                    ("medium", "Médio"),
                    ("high", "Alto"),
                ],
                default="random",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="questionnairesubmission",
            name="simulation_seed",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.RunPython(map_legacy_null_percentage, migrations.RunPython.noop),
    ]
