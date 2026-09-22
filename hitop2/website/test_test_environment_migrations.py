from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class TestEnvironmentPatientMigrationTests(TransactionTestCase):
    migrate_from = ("website", "0009_userprofile_archived_at")
    migrate_to = ("website", "0010_userprofile_test_environment_fields")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps

        User = old_apps.get_model("auth", "User")
        UserProfile = old_apps.get_model("website", "UserProfile")
        professional = User.objects.create(username="existing-professional")
        patient = User.objects.create(username="existing-patient")
        self.profile_id = UserProfile.objects.create(
            user=patient,
            user_type="patient",
            professional=professional,
            area_formacao="Psicologia",
            objetivo_uso="clinico",
            cedula_profissional="0000",
        ).pk

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.apps = executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_existing_patient_remains_real_and_has_no_test_owner(self):
        UserProfile = self.apps.get_model("website", "UserProfile")

        profile = UserProfile.objects.get(pk=self.profile_id)

        self.assertFalse(profile.is_test_data)
        self.assertIsNone(profile.test_environment_owner_id)
        self.assertIsNotNone(profile.professional_id)
