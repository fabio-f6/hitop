from django.db import migrations, models


def copy_pinned_version_snapshot(apps, schema_editor):
    Submission = apps.get_model("polls", "QuestionnaireSubmission")
    batch = []
    for submission in Submission.objects.exclude(
        report_normative_version__isnull=True,
    ).select_related("report_normative_version").iterator():
        version = submission.report_normative_version
        submission.report_normative_version_name = version.name
        submission.report_normative_version_environment = version.environment
        batch.append(submission)
        if len(batch) >= 500:
            Submission.objects.bulk_update(
                batch,
                [
                    "report_normative_version_name",
                    "report_normative_version_environment",
                ],
            )
            batch.clear()
    if batch:
        Submission.objects.bulk_update(
            batch,
            [
                "report_normative_version_name",
                "report_normative_version_environment",
            ],
        )


def clear_pinned_version_snapshot(apps, schema_editor):
    Submission = apps.get_model("polls", "QuestionnaireSubmission")
    Submission.objects.update(
        report_normative_version_name="",
        report_normative_version_environment="",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("polls", "0027_remove_normativedatasetversion_polls_one_active_normative_version_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="questionnairesubmission",
            name="report_normative_version_name",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="questionnairesubmission",
            name="report_normative_version_environment",
            field=models.CharField(
                blank=True,
                choices=[("production", "Produção"), ("test", "Teste")],
                default="",
                max_length=12,
            ),
        ),
        migrations.RunPython(
            copy_pinned_version_snapshot,
            clear_pinned_version_snapshot,
        ),
    ]
