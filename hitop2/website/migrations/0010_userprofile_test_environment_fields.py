import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("website", "0009_userprofile_archived_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="is_test_data",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="test_environment_owner",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="test_environment_patients",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name="userprofile",
            constraint=models.CheckConstraint(
                condition=(
                    Q(is_test_data=False, test_environment_owner__isnull=True)
                    | Q(
                        is_test_data=True,
                        user_type="patient",
                        professional__isnull=True,
                        test_environment_owner__isnull=False,
                    )
                ),
                name="website_valid_test_patient_ownership",
            ),
        ),
    ]
