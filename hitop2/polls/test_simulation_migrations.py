from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SimulationOptionsMigrationTests(TransactionTestCase):
    migrate_from = ("polls", "0024_normative_dataset_versions")
    migrate_to = ("polls", "0025_questionnairesubmission_simulation_options")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps

        User = old_apps.get_model("auth", "User")
        QuestionnaireSubmission = old_apps.get_model(
            "polls", "QuestionnaireSubmission"
        )
        user = User.objects.create(username="simulation-migration-patient")
        self.normal_id = QuestionnaireSubmission.objects.create(
            user=user,
            simulation_mode="normal",
        ).pk
        self.simulated_id = QuestionnaireSubmission.objects.create(
            user=user,
            simulation_mode="simulated",
        ).pk
        self.nulls_id = QuestionnaireSubmission.objects.create(
            user=user,
            simulation_mode="simulated_nulls",
        ).pk

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.apps = executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_existing_modes_and_safe_defaults_are_preserved(self):
        QuestionnaireSubmission = self.apps.get_model(
            "polls", "QuestionnaireSubmission"
        )
        normal = QuestionnaireSubmission.objects.get(pk=self.normal_id)
        simulated = QuestionnaireSubmission.objects.get(pk=self.simulated_id)
        nulls = QuestionnaireSubmission.objects.get(pk=self.nulls_id)

        self.assertEqual(normal.simulation_mode, "normal")
        self.assertEqual(normal.sociodemographic_simulation_mode, "normal")
        self.assertEqual(normal.simulation_missing_percentage, 0)
        self.assertEqual(simulated.simulation_mode, "simulated")
        self.assertEqual(simulated.simulation_missing_percentage, 0)
        self.assertEqual(nulls.simulation_mode, "simulated_nulls")
        self.assertEqual(nulls.simulation_missing_percentage, 10)
