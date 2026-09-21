import csv
import tempfile

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import (
    DynamicAnswer,
    NormativeAnswer,
    NormativeDatasetMembership,
    NormativeDatasetVersion,
    NormativeParticipant,
    NormativeScaleScore,
    NormativeSpectrumScore,
    QuestionnaireSubmission,
    Question,
    Scale,
    Spectra,
    Subfactor,
    UserAnswer,
)
from .normative_versions import (
    NormativeVersionError,
    activate_normative_version,
    create_normative_version,
    get_active_normative_version,
    get_normative_participant_counts,
    get_or_assign_report_normative_version,
    get_unversioned_normative_participant_count,
    prepare_normative_version,
)
from .percentiles import calculate_percentile, calculate_spectrum_percentile


class NormativeDatasetVersionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.spectrum = Spectra.objects.create(name="Normative spectrum")
        subfactor = Subfactor.objects.create(
            name="Normative subfactor",
            spectra=cls.spectrum,
        )
        cls.scale = Scale.objects.create(
            name="Normative scale",
            subfactor=subfactor,
        )
        cls.question = Question.objects.create(
            scale=cls.scale,
            item_code="norm-version-1",
            question_text="Normative version test",
        )

    def create_participant(self, answer="1"):
        participant = NormativeParticipant.objects.create(age=30, sex="Feminino")
        NormativeAnswer.objects.create(
            participant=participant,
            question=self.question,
            answer=answer,
        )
        return participant

    def create_prepared_version(self, name):
        version = create_normative_version(name)
        result = prepare_normative_version(version)
        version.refresh_from_db()
        return version, result

    def test_create_version_makes_unprepared_draft_with_current_snapshot(self):
        participants = [self.create_participant(), self.create_participant("2")]

        version = create_normative_version("v-test-1")

        self.assertEqual(version.status, NormativeDatasetVersion.Status.DRAFT)
        self.assertIsNone(version.prepared_at)
        self.assertIsNone(version.activated_at)
        self.assertCountEqual(version.participants.all(), participants)
        self.assertEqual(version.participant_count, 2)

    def test_later_participant_does_not_change_existing_snapshot(self):
        first = self.create_participant()
        version = create_normative_version("v-test-1")

        later = self.create_participant("4")

        self.assertCountEqual(version.participants.all(), [first])
        self.assertFalse(version.participants.filter(pk=later.pk).exists())

    def test_preparation_only_scores_snapshot_participants(self):
        included = self.create_participant("2")
        version = create_normative_version("v-test-1")
        excluded = self.create_participant("4")

        result = prepare_normative_version(version)

        self.assertEqual(result.participant_count, 1)
        self.assertEqual(result.scale_score_count, 1)
        self.assertEqual(result.spectrum_score_count, 1)
        self.assertTrue(
            NormativeScaleScore.objects.filter(
                version=version,
                participant=included,
            ).exists()
        )
        self.assertFalse(
            NormativeScaleScore.objects.filter(
                version=version,
                participant=excluded,
            ).exists()
        )

    def test_activation_requires_preparation(self):
        version = create_normative_version("v-test-1")

        with self.assertRaises(NormativeVersionError):
            activate_normative_version(version)

    def test_activation_sets_active_version_and_timestamp(self):
        self.create_participant()
        version, _result = self.create_prepared_version("v-test-1")

        activated = activate_normative_version(version)

        self.assertEqual(activated.status, NormativeDatasetVersion.Status.ACTIVE)
        self.assertIsNotNone(activated.activated_at)
        self.assertEqual(get_active_normative_version(), activated)

    def test_activating_v2_retires_v1_and_keeps_only_one_active(self):
        self.create_participant()
        v1, _result = self.create_prepared_version("v-test-1")
        activate_normative_version(v1)
        v2, _result = self.create_prepared_version("v-test-2")

        activate_normative_version(v2)
        v1.refresh_from_db()
        v2.refresh_from_db()

        self.assertEqual(v1.status, NormativeDatasetVersion.Status.RETIRED)
        self.assertEqual(v2.status, NormativeDatasetVersion.Status.ACTIVE)
        self.assertEqual(
            NormativeDatasetVersion.objects.filter(status="active").count(),
            1,
        )

    def test_database_constraint_prevents_two_active_versions(self):
        self.create_participant()
        v1, _result = self.create_prepared_version("v-test-1")
        activate_normative_version(v1)
        v2, _result = self.create_prepared_version("v-test-2")

        with self.assertRaises(IntegrityError), transaction.atomic():
            NormativeDatasetVersion.objects.filter(pk=v2.pk).update(
                status=NormativeDatasetVersion.Status.ACTIVE,
                activated_at=v1.activated_at,
            )

    def test_active_version_participants_cannot_be_changed(self):
        self.create_participant()
        version = create_normative_version("v-test-1")
        prepare_normative_version(version)
        activate_normative_version(version)
        later = self.create_participant("4")

        # ``version`` deliberately remains a stale in-memory draft instance;
        # protection must consult the committed database lifecycle.
        with self.assertRaises(ValidationError):
            version.participants.add(later)

    def test_active_version_participants_cannot_be_cleared(self):
        self.create_participant()
        version = create_normative_version("v-test-1")
        prepare_normative_version(version)
        activate_normative_version(version)

        with self.assertRaises(ValidationError):
            version.participants.clear()

    def test_active_version_cannot_be_reprepared(self):
        self.create_participant()
        version, _result = self.create_prepared_version("v-test-1")
        activate_normative_version(version)

        with self.assertRaises(NormativeVersionError):
            prepare_normative_version(version)

    def test_scores_and_percentiles_remain_separate_by_version(self):
        self.create_participant("1")
        v1, _result = self.create_prepared_version("v-test-1")
        activate_normative_version(v1)
        self.create_participant("4")
        v2, _result = self.create_prepared_version("v-test-2")

        self.assertEqual(NormativeScaleScore.objects.filter(version=v1).count(), 1)
        self.assertEqual(NormativeScaleScore.objects.filter(version=v2).count(), 2)
        self.assertEqual(calculate_percentile(self.scale, 2, version=v1), 100)
        self.assertEqual(calculate_percentile(self.scale, 2, version=v2), 50)
        self.assertEqual(
            calculate_spectrum_percentile(self.spectrum, 2, version=v1),
            100,
        )
        self.assertEqual(
            calculate_spectrum_percentile(self.spectrum, 2, version=v2),
            50,
        )
        self.assertEqual(calculate_percentile(self.scale, 2), 100)

    def test_new_participant_does_not_change_active_percentile(self):
        self.create_participant("1")
        version, _result = self.create_prepared_version("v-test-1")
        activate_normative_version(version)
        before = calculate_percentile(self.scale, 2)

        self.create_participant("4")

        self.assertEqual(calculate_percentile(self.scale, 2), before)
        self.assertEqual(version.participant_count, 1)

    def test_new_participant_counts_and_next_snapshot(self):
        self.create_participant("1")
        v1, _result = self.create_prepared_version("v-test-1")
        activate_normative_version(v1)
        self.create_participant("3")
        self.create_participant("4")

        counts = get_normative_participant_counts()

        self.assertEqual(get_unversioned_normative_participant_count(), 2)
        self.assertEqual(
            counts,
            {"total": 3, "active_version": 1, "not_in_active_version": 2},
        )
        v2 = create_normative_version("v-test-2")
        self.assertEqual(v2.participant_count, 3)

    def test_historical_version_and_scores_remain_available(self):
        self.create_participant("1")
        v1, _result = self.create_prepared_version("v-test-1")
        activate_normative_version(v1)
        v2, _result = self.create_prepared_version("v-test-2")
        activate_normative_version(v2)

        self.assertTrue(NormativeDatasetVersion.objects.filter(pk=v1.pk).exists())
        self.assertTrue(NormativeScaleScore.objects.filter(version=v1).exists())
        with self.assertRaises(ValidationError):
            NormativeScaleScore.objects.filter(version=v1).delete()

    def test_report_is_pinned_to_first_active_version(self):
        self.create_participant("1")
        v1, _result = self.create_prepared_version("v-test-1")
        activate_normative_version(v1)
        patient = User.objects.create_user(username="versioned-report-patient")
        submission = QuestionnaireSubmission.objects.create(user=patient)

        self.assertEqual(get_or_assign_report_normative_version(submission), v1)
        v2, _result = self.create_prepared_version("v-test-2")
        activate_normative_version(v2)
        submission.refresh_from_db()

        self.assertEqual(submission.report_normative_version, v1)
        self.assertEqual(get_or_assign_report_normative_version(submission), v1)

    def test_normative_models_do_not_reference_clinical_records(self):
        clinical_models = {
            QuestionnaireSubmission,
            UserAnswer,
            DynamicAnswer,
            User,
        }
        normative_models = (
            NormativeDatasetVersion,
            NormativeDatasetMembership,
            NormativeParticipant,
            NormativeAnswer,
            NormativeScaleScore,
            NormativeSpectrumScore,
        )
        for model in normative_models:
            related_models = {
                field.related_model
                for field in model._meta.fields
                if field.many_to_one
            }
            self.assertTrue(related_models.isdisjoint(clinical_models))


class ResetNormativeDatasetCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.spectrum = Spectra.objects.create(name="Reset spectrum")
        subfactor = Subfactor.objects.create(
            name="Reset subfactor",
            spectra=cls.spectrum,
        )
        cls.scale = Scale.objects.create(name="Reset scale", subfactor=subfactor)
        cls.question = Question.objects.create(
            scale=cls.scale,
            item_code="reset-1",
            question_text="Reset test",
        )

    def setUp(self):
        old_participant = NormativeParticipant.objects.create(
            age=99,
            sex="Masculino",
        )
        NormativeAnswer.objects.create(
            participant=old_participant,
            question=self.question,
            answer="4",
        )
        version = create_normative_version("v1")
        prepare_normative_version(version)
        activate_normative_version(version)

        self.csv_file = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            suffix=".csv",
        )
        writer = csv.DictWriter(
            self.csv_file,
            fieldnames=["Age", "sex", "reset-1"],
            delimiter=";",
        )
        writer.writeheader()
        writer.writerow({"Age": "31", "sex": "Feminino", "reset-1": "2"})
        self.csv_file.flush()

    def tearDown(self):
        self.csv_file.close()

    def test_reset_requires_explicit_confirmation(self):
        with self.assertRaises(CommandError):
            call_command("reset_normative_dataset", self.csv_file.name)

        self.assertEqual(NormativeParticipant.objects.get().age, 99)

    def test_reset_is_refused_after_a_report_uses_v1(self):
        patient = User.objects.create_user(username="reset-report-patient")
        version = get_active_normative_version()
        QuestionnaireSubmission.objects.create(
            user=patient,
            report_normative_version=version,
        )

        with self.assertRaises(CommandError):
            call_command(
                "reset_normative_dataset",
                self.csv_file.name,
                confirm=True,
            )

        self.assertEqual(NormativeParticipant.objects.get().age, 99)

    def test_reset_reimports_prepares_and_activates_v1_atomically(self):
        call_command(
            "reset_normative_dataset",
            self.csv_file.name,
            confirm=True,
        )

        participant = NormativeParticipant.objects.get()
        version = get_active_normative_version()
        self.assertEqual(participant.age, 31)
        self.assertEqual(participant.sex, "Feminino")
        self.assertEqual(participant.answers.get().answer, "2")
        self.assertEqual(version.name, "v1")
        self.assertEqual(version.participant_count, 1)
        self.assertIsNotNone(version.prepared_at)
        self.assertIsNotNone(version.activated_at)
        self.assertEqual(
            NormativeScaleScore.objects.get(version=version).raw_score,
            2,
        )
        self.assertEqual(
            NormativeSpectrumScore.objects.get(version=version).raw_score,
            2,
        )
