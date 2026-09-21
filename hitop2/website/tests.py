from unittest.mock import patch
from io import BytesIO
from zipfile import ZipFile

from django.test import TestCase, override_settings

from django.contrib.auth.models import User
from django.urls import reverse

from polls.models import (
    DynamicAnswer,
    DynamicChoice,
    DynamicQuestion,
    Question,
    QuestionCategory,
    QuestionnaireSubmission,
    Scale,
    SociodemographicAnswer,
    Spectra,
    Subfactor,
    UserAnswer,
)

from .models import UserProfile
from .docx_report import _split_chart
from .views import _report_sociodemographics


@override_settings(DEBUG=False)
class ErrorPageTests(TestCase):
    def test_unknown_route_uses_branded_404_page(self):
        response = self.client.get("/pagina-que-nao-existe/")

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Página não encontrada", status_code=404)
        self.assertContains(response, "Ir para o início", status_code=404)

    def test_missing_resource_uses_same_404_page(self):
        professional = User.objects.create_user(username="professional")
        professional.userprofile.user_type = "professional"
        professional.userprofile.is_verified = True
        professional.userprofile.save()
        self.client.force_login(professional)

        response = self.client.get(
            reverse("website:patient_answers", args=[999999]),
        )

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Página não encontrada", status_code=404)


class ProfessionalVerificationTests(TestCase):
    def create_user(self, username, user_type, is_verified=False):
        user = User.objects.create_user(
            username=username,
            password="Uma-palavra-passe-segura-123",
        )
        profile = user.userprofile
        profile.user_type = user_type
        profile.is_verified = is_verified
        profile.save()
        return user

    def test_new_professional_registration_is_pending_and_not_logged_in(self):
        response = self.client.post(
            reverse("website:register"),
            {
                "first_name": "Ana",
                "last_name": "Silva",
                "email": "ana.silva@example.com",
                "password1": "Uma-palavra-passe-segura-123",
                "password2": "Uma-palavra-passe-segura-123",
                "area_formacao": "Psicologia",
                "objetivo_uso": "clinico",
                "cedula_profissional": "12345",
            },
            follow=True,
        )

        user = User.objects.get(username="ana.silva")

        self.assertEqual(user.userprofile.user_type, "professional")
        self.assertFalse(user.userprofile.is_verified)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "aguarda verificação por um administrador")

    def test_duplicate_generated_username_shows_friendly_error_page(self):
        self.create_user("ana.silva", "professional")

        response = self.client.post(
            reverse("website:register"),
            {
                "first_name": "Outra",
                "last_name": "Pessoa",
                "email": "ana.silva@outro-dominio.pt",
                "password1": "Uma-palavra-passe-segura-123",
                "password2": "Uma-palavra-passe-segura-123",
                "area_formacao": "Psicologia",
                "objetivo_uso": "clinico",
                "cedula_profissional": "67890",
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertContains(
            response,
            "Nome de utilizador indisponível",
            status_code=409,
        )
        self.assertEqual(User.objects.filter(username="ana.silva").count(), 1)

    def test_unverified_professional_cannot_log_in(self):
        self.create_user("pending-professional", "professional")

        response = self.client.post(
            reverse("website:home"),
            {
                "username": "pending-professional",
                "password": "Uma-palavra-passe-segura-123",
            },
            follow=True,
        )

        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "aguarda verificação por um administrador")

    def test_unverified_professional_is_logged_out_from_protected_views(self):
        user = self.create_user("pending-professional", "professional")
        self.client.force_login(user)

        response = self.client.get(
            reverse("website:dashboard"),
            follow=True,
        )

        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "aguarda verificação por um administrador")

    def test_verified_professional_can_log_in(self):
        self.create_user(
            "verified-professional",
            "professional",
            is_verified=True,
        )

        response = self.client.post(
            reverse("website:home"),
            {
                "username": "verified-professional",
                "password": "Uma-palavra-passe-segura-123",
            },
        )

        self.assertRedirects(
            response,
            reverse("website:dashboard"),
            fetch_redirect_response=False,
        )
        self.assertIn("_auth_user_id", self.client.session)

    def test_patient_login_is_not_affected_by_verification(self):
        self.create_user("patient", "patient")

        response = self.client.post(
            reverse("website:home"),
            {
                "username": "patient",
                "password": "Uma-palavra-passe-segura-123",
            },
        )

        self.assertRedirects(
            response,
            reverse("polls:questionnaire"),
            fetch_redirect_response=False,
        )

    def test_admin_login_redirects_to_django_admin_dashboard(self):
        admin_user = self.create_user("admin", "admin")
        admin_user.is_staff = True
        admin_user.save()

        response = self.client.post(
            reverse("website:home"),
            {
                "username": "admin",
                "password": "Uma-palavra-passe-segura-123",
            },
        )

        self.assertRedirects(
            response,
            reverse("admin:index"),
            fetch_redirect_response=False,
        )

# Create your tests here.


class ReportSociodemographicsTests(TestCase):
    def test_current_submission_uses_dynamic_values_and_choice_labels(self):
        patient = User.objects.create_user(username="report-patient")
        current = QuestionnaireSubmission.objects.create(user=patient)
        previous = QuestionnaireSubmission.objects.create(user=patient)
        category = QuestionCategory.objects.create(name="Dados Sociodemográficos")

        for key, kind, value, label in (
            ("age", "number", "34", None),
            ("sex", "radio", "2", "Masculino"),
            ("gender", "radio", "3", "Não binário"),
            ("education", "radio", "7", "Ensino Superior concluído"),
        ):
            question = DynamicQuestion.objects.create(
                category=category, question_id=key, label=key,
                question_type=kind,
            )
            if label:
                DynamicChoice.objects.create(
                    question=question, value=value, label=label,
                )
            DynamicAnswer.objects.create(
                user=patient, submission=current, question=question,
                answer_value=value,
            )
            if key == "age":
                DynamicAnswer.objects.create(
                    user=patient, submission=previous, question=question,
                    answer_value="58",
                )

        SociodemographicAnswer.objects.create(
            user=patient, question_id="age", answer_value="60",
            answer_label="60",
        )

        self.assertEqual(_report_sociodemographics(current), {
            "age": "34",
            "sex": "Masculino",
            "gender": "Não binário",
            "education": "Ensino Superior concluído",
        })

    def test_legacy_answers_remain_available(self):
        patient = User.objects.create_user(username="legacy-report-patient")
        submission = QuestionnaireSubmission.objects.create(user=patient)
        SociodemographicAnswer.objects.create(
            user=patient, question_id="sex", answer_value="1",
            answer_label="Feminino",
        )

        self.assertEqual(_report_sociodemographics(submission)["sex"], "Feminino")


class ReportPreviewSpectrumTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.professional = User.objects.create_user(username="report-professional")
        professional_profile = cls.professional.userprofile
        professional_profile.user_type = "professional"
        professional_profile.is_verified = True
        professional_profile.save()

        cls.patient = User.objects.create_user(username="report-spectrum-patient")
        patient_profile = cls.patient.userprofile
        patient_profile.user_type = "patient"
        patient_profile.professional = cls.professional
        patient_profile.save()

        cls.submission = QuestionnaireSubmission.objects.create(user=cls.patient)

        for spectrum_name, scale_name in (
            ("Internalizing", "Distress scale"),
            ("Somatoform", "Somatoform scale"),
        ):
            spectrum = Spectra.objects.create(name=spectrum_name)
            subfactor = Subfactor.objects.create(
                name=f"{spectrum_name} subfactor",
                spectra=spectrum,
            )
            scale = Scale.objects.create(name=scale_name, subfactor=subfactor)
            question = Question.objects.create(
                scale=scale,
                item_code=f"{spectrum_name}-1",
                question_text=f"Question for {spectrum_name}",
            )
            UserAnswer.objects.create(
                user=cls.patient,
                submission=cls.submission,
                question=question,
                answer="2",
            )

        cls.submission.spectra.add(Spectra.objects.get(name="Internalizing"))

    @patch("website.views.calculate_percentile", return_value=50)
    @patch("website.views.calculate_spectrum_percentile", return_value=50)
    def test_detailed_profile_only_contains_submission_spectra(
        self,
        _spectrum_percentile,
        _scale_percentile,
    ):
        self.client.force_login(self.professional)

        response = self.client.get(
            reverse("website:report_preview", args=[self.submission.id]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [section["key"] for section in response.context["detailed_sections"]],
            ["internalizing"],
        )
        self.assertContains(response, "Internalização")
        self.assertNotContains(response, "Somatização")
        self.assertContains(
            response,
            reverse("website:export_report_docx", args=[self.submission.id]),
        )

    @patch("website.views.calculate_percentile", return_value=50)
    @patch("website.views.calculate_spectrum_percentile", return_value=50)
    def test_docx_export_contains_report_and_editable_fields(
        self,
        _spectrum_percentile,
        _scale_percentile,
    ):
        self.client.force_login(self.professional)

        response = self.client.get(
            reverse("website:export_report_docx", args=[self.submission.id]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document",
        )
        self.assertIn("attachment;", response["Content-Disposition"])

        with ZipFile(BytesIO(response.content)) as archive:
            document_xml = archive.read("word/document.xml").decode()
            report_images = [
                name for name in archive.namelist()
                if name.startswith("word/media/")
            ]

        self.assertIn("Internalização", document_xml)
        self.assertNotIn("Somatização", document_xml)
        self.assertIn("Motivo da Avaliação / Encaminhamento", document_xml)
        self.assertIn("Clique aqui e escreva", document_xml)
        self.assertNotIn("POSIÇÃO PERCENTÍLICA", document_xml)
        self.assertGreaterEqual(len(report_images), 3)


class ReportDocxLayoutTests(TestCase):
    def test_long_charts_are_split_only_between_complete_rows(self):
        chart = {
            "height": 55 + 19 * 28,
            "items": [
                {"name": f"Scale {index}", "y": 55 + index * 28}
                for index in range(19)
            ],
        }

        fragments = _split_chart(chart)

        self.assertEqual([len(fragment["items"]) for fragment in fragments], [8, 8, 3])
        self.assertEqual(
            [fragment["show_header"] for fragment in fragments],
            [True, False, False],
        )
        for fragment_index, fragment in enumerate(fragments):
            first_row_y = 55 if fragment_index == 0 else 22
            self.assertEqual(
                [item["y"] for item in fragment["items"]],
                [first_row_y + index * 28 for index in range(len(fragment["items"]))],
            )
            self.assertEqual(
                fragment["height"],
                first_row_y + len(fragment["items"]) * 28,
            )
