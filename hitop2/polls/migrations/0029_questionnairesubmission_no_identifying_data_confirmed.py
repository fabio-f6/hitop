from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("polls", "0028_questionnairesubmission_normative_version_snapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="questionnairesubmission",
            name="no_identifying_data_confirmed",
            field=models.BooleanField(
                default=False,
                verbose_name="ausência de dados identificativos confirmada",
            ),
        ),
    ]
