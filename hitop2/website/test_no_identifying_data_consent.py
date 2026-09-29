from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from polls.models import Question, QuestionnaireSubmission, Scale, Spectra, Subfactor


class NoIdentifyingDataConsentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_sociodemographic", verbosity=0)
        cls.professional = User.objects.create_user(username="consent-professional")
        cls.professional.userprofile.user_type = "professional"
        cls.professional.userprofile.is_verified = True
        cls.professional.userprofile.save(update_fields=["user_type", "is_verified"])

        cls.patient = User.objects.create_user(username="consent-patient")
        cls.patient.userprofile.user_type = "patient"
        cls.patient.userprofile.professional = cls.professional
        cls.patient.userprofile.save(update_fields=["user_type", "professional"])
        cls.spectrum = Spectra.objects.create(name="Consent spectrum")
        subfactor = Subfactor.objects.create(
            name="Consent subfactor",
            spectra=cls.spectrum,
        )
        scale = Scale.objects.create(name="Consent scale", subfactor=subfactor)
        Question.objects.create(
            scale=scale,
            item_code="CONSENT-1",
            question_text="Consent test question",
        )

    def setUp(self):
        self.client.force_login(self.professional)
        patcher = patch(
            "website.professional_environment.get_or_assign_report_normative_version",
            return_value=object(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def post_data(self, **overrides):
        data = {
            "title": "Aplicação sem dados identificativos",
            "spectra": [self.spectrum.pk],
        }
        data.update(overrides)
        return data

    def test_consent_uses_form_checkbox_styling_immediately_before_button(self):
        response = self.client.get(
            reverse("website:new_questionnaire", args=[self.patient.userprofile.pk])
        )
        content = response.content.decode()

        self.assertContains(
            response,
            'name="no_identifying_data_confirmed" class="form-check-input"',
        )
        self.assertLess(
            content.index('name="no_identifying_data_confirmed"'),
            content.index("Criar aplicação"),
        )

    def test_new_submission_requires_consent(self):
        response = self.client.post(
            reverse("website:new_questionnaire", args=[self.patient.userprofile.pk]),
            self.post_data(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.")
        self.assertFalse(QuestionnaireSubmission.objects.exists())

    def test_new_submission_records_consent(self):
        response = self.client.post(
            reverse("website:new_questionnaire", args=[self.patient.userprofile.pk]),
            self.post_data(no_identifying_data_confirmed="on"),
        )

        self.assertRedirects(
            response,
            reverse("website:dashboard"),
            fetch_redirect_response=False,
        )
        submission = QuestionnaireSubmission.objects.get()
        self.assertTrue(submission.no_identifying_data_confirmed)

    def test_create_patient_requires_consent_before_creating_any_record(self):
        url = reverse("website:create_patient")
        self.client.get(url)

        response = self.client.post(url, self.post_data())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.")
        self.assertFalse(
            User.objects.filter(userprofile__user_type="patient").exclude(
                pk=self.patient.pk
            ).exists()
        )
        self.assertFalse(QuestionnaireSubmission.objects.exists())

    def test_create_patient_records_consent_on_first_submission(self):
        url = reverse("website:create_patient")
        self.client.get(url)

        response = self.client.post(
            url,
            self.post_data(no_identifying_data_confirmed="on"),
        )

        self.assertEqual(response.status_code, 302)
        submission = QuestionnaireSubmission.objects.get()
        self.assertTrue(submission.no_identifying_data_confirmed)
