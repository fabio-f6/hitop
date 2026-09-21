from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("polls", "0021_dynamicquestion_group_intro_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="dynamicquestion",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
    ]
