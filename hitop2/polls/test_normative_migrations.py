from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class NormativeVersionDataMigrationTests(TransactionTestCase):
    migrate_from = ("polls", "0023_questionnairesubmission_normative_fields")
    migrate_to = ("polls", "0024_normative_dataset_versions")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps

        Spectra = old_apps.get_model("polls", "Spectra")
        Subfactor = old_apps.get_model("polls", "Subfactor")
        Scale = old_apps.get_model("polls", "Scale")
        Question = old_apps.get_model("polls", "Question")
        NormativeParticipant = old_apps.get_model("polls", "NormativeParticipant")
        NormativeAnswer = old_apps.get_model("polls", "NormativeAnswer")
        NormativeScaleScore = old_apps.get_model("polls", "NormativeScaleScore")
        NormativeSpectrumScore = old_apps.get_model(
            "polls", "NormativeSpectrumScore"
        )
        User = old_apps.get_model("auth", "User")
        QuestionnaireSubmission = old_apps.get_model(
            "polls", "QuestionnaireSubmission"
        )

        spectrum = Spectra.objects.create(name="Migrated spectrum")
        subfactor = Subfactor.objects.create(
            name="Migrated subfactor",
            spectra=spectrum,
        )
        scale = Scale.objects.create(name="Migrated scale", subfactor=subfactor)
        question = Question.objects.create(
            scale=scale,
            item_code="migration-version-1",
            question_text="Migration preservation test",
        )
        participant = NormativeParticipant.objects.create(age=40, sex="Feminino")
        answer = NormativeAnswer.objects.create(
            participant=participant,
            question=question,
            answer="3",
        )
        scale_score = NormativeScaleScore.objects.create(
            participant=participant,
            scale=scale,
            raw_score=3,
        )
        spectrum_score = NormativeSpectrumScore.objects.create(
            participant=participant,
            spectrum=spectrum,
            raw_score=3,
        )
        user = User.objects.create(username="migrated-report-patient")
        submission = QuestionnaireSubmission.objects.create(
            user=user,
            completed=True,
        )
        self.record_ids = {
            "participant": participant.pk,
            "answer": answer.pk,
            "scale_score": scale_score.pk,
            "spectrum_score": spectrum_score.pk,
            "submission": submission.pk,
        }

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.apps = executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_existing_normative_data_is_preserved_in_active_v1(self):
        NormativeDatasetVersion = self.apps.get_model(
            "polls", "NormativeDatasetVersion"
        )
        NormativeDatasetMembership = self.apps.get_model(
            "polls", "NormativeDatasetMembership"
        )
        NormativeParticipant = self.apps.get_model("polls", "NormativeParticipant")
        NormativeAnswer = self.apps.get_model("polls", "NormativeAnswer")
        NormativeScaleScore = self.apps.get_model("polls", "NormativeScaleScore")
        NormativeSpectrumScore = self.apps.get_model(
            "polls", "NormativeSpectrumScore"
        )
        QuestionnaireSubmission = self.apps.get_model(
            "polls", "QuestionnaireSubmission"
        )

        version = NormativeDatasetVersion.objects.get(name="v1")

        self.assertEqual(version.status, "active")
        self.assertIsNotNone(version.prepared_at)
        self.assertIsNotNone(version.activated_at)
        self.assertTrue(
            NormativeParticipant.objects.filter(
                pk=self.record_ids["participant"]
            ).exists()
        )
        self.assertTrue(
            NormativeAnswer.objects.filter(pk=self.record_ids["answer"]).exists()
        )
        self.assertTrue(
            NormativeDatasetMembership.objects.filter(
                version=version,
                participant_id=self.record_ids["participant"],
            ).exists()
        )
        self.assertEqual(
            NormativeScaleScore.objects.get(
                pk=self.record_ids["scale_score"]
            ).version_id,
            version.pk,
        )
        self.assertEqual(
            NormativeSpectrumScore.objects.get(
                pk=self.record_ids["spectrum_score"]
            ).version_id,
            version.pk,
        )
        self.assertEqual(
            QuestionnaireSubmission.objects.get(
                pk=self.record_ids["submission"]
            ).report_normative_version_id,
            version.pk,
        )
