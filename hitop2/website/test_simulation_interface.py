from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from polls.models import (
    Question,
    QuestionCategory,
    QuestionnaireSubmission,
    Scale,
    Spectra,
    Subfactor,
)

from .forms import NewQuestionnaireForm


class SimulationInterfaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_sociodemographic", verbosity=0)
        cls.professional = User.objects.create_user(
            username="simulation-professional",
            password="test-password",
        )
        cls.professional.userprofile.user_type = "professional"
        cls.professional.userprofile.is_verified = True
        cls.professional.userprofile.save()

        cls.patient = User.objects.create_user(username="simulation-ui-patient")
        cls.patient.userprofile.user_type = "patient"
        cls.patient.userprofile.professional = cls.professional
        cls.patient.userprofile.save()

        cls.spectrum = Spectra.objects.create(name="Simulation UI spectrum")
        subfactor = Subfactor.objects.create(
            name="Simulation UI subfactor",
            spectra=cls.spectrum,
        )
        scale = Scale.objects.create(name="Simulation UI scale", subfactor=subfactor)
        Question.objects.create(
            scale=scale,
            item_code="simulation-ui-1",
            question_text="Simulation UI question",
        )

    def setUp(self):
        self.client.force_login(self.professional)

    def url(self):
        return reverse(
            "website:new_questionnaire",
            args=[self.patient.userprofile.id],
        )

    def test_advanced_options_are_present_but_initially_hidden(self):
        response = self.client.get(self.url())
        self.assertContains(response, "Opções de simulação")
        self.assertContains(response, "Elegível para base normativa")
        self.assertContains(response, "Múltiplas falhas")
        self.assertRegex(
            response.content.decode(),
            r"data-simulation-options\s+hidden",
        )

    def test_selected_simulation_values_are_saved(self):
        response = self.client.post(self.url(), {
            "title": "Simulação configurada",
            "spectra": [self.spectrum.id],
            "simulation_mode": "simulated",
            "sociodemographic_simulation_mode": "ineligible_mental_health",
            "simulation_response_profile": "high",
            "simulation_missing_percentage": "30",
            "simulation_attention_mode": "one_failure",
            "simulation_seed": "2468",
        })

        self.assertRedirects(
            response,
            reverse("website:dashboard"),
            fetch_redirect_response=False,
        )
        submission = QuestionnaireSubmission.objects.get(
            title="Simulação configurada"
        )
        self.assertEqual(submission.simulation_mode, "simulated")
        self.assertEqual(
            submission.sociodemographic_simulation_mode,
            "ineligible_mental_health",
        )
        self.assertEqual(submission.simulation_response_profile, "high")
        self.assertEqual(submission.simulation_missing_percentage, 30)
        self.assertEqual(submission.simulation_attention_mode, "one_failure")
        self.assertEqual(submission.simulation_seed, 2468)

    def test_normal_application_forces_safe_defaults(self):
        response = self.client.post(self.url(), {
            "title": "Aplicação normal",
            "spectra": [self.spectrum.id],
            "simulation_mode": "normal",
            "sociodemographic_simulation_mode": "eligible",
            "simulation_response_profile": "high",
            "simulation_missing_percentage": "30",
            "simulation_attention_mode": "multiple_failures",
            "simulation_seed": "999",
        })

        self.assertEqual(response.status_code, 302)
        submission = QuestionnaireSubmission.objects.get(title="Aplicação normal")
        self.assertEqual(submission.sociodemographic_simulation_mode, "normal")
        self.assertEqual(submission.simulation_response_profile, "random")
        self.assertEqual(submission.simulation_missing_percentage, 0)
        self.assertEqual(submission.simulation_attention_mode, "all_correct")
        self.assertIsNone(submission.simulation_seed)
        self.assertFalse(submission.completed)

    def test_legacy_null_mode_defaults_to_ten_percent_in_form(self):
        form = NewQuestionnaireForm(data={
            "title": "Legacy nulls",
            "spectra": [self.spectrum.id],
            "simulation_mode": "simulated_nulls",
            "sociodemographic_simulation_mode": "normal",
            "simulation_response_profile": "random",
            "simulation_missing_percentage": "0",
            "simulation_attention_mode": "all_correct",
            "simulation_seed": "",
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["simulation_missing_percentage"], 10)

    def test_legacy_simulated_post_uses_new_safe_defaults(self):
        form = NewQuestionnaireForm(data={
            "title": "Legacy simulated",
            "spectra": [self.spectrum.id],
            "simulation_mode": "simulated",
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["sociodemographic_simulation_mode"], "normal")
        self.assertEqual(form.cleaned_data["simulation_response_profile"], "random")
        self.assertEqual(form.cleaned_data["simulation_missing_percentage"], 0)
        self.assertEqual(form.cleaned_data["simulation_attention_mode"], "all_correct")

    def test_create_patient_uses_the_same_simulation_controls(self):
        response = self.client.get(reverse("website:create_patient"))
        self.assertContains(response, "Opções de simulação")
        self.assertContains(response, "Indeterminado / resposta normativa em falta")

    def test_invalid_sociodemographic_configuration_rolls_back_cleanly(self):
        QuestionCategory.objects.filter(name="Dados Sociodemográficos").delete()

        response = self.client.post(self.url(), {
            "title": "Configuração indisponível",
            "spectra": [self.spectrum.id],
            "simulation_mode": "simulated",
            "sociodemographic_simulation_mode": "eligible",
            "simulation_response_profile": "random",
            "simulation_missing_percentage": "0",
            "simulation_attention_mode": "all_correct",
            "simulation_seed": "1",
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "O questionário sociodemográfico não está configurado.",
        )
        self.assertFalse(QuestionnaireSubmission.objects.filter(
            title="Configuração indisponível"
        ).exists())
