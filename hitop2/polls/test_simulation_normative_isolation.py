from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from .models import (
    NormativeAnswer,
    NormativeDatasetMembership,
    NormativeDatasetVersion,
    NormativeParticipant,
    NormativeScaleScore,
    NormativeSpectrumScore,
    Question,
    QuestionnaireSubmission,
    Scale,
    Spectra,
    Subfactor,
)
from .normative_export import (
    TestSubmissionExportBlocked,
    evaluate_normative_eligibility,
    export_submission_to_normative,
)
from .normative_versions import (
    activate_normative_version,
    create_normative_version,
    get_active_normative_version,
    get_unversioned_normative_participant_count,
    prepare_normative_version,
)
from .percentiles import calculate_percentile, calculate_spectrum_percentile
from .simulation import simulate_submission


class SimulationNormativeIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_sociodemographic", verbosity=0)

        cls.administrator = User.objects.create_user(
            username="normative-isolation-administrator"
        )
        cls.administrator.userprofile.user_type = "admin"
        cls.administrator.userprofile.save(update_fields=["user_type"])

        cls.patient = User.objects.create_user(
            username="normative-isolation-test-patient"
        )
        cls.patient.userprofile.user_type = "patient"
        cls.patient.userprofile.is_test_data = True
        cls.patient.userprofile.test_environment_owner = cls.administrator
        cls.patient.userprofile.save(update_fields=[
            "user_type",
            "is_test_data",
            "test_environment_owner",
        ])

        cls.spectrum = Spectra.objects.create(name="Isolation spectrum")
        subfactor = Subfactor.objects.create(
            name="Isolation subfactor",
            spectra=cls.spectrum,
        )
        cls.scale = Scale.objects.create(
            name="Isolation scale",
            subfactor=subfactor,
        )
        cls.question = Question.objects.create(
            scale=cls.scale,
            item_code="norm-isolation-1",
            question_text="Normative isolation question",
        )

        participant = NormativeParticipant.objects.create(age=41, sex="Feminino")
        NormativeAnswer.objects.create(
            participant=participant,
            question=cls.question,
            answer="2",
        )
        version = create_normative_version("normative-isolation-v1")
        prepare_normative_version(version)
        cls.version = activate_normative_version(version)

    def make_simulation(self, socio_mode):
        submission = QuestionnaireSubmission.objects.create(
            user=self.patient,
            is_test_data=True,
            simulation_mode="simulated",
            sociodemographic_simulation_mode=socio_mode,
            simulation_seed=2048,
        )
        submission.spectra.add(self.spectrum)
        result = simulate_submission(submission)
        submission.refresh_from_db()
        return submission, result

    def normative_snapshot(self):
        version = NormativeDatasetVersion.objects.get(pk=self.version.pk)
        return {
            "participants": list(
                NormativeParticipant.objects.order_by("pk").values_list(
                    "pk", "age", "sex"
                )
            ),
            "answers": list(
                NormativeAnswer.objects.order_by("pk").values_list(
                    "pk", "participant_id", "question_id", "answer"
                )
            ),
            "memberships": list(
                NormativeDatasetMembership.objects.order_by("pk").values_list(
                    "pk", "version_id", "participant_id"
                )
            ),
            "versions": list(
                NormativeDatasetVersion.objects.order_by("pk").values_list(
                    "pk", "name", "status", "prepared_at", "activated_at"
                )
            ),
            "scale_scores": list(
                NormativeScaleScore.objects.order_by("pk").values_list(
                    "pk", "version_id", "participant_id", "scale_id", "raw_score"
                )
            ),
            "spectrum_scores": list(
                NormativeSpectrumScore.objects.order_by("pk").values_list(
                    "pk",
                    "version_id",
                    "participant_id",
                    "spectrum_id",
                    "raw_score",
                )
            ),
            "participant_count": version.participant_count,
            "unversioned_count": get_unversioned_normative_participant_count(),
            "scale_percentile": calculate_percentile(self.scale, 2),
            "spectrum_percentile": calculate_spectrum_percentile(
                self.spectrum,
                2,
            ),
        }

    def test_eligible_simulation_changes_no_real_normative_data(self):
        before = self.normative_snapshot()

        submission, result = self.make_simulation("eligible")

        self.assertIs(evaluate_normative_eligibility(submission)["eligible"], True)
        self.assertEqual(
            result,
            {
                "eligible": True,
                "reason": "os dois critérios foram cumpridos",
                "exported": False,
                "test_data": True,
            },
        )
        self.assertEqual(submission.normative_status, "pending")
        self.assertIsNone(submission.normative_exported_at)
        self.assertEqual(self.normative_snapshot(), before)
        self.assertEqual(get_active_normative_version().pk, self.version.pk)

    def test_low_level_export_refuses_eligible_simulation_atomically(self):
        submission, _result = self.make_simulation("eligible")
        before = self.normative_snapshot()

        with self.assertRaises(TestSubmissionExportBlocked):
            export_submission_to_normative(submission)

        submission.refresh_from_db()
        self.assertEqual(submission.normative_status, "pending")
        self.assertIsNone(submission.normative_exported_at)
        self.assertEqual(self.normative_snapshot(), before)

    def test_ineligible_and_pending_simulations_do_not_change_normative_data(self):
        before = self.normative_snapshot()

        ineligible, ineligible_result = self.make_simulation(
            "ineligible_language"
        )
        pending, pending_result = self.make_simulation("pending_missing")

        self.assertIs(
            evaluate_normative_eligibility(ineligible)["eligible"],
            False,
        )
        self.assertIsNone(evaluate_normative_eligibility(pending)["eligible"])
        self.assertIs(ineligible_result["eligible"], False)
        self.assertIsNone(pending_result["eligible"])
        self.assertFalse(ineligible_result["exported"])
        self.assertFalse(pending_result["exported"])
        self.assertEqual(ineligible.normative_status, "pending")
        self.assertEqual(pending.normative_status, "pending")
        self.assertEqual(self.normative_snapshot(), before)
