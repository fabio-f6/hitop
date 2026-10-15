import csv
import hashlib
import io
import json
import os
import zipfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from polls.models import (
    DynamicAnswer,
    DynamicChoice,
    DynamicQuestion,
    NormativeAnswer,
    NormativeDatasetMembership,
    NormativeDatasetVersion,
    NormativeParticipant,
    NormativeScaleScore,
    NormativeSpectrumScore,
    Question,
    QuestionCategory,
    QuestionnaireCollection,
    QuestionnaireSubmission,
    Scale,
    Spectra,
    Subfactor,
    UserAnswer,
)
from .models import AdministrativeAuditLog


def response_bytes(response):
    return b"".join(response.streaming_content)


def csv_rows(archive, name):
    text = archive.read(name).decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def preserve_validation_artifact(filename, payload):
    directory = os.getenv("HITOP_EXPORT_VALIDATION_DIR")
    if not directory:
        return
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    (target / filename).write_bytes(payload)


class ExportFixtureMixin:
    password = "Strong-admin-password-91"

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="export-admin",
            email="admin-never-export@example.test",
            password=cls.password,
            is_staff=True,
        )
        cls.admin.userprofile.user_type = "admin"
        cls.admin.userprofile.save(update_fields=["user_type"])
        cls.non_staff_admin = User.objects.create_user(
            username="non-staff-admin", password=cls.password,
        )
        cls.non_staff_admin.userprofile.user_type = "admin"
        cls.non_staff_admin.userprofile.save(update_fields=["user_type"])
        cls.professional = User.objects.create_user(
            username="professional", password=cls.password,
        )
        cls.professional.userprofile.user_type = "professional"
        cls.professional.userprofile.is_verified = True
        cls.professional.userprofile.save(update_fields=["user_type", "is_verified"])
        cls.researcher = User.objects.create_user(
            username="researcher", password=cls.password,
        )
        cls.researcher.userprofile.user_type = "professional"
        cls.researcher.userprofile.is_verified = True
        cls.researcher.userprofile.is_researcher = True
        cls.researcher.userprofile.save(
            update_fields=["user_type", "is_verified", "is_researcher"]
        )
        cls.patient = User.objects.create_user(
            username="patient-secret-username",
            email="patient-secret@example.test",
            password="Patient-secret-password-33",
        )
        cls.patient.userprofile.user_type = "patient"
        cls.patient.userprofile.professional = cls.professional
        cls.patient.userprofile.save(update_fields=["user_type", "professional"])

        cls.spectrum = Spectra.objects.create(name="Internalizing")
        cls.subfactor = Subfactor.objects.create(
            name="Distress", spectra=cls.spectrum
        )
        cls.scale = Scale.objects.create(name="Anxious Worry", subfactor=cls.subfactor)
        cls.question_one = Question.objects.create(
            scale=cls.scale, item_code="HiTOP_001", question_text="=formula-safe"
        )
        cls.question_two = Question.objects.create(
            scale=cls.scale, item_code="HiTOP_002", question_text="Second question"
        )
        cls.valid_scale = Scale.objects.create(name="Valid scale", subfactor=cls.subfactor)
        cls.question_three = Question.objects.create(
            scale=cls.valid_scale, item_code="HiTOP_003", question_text="Third question"
        )
        catch_spectrum = Spectra.objects.create(name="Catch")
        catch_subfactor = Subfactor.objects.create(name="Catch", spectra=catch_spectrum)
        catch_scale = Scale.objects.create(name="Catch", subfactor=catch_subfactor)
        cls.attention = Question.objects.create(
            scale=catch_scale,
            item_code="ATT_001",
            question_text="Attention",
            is_attention_check=True,
            expected_answer="2",
        )

        cls.production_version = NormativeDatasetVersion.objects.create(name="v-export")
        cls.percentile_version = NormativeDatasetVersion.objects.create(name="v-percentile")
        percentile_participant = NormativeParticipant.objects.create(source="real")
        NormativeDatasetMembership.objects.create(
            version=cls.percentile_version, participant=percentile_participant
        )
        NormativeScaleScore.objects.create(
            version=cls.percentile_version,
            participant=percentile_participant,
            scale=cls.valid_scale,
            raw_score=3.0,
        )
        cls.submission = QuestionnaireSubmission.objects.create(
            user=cls.patient,
            title="Never export this title",
            completed=True,
            completed_at=timezone.now(),
            is_open=False,
            report_normative_version=cls.percentile_version,
        )
        cls.submission.spectra.set([cls.spectrum])
        UserAnswer.objects.create(
            user=cls.patient,
            submission=cls.submission,
            question=cls.question_one,
            answer="3",
        )
        UserAnswer.objects.create(
            user=cls.patient,
            submission=cls.submission,
            question=cls.question_two,
            answer="5",
        )
        UserAnswer.objects.create(
            user=cls.patient,
            submission=cls.submission,
            question=cls.question_three,
            answer="4",
        )

        category = QuestionCategory.objects.create(name="Dados Sociodemográficos")
        cls.socio_radio = DynamicQuestion.objects.create(
            category=category,
            question_id="safe_radio",
            label="Safe radio",
            question_type="radio",
            order=1,
        )
        DynamicChoice.objects.create(
            question=cls.socio_radio, value="1", label="=dangerous label", order=1
        )
        cls.socio_text = DynamicQuestion.objects.create(
            category=category,
            question_id="free_text",
            label="Free text",
            question_type="text",
            order=2,
        )
        DynamicAnswer.objects.create(
            user=cls.patient,
            submission=cls.submission,
            question=cls.socio_radio,
            answer_value="1",
        )
        DynamicAnswer.objects.create(
            user=cls.patient,
            submission=cls.submission,
            question=cls.socio_text,
            answer_value="identifying free text",
        )

        cls.collection = QuestionnaireCollection.objects.create(
            owner=cls.researcher, name="Anonymous collection"
        )
        cls.collection.spectra.set([cls.spectrum])
        cls.collection_submission = QuestionnaireSubmission.objects.create(
            collection=cls.collection,
            participant_number=1,
            completed=True,
            completed_at=timezone.now(),
            is_open=False,
            no_identifying_data_confirmed=True,
        )
        cls.collection_submission.spectra.set([cls.spectrum])
        UserAnswer.objects.create(
            submission=cls.collection_submission,
            question=cls.question_one,
            answer="4",
        )

        cls.incomplete = QuestionnaireSubmission.objects.create(
            user=cls.patient,
            title="Incomplete",
        )
        cls.incomplete.spectra.set([cls.spectrum])
        UserAnswer.objects.create(
            user=cls.patient,
            submission=cls.incomplete,
            question=cls.question_one,
            answer="2",
        )

        cls.test_patient = User.objects.create_user(
            username="test-patient", password="test-password"
        )
        cls.test_patient.userprofile.user_type = "patient"
        cls.test_patient.userprofile.is_test_data = True
        cls.test_patient.userprofile.test_environment_owner = cls.admin
        cls.test_patient.userprofile.save(
            update_fields=["user_type", "is_test_data", "test_environment_owner"]
        )
        cls.test_submission = QuestionnaireSubmission.objects.create(
            user=cls.test_patient,
            completed=True,
            completed_at=timezone.now(),
            is_open=False,
            is_test_data=True,
            simulation_mode="simulated",
        )
        cls.test_submission.spectra.set([cls.spectrum])
        UserAnswer.objects.create(
            user=cls.test_patient,
            submission=cls.test_submission,
            question=cls.question_one,
            answer="1",
        )

    def login_admin(self):
        self.client.force_login(self.admin)

    def scientific_post(self, **overrides):
        data = {
            "origin": "all",
            "environment": "production",
            "state": "completed",
            "include_answers": "on",
            "include_sociodemographics": "on",
            "include_results": "on",
            "password": self.password,
        }
        data.update(overrides)
        return self.client.post(reverse("administration:scientific_data_export"), data)


class ScientificDataExportTests(ExportFixtureMixin, TestCase):
    def test_permission_boundary_requires_admin_and_staff(self):
        url = reverse("administration:scientific_data_export")
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)
        for user in (self.non_staff_admin, self.professional, self.researcher):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_password_post_csrf_and_private_download_headers(self):
        self.login_admin()
        bad = self.scientific_post(password="wrong")
        self.assertEqual(bad.status_code, 200)
        self.assertContains(bad, "password atual está incorreta")
        self.assertFalse(
            AdministrativeAuditLog.objects.filter(
                action=AdministrativeAuditLog.Action.SCIENTIFIC_DATA_EXPORTED
            ).exists()
        )

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        self.assertEqual(
            csrf_client.post(reverse("administration:scientific_data_export"), {}).status_code,
            403,
        )

        response = self.scientific_post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertTrue(
            AdministrativeAuditLog.objects.filter(
                action=AdministrativeAuditLog.Action.SCIENTIFIC_DATA_EXPORTED
            ).exists()
        )

    def test_zip_preserves_raw_states_relationships_and_privacy(self):
        self.login_admin()
        before = QuestionnaireSubmission.objects.values(
            "pk", "normative_status", "report_normative_version_id", "completed"
        ).order_by("pk")
        before = list(before)
        payload = response_bytes(self.scientific_post())
        preserve_validation_artifact("scientific-example.zip", payload)
        self.assertEqual(before, list(QuestionnaireSubmission.objects.values(
            "pk", "normative_status", "report_normative_version_id", "completed"
        ).order_by("pk")))
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            self.assertTrue(archive.testzip() is None)
            expected = {
                "participants.csv", "submissions.csv", "answers.csv",
                "sociodemographic_answers.csv", "scale_scores.csv",
                "spectrum_scores.csv", "questions.csv", "scales.csv",
                "subfactors.csv", "spectra.csv", "normative_versions.csv",
                "metadata.json", "README.txt", "manifest.csv",
            }
            self.assertEqual(set(archive.namelist()), expected)
            for name in archive.namelist():
                archive.read(name).decode("utf-8")

            submissions = csv_rows(archive, "submissions.csv")
            self.assertEqual(len(submissions), 2)
            self.assertEqual({row["origin"] for row in submissions}, {"clinical", "collection"})
            self.assertEqual({row["environment"] for row in submissions}, {"production"})
            participants = csv_rows(archive, "participants.csv")
            self.assertEqual(len(participants), 2)
            self.assertTrue(all(row["participant_id"].startswith("P") for row in participants))

            answers = csv_rows(archive, "answers.csv")
            clinical_id = next(
                row["submission_id"] for row in submissions if row["origin"] == "clinical"
            )
            answer_map = {
                row["item_code"]: row
                for row in answers if row["submission_id"] == clinical_id
            }
            self.assertEqual(answer_map["HiTOP_001"]["answer"], "3")
            self.assertEqual(answer_map["HiTOP_001"]["response_status"], "answered_valid")
            self.assertEqual(answer_map["HiTOP_002"]["response_status"], "explicitly_omitted")
            self.assertEqual(answer_map["ATT_001"]["response_status"], "presented_unanswered")
            scale_score = next(
                row for row in csv_rows(archive, "scale_scores.csv")
                if row["submission_id"] == clinical_id
                and row["scale_code"] == "Anxious Worry"
            )
            self.assertEqual(scale_score["is_valid"], "false")
            self.assertEqual(scale_score["raw_score"], "")
            valid_score = next(
                row for row in csv_rows(archive, "scale_scores.csv")
                if row["submission_id"] == clinical_id
                and row["scale_code"] == "Valid scale"
            )
            self.assertEqual(valid_score["raw_score"], "4")
            self.assertEqual(valid_score["percentile"], "100")
            self.assertEqual(valid_score["normative_version"], "v-percentile")

            socio = csv_rows(archive, "sociodemographic_answers.csv")
            self.assertNotIn("free_text", {row["question_id"] for row in socio})
            safe = next(row for row in socio if row["question_id"] == "safe_radio")
            self.assertEqual(safe["answer_label"], "'=dangerous label")
            self.assertEqual(
                json.loads(safe["csv_injection_escaped_fields"]), ["answer_label"]
            )

            all_text = "\n".join(
                archive.read(name).decode("utf-8") for name in archive.namelist()
            )
            self.assertNotIn("patient-secret-username", all_text)
            self.assertNotIn("patient-secret@example.test", all_text)
            self.assertNotIn("Patient-secret-password-33", all_text)
            self.assertNotIn("identifying free text", all_text)

            metadata = json.loads(archive.read("metadata.json"))
            self.assertEqual(metadata["submission_count"], 2)
            self.assertEqual(metadata["environment"], "production")
            manifest = csv_rows(archive, "manifest.csv")
            for row in manifest:
                self.assertEqual(
                    row["sha256"], hashlib.sha256(archive.read(row["filename"])).hexdigest()
                )

    def test_filters_default_completion_origin_period_and_test_isolation(self):
        self.login_admin()
        production = zipfile.ZipFile(io.BytesIO(response_bytes(self.scientific_post())))
        self.assertEqual(len(csv_rows(production, "submissions.csv")), 2)

        clinical = zipfile.ZipFile(io.BytesIO(response_bytes(
            self.scientific_post(origin="clinical")
        )))
        self.assertEqual(len(csv_rows(clinical, "submissions.csv")), 1)
        self.assertEqual(csv_rows(clinical, "submissions.csv")[0]["origin"], "clinical")

        collection = zipfile.ZipFile(io.BytesIO(response_bytes(
            self.scientific_post(origin="collection")
        )))
        self.assertEqual(len(csv_rows(collection, "submissions.csv")), 1)
        self.assertEqual(csv_rows(collection, "submissions.csv")[0]["origin"], "collection")

        test_zip = zipfile.ZipFile(io.BytesIO(response_bytes(
            self.scientific_post(environment="test")
        )))
        rows = csv_rows(test_zip, "submissions.csv")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["environment"], "test")

        future = (timezone.localdate() + timedelta(days=1)).isoformat()
        none_zip = zipfile.ZipFile(io.BytesIO(response_bytes(
            self.scientific_post(date_from=future)
        )))
        self.assertEqual(csv_rows(none_zip, "submissions.csv"), [])

        all_states = zipfile.ZipFile(io.BytesIO(response_bytes(
            self.scientific_post(state="all")
        )))
        all_submissions = csv_rows(all_states, "submissions.csv")
        self.assertEqual(len(all_submissions), 3)
        incomplete_id = next(row["submission_id"] for row in all_submissions if row["completed"] == "false")
        clinical_participants = {
            row["participant_id"] for row in all_submissions if row["origin"] == "clinical"
        }
        self.assertEqual(len(clinical_participants), 1)
        self.assertNotIn(
            incomplete_id,
            {row["submission_id"] for row in csv_rows(all_states, "scale_scores.csv")},
        )


class NormativeDatasetExportTests(ExportFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.real_participant = NormativeParticipant.objects.create(
            source="real", age=41, sex="Feminino"
        )
        NormativeDatasetMembership.objects.create(
            version=cls.production_version, participant=cls.real_participant
        )
        NormativeAnswer.objects.create(
            participant=cls.real_participant, question=cls.question_one, answer="3"
        )
        NormativeScaleScore.objects.create(
            version=cls.production_version,
            participant=cls.real_participant,
            scale=cls.scale,
            raw_score=3.125,
        )
        NormativeSpectrumScore.objects.create(
            version=cls.production_version,
            participant=cls.real_participant,
            spectrum=cls.spectrum,
            raw_score=3.125,
        )
        cls.outsider = NormativeParticipant.objects.create(
            source="real", age=80, sex="Masculino"
        )

        cls.test_version = NormativeDatasetVersion.objects.create(
            name="test-export", environment="test", baseline_version=cls.production_version
        )
        NormativeDatasetMembership.objects.create(
            version=cls.test_version, participant=cls.real_participant
        )
        cls.synthetic = NormativeParticipant.objects.create(
            source="synthetic", age=30, sex="Masculino", source_submission=cls.test_submission
        )
        NormativeDatasetMembership.objects.create(
            version=cls.test_version, participant=cls.synthetic
        )

    def normative_post(self, version=None, password=None):
        version = version or self.production_version
        return self.client.post(
            reverse("administration:normative_dataset_export", args=[version.pk]),
            {"password": password or self.password},
        )

    def test_permission_password_and_all_lifecycle_states(self):
        url = reverse(
            "administration:normative_dataset_export", args=[self.production_version.pk]
        )
        for user in (self.non_staff_admin, self.professional, self.researcher):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 403)
        self.login_admin()
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.normative_post(password="wrong").status_code, 200)

        for status in ("draft", "active", "retired"):
            NormativeDatasetVersion.objects.filter(pk=self.production_version.pk).update(
                status=status,
                activated_at=timezone.now() if status != "draft" else None,
            )
            self.production_version.refresh_from_db()
            response = self.normative_post()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/zip")

    def test_selected_snapshot_and_persisted_scores_are_exported_without_mutation(self):
        self.login_admin()
        before_version = NormativeDatasetVersion.objects.values().get(
            pk=self.production_version.pk
        )
        before_submission = QuestionnaireSubmission.objects.values(
            "normative_status", "normative_exported_at", "report_normative_version_id"
        ).get(pk=self.submission.pk)
        payload = response_bytes(self.normative_post())
        preserve_validation_artifact("normative-example.zip", payload)
        archive = zipfile.ZipFile(io.BytesIO(payload))
        participants = csv_rows(archive, "normative_participants.csv")
        self.assertEqual(len(participants), 1)
        self.assertEqual(participants[0]["age"], "41")
        memberships = csv_rows(archive, "normative_memberships.csv")
        self.assertEqual(len(memberships), 1)
        self.assertEqual(memberships[0]["version_name"], "v-export")
        self.assertEqual(csv_rows(archive, "normative_scale_scores.csv")[0]["raw_score"], "3.125")
        self.assertEqual(
            csv_rows(archive, "normative_spectrum_scores.csv")[0]["raw_score"], "3.125"
        )
        self.assertEqual(
            before_version,
            NormativeDatasetVersion.objects.values().get(pk=self.production_version.pk),
        )
        self.assertEqual(
            before_submission,
            QuestionnaireSubmission.objects.values(
                "normative_status", "normative_exported_at", "report_normative_version_id"
            ).get(pk=self.submission.pk),
        )
        audit = AdministrativeAuditLog.objects.get(
            action=AdministrativeAuditLog.Action.NORMATIVE_DATASET_EXPORTED
        )
        self.assertNotIn("answers", audit.metadata)
        self.assertNotIn("scores", audit.metadata)

    def test_test_version_preserves_baseline_and_synthetic_sources(self):
        self.login_admin()
        archive = zipfile.ZipFile(io.BytesIO(response_bytes(
            self.normative_post(self.test_version)
        )))
        participants = csv_rows(archive, "normative_participants.csv")
        self.assertEqual({row["source"] for row in participants}, {"real", "synthetic"})
        metadata = json.loads(archive.read("metadata.json"))
        self.assertEqual(metadata["environment"], "test")
        self.assertEqual(metadata["normative_version"]["baseline_version"], "v-export")
        self.production_version.refresh_from_db()
        self.assertEqual(self.production_version.environment, "production")

    def test_get_never_starts_download_and_post_requires_csrf(self):
        self.login_admin()
        url = reverse(
            "administration:normative_dataset_export", args=[self.production_version.pk]
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response["Content-Type"], "application/zip")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        self.assertEqual(csrf_client.post(url, {"password": self.password}).status_code, 403)

    def test_invalid_synthetic_production_membership_blocks_export_and_audit(self):
        synthetic = NormativeParticipant.objects.create(source="synthetic")
        NormativeDatasetMembership.objects.bulk_create([
            NormativeDatasetMembership(
                version=self.production_version,
                participant=synthetic,
            )
        ])
        self.login_admin()
        response = self.normative_post()
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response["Content-Type"], "application/zip")
        self.assertContains(response, "associação sintética inválida")
        self.assertFalse(
            AdministrativeAuditLog.objects.filter(
                action=AdministrativeAuditLog.Action.NORMATIVE_DATASET_EXPORTED
            ).exists()
        )
