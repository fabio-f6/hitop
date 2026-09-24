from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch

from .models import (
    NormativeDatasetMembership, NormativeDatasetVersion, NormativeParticipant,
    NormativeAnswer, NormativeScaleScore, NormativeSpectrumScore, Question,
    QuestionnaireSubmission, Scale, Spectra, Subfactor,
)
from .normative_test import clear_normative_test_environment
from .normative_versions import (
    NormativeVersionError, activate_normative_version, create_normative_version,
    get_active_normative_version, get_normative_version_details,
    prepare_normative_version,
)
from .simulation import derive_simulation_seed


class NormativeEnvironmentTests(TestCase):
    def test_existing_defaults_are_production_and_real(self):
        self.assertEqual(NormativeParticipant.objects.create().source, "real")
        self.assertEqual(NormativeDatasetVersion.objects.create(name="v1").environment, "production")

    def test_synthetic_membership_is_rejected_in_production(self):
        participant = NormativeParticipant.objects.create(source="synthetic")
        version = NormativeDatasetVersion.objects.create(name="v1")
        with self.assertRaises(ValidationError):
            NormativeDatasetMembership.objects.create(version=version, participant=participant)

    def test_test_snapshot_combines_real_baseline_and_synthetic(self):
        real = NormativeParticipant.objects.create()
        synthetic = NormativeParticipant.objects.create(source="synthetic")
        baseline = create_normative_version("v1")
        version = create_normative_version(
            "whatever", environment="test", baseline_version=baseline,
        )
        self.assertSetEqual(set(version.participants.all()), {real, synthetic})
        self.assertEqual(baseline.participant_count, 1)
        self.assertEqual(get_normative_version_details(version.pk), version)

    def test_active_versions_are_independent(self):
        production = create_normative_version("v1")
        prepare_normative_version(production)
        activate_normative_version(production)
        test = create_normative_version("test-v1", environment="test", baseline_version=production)
        prepare_normative_version(test)
        activate_normative_version(test)
        self.assertEqual(get_active_normative_version(), production)
        self.assertEqual(get_active_normative_version("test"), test)

    def test_prepare_defends_production_from_bulk_inserted_synthetic(self):
        participant = NormativeParticipant.objects.create(source="synthetic")
        version = NormativeDatasetVersion.objects.create(name="v1")
        NormativeDatasetMembership.objects.bulk_create([
            NormativeDatasetMembership(version=version, participant=participant)
        ])
        with self.assertRaises(NormativeVersionError):
            prepare_normative_version(version)

    def test_cleanup_preserves_production_and_real_data(self):
        real = NormativeParticipant.objects.create()
        synthetic = NormativeParticipant.objects.create(source="synthetic")
        production = create_normative_version("v1")
        later_production = create_normative_version("v2")
        test = create_normative_version("test-v1", environment="test", baseline_version=production)
        now = timezone.now()
        NormativeDatasetVersion.objects.filter(pk=test.pk).update(
            status=NormativeDatasetVersion.Status.ACTIVE,
            prepared_at=now,
            activated_at=now,
        )
        test.refresh_from_db()
        spectrum = Spectra.objects.create(name="Cleanup spectrum")
        subfactor = Subfactor.objects.create(name="Cleanup subfactor", spectra=spectrum)
        scale = Scale.objects.create(name="Cleanup scale", subfactor=subfactor)
        question = Question.objects.create(
            scale=scale, item_code="CLEANUP-1", question_text="Cleanup",
        )
        NormativeAnswer.objects.create(
            participant=real, question=question, answer="2",
        )
        NormativeScaleScore.objects.bulk_create([NormativeScaleScore(
            version=production, participant=real, scale=scale, raw_score=2,
        )])
        NormativeSpectrumScore.objects.bulk_create([NormativeSpectrumScore(
            version=production, participant=real, spectrum=spectrum, raw_score=2,
        )])
        NormativeAnswer.objects.create(
            participant=synthetic, question=question, answer="1",
        )
        NormativeScaleScore.objects.bulk_create([NormativeScaleScore(
            version=test, participant=synthetic, scale=scale, raw_score=1,
        )])
        NormativeSpectrumScore.objects.bulk_create([NormativeSpectrumScore(
            version=test, participant=synthetic, spectrum=spectrum, raw_score=1,
        )])
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user(username="cleanup-test-submission")
        submission = QuestionnaireSubmission.objects.create(
            user=user,
            is_test_data=True,
            simulation_mode="simulated",
            report_normative_version=test,
        )

        # The previous delete path was blocked by the submission pin and both
        # score FKs, even after bypassing the lifecycle status guard.
        with self.assertRaises(ProtectedError):
            NormativeDatasetVersion.objects.filter(pk=test.pk).delete()

        result = clear_normative_test_environment()
        self.assertEqual((result.versions, result.participants), (1, 1))
        self.assertTrue(NormativeParticipant.objects.filter(pk=real.pk).exists())
        self.assertFalse(NormativeParticipant.objects.filter(pk=synthetic.pk).exists())
        self.assertTrue(NormativeDatasetVersion.objects.filter(pk=production.pk).exists())
        self.assertTrue(NormativeDatasetVersion.objects.filter(pk=later_production.pk).exists())
        self.assertTrue(NormativeDatasetMembership.objects.filter(
            version=production, participant=real,
        ).exists())
        self.assertTrue(NormativeAnswer.objects.filter(participant=real).exists())
        self.assertTrue(NormativeScaleScore.objects.filter(version=production).exists())
        self.assertTrue(NormativeSpectrumScore.objects.filter(version=production).exists())
        self.assertFalse(NormativeDatasetVersion.objects.filter(pk=test.pk).exists())
        self.assertFalse(NormativeDatasetMembership.objects.filter(version=test).exists())
        self.assertFalse(NormativeScaleScore.objects.filter(version=test).exists())
        self.assertFalse(NormativeSpectrumScore.objects.filter(version=test).exists())
        self.assertFalse(NormativeAnswer.objects.filter(participant=synthetic).exists())
        submission.refresh_from_db()
        self.assertIsNone(submission.report_normative_version)

    def test_cleanup_abort_preserves_everything_when_real_submission_pins_test(self):
        real = NormativeParticipant.objects.create()
        synthetic = NormativeParticipant.objects.create(source="synthetic")
        production = create_normative_version("real-pin-production")
        test = create_normative_version(
            "real-pin-test", environment="test", baseline_version=production,
        )
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user(username="cleanup-real-submission")
        submission = QuestionnaireSubmission.objects.create(
            user=user, report_normative_version=production,
        )
        # Simulate corrupt legacy data without running the normal save guard.
        QuestionnaireSubmission.objects.filter(pk=submission.pk).update(
            report_normative_version=test,
        )

        with self.assertRaisesRegex(RuntimeError, "submissão clínica real"):
            clear_normative_test_environment()

        submission.refresh_from_db()
        self.assertEqual(submission.report_normative_version, test)
        self.assertTrue(NormativeDatasetVersion.objects.filter(pk=test.pk).exists())
        self.assertTrue(NormativeParticipant.objects.filter(pk=synthetic.pk).exists())
        self.assertTrue(NormativeParticipant.objects.filter(pk=real.pk).exists())

    def test_cleanup_failure_rolls_back_pins_scores_memberships_versions_and_participants(self):
        synthetic = NormativeParticipant.objects.create(source="synthetic")
        production = create_normative_version("rollback-production")
        test = create_normative_version(
            "rollback-test", environment="test", baseline_version=production,
        )
        spectrum = Spectra.objects.create(name="Rollback spectrum")
        subfactor = Subfactor.objects.create(name="Rollback subfactor", spectra=spectrum)
        scale = Scale.objects.create(name="Rollback scale", subfactor=subfactor)
        question = Question.objects.create(
            scale=scale, item_code="ROLLBACK-1", question_text="Rollback",
        )
        NormativeAnswer.objects.create(
            participant=synthetic, question=question, answer="2",
        )
        NormativeScaleScore.objects.bulk_create([NormativeScaleScore(
            version=test, participant=synthetic, scale=scale, raw_score=2,
        )])
        NormativeSpectrumScore.objects.bulk_create([NormativeSpectrumScore(
            version=test, participant=synthetic, spectrum=spectrum, raw_score=2,
        )])
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user(username="cleanup-rollback")
        submission = QuestionnaireSubmission.objects.create(
            user=user,
            is_test_data=True,
            simulation_mode="simulated",
            report_normative_version=test,
        )
        before = (
            NormativeDatasetVersion.objects.count(),
            NormativeDatasetMembership.objects.count(),
            NormativeParticipant.objects.count(),
            NormativeAnswer.objects.count(),
            NormativeScaleScore.objects.count(),
            NormativeSpectrumScore.objects.count(),
            QuestionnaireSubmission.objects.count(),
        )

        with patch(
            "polls.normative_test._validate_cleanup_result",
            side_effect=RuntimeError("forced cleanup validation failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "forced cleanup"):
                clear_normative_test_environment()

        self.assertEqual((
            NormativeDatasetVersion.objects.count(),
            NormativeDatasetMembership.objects.count(),
            NormativeParticipant.objects.count(),
            NormativeAnswer.objects.count(),
            NormativeScaleScore.objects.count(),
            NormativeSpectrumScore.objects.count(),
            QuestionnaireSubmission.objects.count(),
        ), before)
        submission.refresh_from_db()
        self.assertEqual(submission.report_normative_version, test)
        self.assertTrue(NormativeDatasetVersion.objects.filter(pk=test.pk).exists())
        self.assertTrue(NormativeDatasetMembership.objects.filter(
            version=test, participant=synthetic,
        ).exists())
        self.assertTrue(NormativeParticipant.objects.filter(pk=synthetic.pk).exists())
        self.assertTrue(NormativeAnswer.objects.filter(participant=synthetic).exists())
        self.assertTrue(NormativeScaleScore.objects.filter(version=test).exists())
        self.assertTrue(NormativeSpectrumScore.objects.filter(version=test).exists())

    def test_derived_seeds_are_reproducible_and_distinct(self):
        first = [derive_simulation_seed(12345, i) for i in range(1, 51)]
        second = [derive_simulation_seed(12345, i) for i in range(1, 51)]
        self.assertEqual(first, second)
        self.assertEqual(len(set(first)), 50)

    def test_real_submission_cannot_pin_test_version(self):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user(username="real")
        baseline = create_normative_version("v1")
        test = create_normative_version("test-v1", environment="test", baseline_version=baseline)
        with self.assertRaises(ValidationError):
            QuestionnaireSubmission.objects.create(
                user=user, report_normative_version=test,
            )
