from io import BytesIO
from zipfile import ZipFile

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from polls.models import NormativeDatasetVersion, QuestionnaireSubmission
from polls.normative_versions import NormativeVersionError

from .views import _build_report_context


class NormativeTraceabilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.professional = User.objects.create_user(username="trace-professional")
        profile = cls.professional.userprofile
        profile.user_type = "professional"
        profile.is_verified = True
        profile.area_formacao = "Psicologia"
        profile.cedula_profissional = "TRACE-1"
        profile.save()

        cls.patient = User.objects.create_user(username="trace-patient")
        profile = cls.patient.userprofile
        profile.user_type = "patient"
        profile.professional = cls.professional
        profile.save()

        cls.administrator = User.objects.create_user(username="trace-admin")
        profile = cls.administrator.userprofile
        profile.user_type = "admin"
        profile.save()

        cls.test_patient = User.objects.create_user(username="trace-test-patient")
        profile = cls.test_patient.userprofile
        profile.user_type = "patient"
        profile.is_test_data = True
        profile.test_environment_owner = cls.administrator
        profile.save()

    def _version(self, name, environment="production", *, active=False):
        version = NormativeDatasetVersion.objects.create(
            name=name,
            environment=environment,
        )
        if active:
            NormativeDatasetVersion.objects.filter(
                environment=environment,
                status=NormativeDatasetVersion.Status.ACTIVE,
            ).update(status=NormativeDatasetVersion.Status.RETIRED)
            NormativeDatasetVersion.objects.filter(pk=version.pk).update(
                status=NormativeDatasetVersion.Status.ACTIVE,
                activated_at=timezone.now(),
            )
            version.refresh_from_db()
        return version

    def _submission(self, *, version=None, test=False):
        return QuestionnaireSubmission.objects.create(
            user=self.test_patient if test else self.patient,
            title="Rastreabilidade",
            completed=True,
            is_open=False,
            is_test_data=test,
            simulation_mode="simulated" if test else "normal",
            report_normative_version=version,
        )

    def test_production_report_shows_pinned_version_and_not_new_active_version(self):
        pinned = self._version("v1")
        submission = self._submission(version=pinned)
        self._version("v2", active=True)
        self.client.force_login(self.professional)

        response = self.client.get(reverse("website:report_preview", args=[submission.pk]))

        self.assertContains(response, "Base normativa:")
        self.assertContains(response, "v1 (Produção)")
        self.assertNotContains(response, "v2 (Produção)")
        submission.refresh_from_db()
        self.assertEqual(submission.report_normative_version, pinned)

    def test_test_report_shows_pinned_test_version_after_active_test_changes(self):
        self._version("prod-base")
        pinned = self._version("arbitrary-name", "test")
        submission = self._submission(version=pinned, test=True)
        self._version("next", "test", active=True)
        self.client.force_login(self.administrator)

        response = self.client.get(reverse(
            "administration:test_report_preview", args=[submission.pk]
        ))

        self.assertContains(response, "arbitrary-name (Teste)")
        self.assertNotContains(response, "next (Teste)")
        self.assertNotContains(response, "arbitrary-name (Produção)")

    def test_test_report_production_fallback_is_labelled_production_and_pinned(self):
        production = self._version("fallback-v1", active=True)
        submission = self._submission(test=True)
        self.client.force_login(self.administrator)

        response = self.client.get(reverse(
            "administration:test_report_preview", args=[submission.pk]
        ))

        self.assertContains(response, "fallback-v1 (Produção)")
        submission.refresh_from_db()
        self.assertEqual(submission.report_normative_version, production)

    def test_card_uses_pinned_version_and_unassigned_card_is_read_only(self):
        pinned = self._version("card-test", "test")
        pinned_submission = self._submission(version=pinned, test=True)
        unassigned = self._submission(test=True)
        self.client.force_login(self.administrator)

        response = self.client.get(reverse(
            "administration:test_patient_submissions", args=[self.test_patient.pk]
        ))

        self.assertContains(response, "card-test (Teste)")
        self.assertContains(response, "Base normativa:")
        self.assertContains(response, "ainda não atribuída")
        pinned_submission.refresh_from_db()
        unassigned.refresh_from_db()
        self.assertEqual(pinned_submission.report_normative_version, pinned)
        self.assertIsNone(unassigned.report_normative_version)

    def test_clinical_card_listing_does_not_pin_active_version(self):
        self._version("active-but-not-used", active=True)
        submission = self._submission()
        self.client.force_login(self.professional)

        response = self.client.get(reverse(
            "website:patient_submissions", args=[self.patient.pk]
        ))

        self.assertContains(response, "Base normativa:")
        self.assertContains(response, "ainda não atribuída")
        submission.refresh_from_db()
        self.assertIsNone(submission.report_normative_version)

    def test_report_generation_keeps_using_existing_pinning_mechanism(self):
        active = self._version("generated-pin", active=True)
        submission = self._submission()
        self.client.force_login(self.professional)

        self.client.get(reverse("website:report_preview", args=[submission.pk]))

        submission.refresh_from_db()
        self.assertEqual(submission.report_normative_version, active)

    def test_production_report_rejects_structurally_test_version(self):
        test_version = self._version("not-prefixed-as-test", "test")
        submission = self._submission()
        QuestionnaireSubmission.objects.filter(pk=submission.pk).update(
            report_normative_version=test_version,
        )
        submission.refresh_from_db()

        with self.assertRaises(NormativeVersionError):
            _build_report_context(submission)

    def test_docx_footer_contains_pinned_version(self):
        pinned = self._version("docx-v1")
        submission = self._submission(version=pinned)
        self.client.force_login(self.professional)

        response = self.client.get(reverse(
            "website:export_report_docx", args=[submission.pk]
        ))

        with ZipFile(BytesIO(response.content)) as archive:
            footer_xml = " ".join(
                archive.read(name).decode()
                for name in archive.namelist()
                if name.startswith("word/footer") and name.endswith(".xml")
            )
        self.assertIn("Base normativa: docx-v1 (Produção)", footer_xml)
