from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("polls", "0025_questionnairesubmission_simulation_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="questionnairesubmission",
            name="is_test_data",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
