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
    UserAnswer,
)

from .forms import NewQuestionnaireForm


class SimulationInterfaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_sociodemographic", verbosity=0)

        cls.administrator = User.objects.create_user(
            username="simulation-administrator",
            password="test-password",
        )
        cls.administrator.userprofile.user_type = "admin"
        cls.administrator.userprofile.save(update_fields=["user_type"])

        cls.professional = User.objects.create_user(
            username="simulation-professional",
            password="test-password",
        )
        cls.professional.userprofile.user_type = "professional"
        cls.professional.userprofile.is_verified = True
        cls.professional.userprofile.save(
            update_fields=["user_type", "is_verified"]
        )

        cls.patient = User.objects.create_user(username="simulation-ui-patient")
        cls.patient.userprofile.user_type = "patient"
        cls.patient.userprofile.professional = cls.professional
        cls.patient.userprofile.save(
            update_fields=["user_type", "professional"]
        )

        cls.test_patient = User.objects.create_user(
            username="simulation-ui-test-patient"
        )
        cls.test_patient.userprofile.user_type = "patient"
        cls.test_patient.userprofile.is_test_data = True
        cls.test_patient.userprofile.professional = None
        cls.test_patient.userprofile.test_environment_owner = cls.administrator
        cls.test_patient.userprofile.save(update_fields=[
            "user_type",
            "is_test_data",
            "professional",
            "test_environment_owner",
        ])

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

    def professional_url(self):
        return reverse(
            "website:new_questionnaire",
            args=[self.patient.userprofile.id],
        )

    def administrator_url(self):
        return reverse(
            "administration:test_new_questionnaire",
            args=[self.test_patient.userprofile.id],
        )

    def simulation_post_data(self, **overrides):
        data = {
            "title": "Simulação configurada",
            "spectra": [self.spectrum.id],
            "simulation_mode": "simulated",
            "sociodemographic_simulation_mode": "ineligible_mental_health",
            "simulation_response_profile": "high",
            "simulation_missing_percentage": "30",
            "simulation_attention_mode": "one_failure",
            "simulation_seed": "2468",
        }
        data.update(overrides)
        return data

    def test_professional_does_not_see_simulation_options(self):
        self.client.force_login(self.professional)

        questionnaire_response = self.client.get(self.professional_url())
        create_patient_response = self.client.get(reverse("website:create_patient"))

        for response in (questionnaire_response, create_patient_response):
            with self.subTest(template=response.templates[0].name):
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, "Opções de simulação")
                self.assertNotContains(response, 'name="simulation_mode"')
                self.assertNotContains(response, "Elegível para base normativa")

    def test_professional_manual_simulation_post_is_forced_to_real_defaults(self):
        self.client.force_login(self.professional)

        response = self.client.post(
            self.professional_url(),
            self.simulation_post_data(title="POST adulterado"),
        )

        self.assertRedirects(
            response,
            reverse("website:dashboard"),
            fetch_redirect_response=False,
        )
        submission = QuestionnaireSubmission.objects.get(title="POST adulterado")
        self.assertFalse(submission.is_test_data)
        self.assertEqual(submission.simulation_mode, "normal")
        self.assertEqual(submission.sociodemographic_simulation_mode, "normal")
        self.assertEqual(submission.simulation_response_profile, "random")
        self.assertEqual(submission.simulation_missing_percentage, 0)
        self.assertEqual(submission.simulation_attention_mode, "all_correct")
        self.assertIsNone(submission.simulation_seed)
        self.assertFalse(submission.completed)
        self.assertFalse(UserAnswer.objects.filter(submission=submission).exists())

    def test_professional_create_patient_post_cannot_enable_simulation(self):
        self.client.force_login(self.professional)
        url = reverse("website:create_patient")
        self.client.get(url)

        response = self.client.post(
            url,
            self.simulation_post_data(title="Novo paciente clínico"),
        )

        self.assertEqual(response.status_code, 302)
        submission = QuestionnaireSubmission.objects.get(
            title="Novo paciente clínico"
        )
        profile = submission.user.userprofile
        self.assertFalse(profile.is_test_data)
        self.assertEqual(profile.professional, self.professional)
        self.assertIsNone(profile.test_environment_owner)
        self.assertFalse(submission.is_test_data)
        self.assertEqual(submission.simulation_mode, "normal")
        self.assertFalse(submission.completed)

    def test_administrator_sees_advanced_options_only_in_test_environment(self):
        self.client.force_login(self.administrator)

        response = self.client.get(self.administrator_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ambiente de Teste Profissional")
        self.assertContains(response, "Opções de simulação")
        self.assertContains(response, "Elegível para base normativa")
        self.assertContains(response, "Múltiplas falhas")
        self.assertContains(response, 'name="simulation_mode"')
        self.assertRegex(
            response.content.decode(),
            r"data-simulation-options\s+hidden",
        )

    def test_administrator_selected_simulation_values_are_saved(self):
        self.client.force_login(self.administrator)

        response = self.client.post(
            self.administrator_url(),
            self.simulation_post_data(),
        )

        self.assertRedirects(
            response,
            reverse("administration:professional_test_environment"),
            fetch_redirect_response=False,
        )
        submission = QuestionnaireSubmission.objects.get(
            title="Simulação configurada"
        )
        self.assertTrue(submission.is_test_data)
        self.assertEqual(submission.simulation_mode, "simulated")
        self.assertEqual(
            submission.sociodemographic_simulation_mode,
            "ineligible_mental_health",
        )
        self.assertEqual(submission.simulation_response_profile, "high")
        self.assertEqual(submission.simulation_missing_percentage, 30)
        self.assertEqual(submission.simulation_attention_mode, "one_failure")
        self.assertEqual(submission.simulation_seed, 2468)
        self.assertTrue(submission.completed)

    def test_test_environment_normal_application_forces_safe_defaults(self):
        self.client.force_login(self.administrator)

        response = self.client.post(
            self.administrator_url(),
            self.simulation_post_data(
                title="Aplicação de teste manual",
                simulation_mode="normal",
                sociodemographic_simulation_mode="eligible",
                simulation_attention_mode="multiple_failures",
                simulation_seed="999",
            ),
        )

        self.assertEqual(response.status_code, 302)
        submission = QuestionnaireSubmission.objects.get(
            title="Aplicação de teste manual"
        )
        self.assertTrue(submission.is_test_data)
        self.assertEqual(submission.sociodemographic_simulation_mode, "normal")
        self.assertEqual(submission.simulation_response_profile, "random")
        self.assertEqual(submission.simulation_missing_percentage, 0)
        self.assertEqual(submission.simulation_attention_mode, "all_correct")
        self.assertIsNone(submission.simulation_seed)
        self.assertFalse(submission.completed)

    def test_legacy_null_mode_defaults_to_ten_percent_in_enabled_form(self):
        form = NewQuestionnaireForm(
            data={
                "title": "Legacy nulls",
                "spectra": [self.spectrum.id],
                "simulation_mode": "simulated_nulls",
                "sociodemographic_simulation_mode": "normal",
                "simulation_response_profile": "random",
                "simulation_missing_percentage": "0",
                "simulation_attention_mode": "all_correct",
                "simulation_seed": "",
            },
            allow_simulation=True,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["simulation_missing_percentage"], 10)

    def test_legacy_simulated_post_uses_safe_defaults_in_enabled_form(self):
        form = NewQuestionnaireForm(
            data={
                "title": "Legacy simulated",
                "spectra": [self.spectrum.id],
                "simulation_mode": "simulated",
            },
            allow_simulation=True,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["sociodemographic_simulation_mode"], "normal")
        self.assertEqual(form.cleaned_data["simulation_response_profile"], "random")
        self.assertEqual(form.cleaned_data["simulation_missing_percentage"], 0)
        self.assertEqual(form.cleaned_data["simulation_attention_mode"], "all_correct")

    def test_administrator_create_patient_uses_simulation_controls(self):
        self.client.force_login(self.administrator)

        response = self.client.get(reverse("administration:test_create_patient"))

        self.assertContains(response, "Opções de simulação")
        self.assertContains(response, "Indeterminado / resposta normativa em falta")

    def test_invalid_sociodemographic_configuration_rolls_back_admin_flow(self):
        self.client.force_login(self.administrator)
        QuestionCategory.objects.filter(name="Dados Sociodemográficos").delete()

        response = self.client.post(
            self.administrator_url(),
            self.simulation_post_data(
                title="Configuração indisponível",
                sociodemographic_simulation_mode="eligible",
                simulation_response_profile="random",
                simulation_missing_percentage="0",
                simulation_attention_mode="all_correct",
                simulation_seed="1",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "O questionário sociodemográfico não está configurado.",
        )
        self.assertFalse(
            QuestionnaireSubmission.objects.filter(
                title="Configuração indisponível"
            ).exists()
        )
