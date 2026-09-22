from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class TestEnvironmentSubmissionMigrationTests(TransactionTestCase):
    migrate_from = ("polls", "0025_questionnairesubmission_simulation_options")
    migrate_to = ("polls", "0026_questionnairesubmission_is_test_data")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps

        User = old_apps.get_model("auth", "User")
        QuestionnaireSubmission = old_apps.get_model(
            "polls", "QuestionnaireSubmission"
        )
        user = User.objects.create(username="existing-submission-patient")
        self.normal_id = QuestionnaireSubmission.objects.create(
            user=user,
            simulation_mode="normal",
        ).pk
        self.simulated_id = QuestionnaireSubmission.objects.create(
            user=user,
            simulation_mode="simulated",
        ).pk

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.apps = executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_existing_submissions_remain_classified_as_real(self):
        QuestionnaireSubmission = self.apps.get_model(
            "polls", "QuestionnaireSubmission"
        )

        normal = QuestionnaireSubmission.objects.get(pk=self.normal_id)
        simulated = QuestionnaireSubmission.objects.get(pk=self.simulated_id)

        self.assertFalse(normal.is_test_data)
        self.assertFalse(simulated.is_test_data)
        self.assertEqual(normal.simulation_mode, "normal")
        self.assertEqual(simulated.simulation_mode, "simulated")
