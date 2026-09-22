from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from polls.models import (
    Question,
    QuestionnaireSubmission,
    Scale,
    Spectra,
    Subfactor,
    UserAnswer,
)


class ProfessionalTestEnvironmentMixin:
    password = "Uma-palavra-passe-segura-123"

    @classmethod
    def create_role_user(cls, username, user_type, *, verified=False):
        user = User.objects.create_user(
            username=username,
            password=cls.password,
        )
        profile = user.userprofile
        profile.user_type = user_type
        profile.is_verified = verified
        profile.save(update_fields=["user_type", "is_verified"])
        return user

    @classmethod
    def create_test_patient(cls, username, owner):
        patient = User.objects.create_user(username=username)
        profile = patient.userprofile
        profile.user_type = "patient"
        profile.is_test_data = True
        profile.professional = None
        profile.test_environment_owner = owner
        profile.save(update_fields=[
            "user_type",
            "is_test_data",
            "professional",
            "test_environment_owner",
        ])
        return patient

    @classmethod
    def create_clinical_patient(cls, username, professional):
        patient = User.objects.create_user(username=username)
        profile = patient.userprofile
        profile.user_type = "patient"
        profile.professional = professional
        profile.save(update_fields=["user_type", "professional"])
        return patient

    @classmethod
    def setUpTestData(cls):
        cls.administrator = cls.create_role_user(
            "test-environment-admin",
            "admin",
        )
        cls.other_administrator = cls.create_role_user(
            "other-test-environment-admin",
            "admin",
        )
        cls.professional = cls.create_role_user(
            "test-environment-professional",
            "professional",
            verified=True,
        )
        cls.patient_user = cls.create_role_user(
            "standalone-test-environment-patient",
            "patient",
        )
        cls.clinical_patient = cls.create_clinical_patient(
            "clinical-patient",
            cls.professional,
        )
        cls.test_patient = cls.create_test_patient(
            "administrator-test-patient",
            cls.administrator,
        )
        cls.other_test_patient = cls.create_test_patient(
            "other-administrator-test-patient",
            cls.other_administrator,
        )

        cls.spectrum = Spectra.objects.create(name="Internalizing")
        cls.subfactor = Subfactor.objects.create(
            name="Test environment subfactor",
            spectra=cls.spectrum,
        )
        cls.scale = Scale.objects.create(
            name="Test environment scale",
            subfactor=cls.subfactor,
        )
        cls.question = Question.objects.create(
            scale=cls.scale,
            item_code="ADMIN-TEST-1",
            question_text="Test environment question",
        )

        cls.test_submission = QuestionnaireSubmission.objects.create(
            user=cls.test_patient,
            title="Administrator test submission",
            completed=True,
            is_open=False,
            simulation_mode="simulated",
            is_test_data=True,
        )
        cls.test_submission.spectra.add(cls.spectrum)
        UserAnswer.objects.create(
            user=cls.test_patient,
            submission=cls.test_submission,
            question=cls.question,
            answer="2",
        )


class ProfessionalTestEnvironmentPermissionTests(
    ProfessionalTestEnvironmentMixin,
    TestCase,
):
    def test_administrator_can_access_professional_test_environment(self):
        self.client.force_login(self.administrator)

        response = self.client.get(
            reverse("administration:professional_test_environment")
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "website/dashboard.html")
        self.assertContains(response, "Ambiente de Teste Profissional")

    def test_professional_cannot_access_professional_test_environment(self):
        self.client.force_login(self.professional)

        response = self.client.get(
            reverse("administration:professional_test_environment")
        )

        self.assertEqual(response.status_code, 403)

    def test_patient_cannot_access_professional_test_environment(self):
        self.client.force_login(self.patient_user)

        response = self.client.get(
            reverse("administration:professional_test_environment")
        )

        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_cannot_access_professional_test_environment(self):
        response = self.client.get(
            reverse("administration:professional_test_environment")
        )

        self.assertRedirects(response, reverse("website:home"))

    def test_all_test_environment_detail_endpoints_reject_non_admin_users(self):
        get_urls = (
            reverse("administration:test_create_patient"),
            reverse("administration:test_archived_patients"),
            reverse(
                "administration:test_patient_submissions",
                args=[self.test_patient.id],
            ),
            reverse(
                "administration:test_new_questionnaire",
                args=[self.test_patient.userprofile.id],
            ),
            reverse(
                "administration:test_patient_answers",
                args=[self.test_submission.id],
            ),
            reverse(
                "administration:test_report_preview",
                args=[self.test_submission.id],
            ),
            reverse(
                "administration:test_export_report_docx",
                args=[self.test_submission.id],
            ),
        )
        post_urls = (
            reverse(
                "administration:test_archive_patient",
                args=[self.test_patient.userprofile.id],
            ),
            reverse(
                "administration:test_restore_patient",
                args=[self.test_patient.userprofile.id],
            ),
        )

        for user in (self.professional, self.patient_user):
            self.client.force_login(user)
            for url in get_urls:
                with self.subTest(user=user.username, method="GET", url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
            for url in post_urls:
                with self.subTest(user=user.username, method="POST", url=url):
                    self.assertEqual(self.client.post(url).status_code, 403)

    def test_test_environment_link_is_not_shown_to_professional_or_patient(self):
        self.client.force_login(self.professional)
        professional_response = self.client.get(reverse("website:dashboard"))
        self.assertNotContains(
            professional_response,
            "Ambiente de Teste Profissional",
        )

        self.client.force_login(self.patient_user)
        patient_response = self.client.get(reverse("polls:thank_you"))
        self.assertNotContains(patient_response, "Ambiente de Teste Profissional")


class ProfessionalSimulationBoundaryTests(
    ProfessionalTestEnvironmentMixin,
    TestCase,
):
    def setUp(self):
        self.client.force_login(self.professional)

    def test_professional_forms_do_not_show_simulation_controls(self):
        create_response = self.client.get(reverse("website:create_patient"))
        questionnaire_response = self.client.get(
            reverse(
                "website:new_questionnaire",
                args=[self.clinical_patient.userprofile.id],
            )
        )

        for response in (create_response, questionnaire_response):
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "Opções de simulação")
            self.assertNotContains(response, 'name="simulation_mode"')

    def test_professional_manual_simulation_post_is_safely_ignored(self):
        response = self.client.post(
            reverse(
                "website:new_questionnaire",
                args=[self.clinical_patient.userprofile.id],
            ),
            {
                "title": "Attempted manual simulation",
                "spectra": [self.spectrum.id],
                "simulation_mode": "simulated",
                "sociodemographic_simulation_mode": "eligible",
                "simulation_response_profile": "high",
                "simulation_missing_percentage": "30",
                "simulation_attention_mode": "multiple_failures",
                "simulation_seed": "9876",
                "is_test_data": "true",
            },
        )

        self.assertRedirects(
            response,
            reverse("website:dashboard"),
            fetch_redirect_response=False,
        )
        submission = QuestionnaireSubmission.objects.get(
            title="Attempted manual simulation"
        )
        self.assertEqual(submission.simulation_mode, "normal")
        self.assertEqual(submission.sociodemographic_simulation_mode, "normal")
        self.assertEqual(submission.simulation_response_profile, "random")
        self.assertEqual(submission.simulation_missing_percentage, 0)
        self.assertEqual(submission.simulation_attention_mode, "all_correct")
        self.assertIsNone(submission.simulation_seed)
        self.assertFalse(submission.is_test_data)
        self.assertFalse(submission.completed)
        self.assertFalse(UserAnswer.objects.filter(submission=submission).exists())

    def test_legacy_simulated_submission_is_excluded_from_clinical_views(self):
        legacy = QuestionnaireSubmission.objects.create(
            user=self.clinical_patient,
            title="Legacy simulated clinical record",
            simulation_mode="simulated",
            is_test_data=False,
        )
        QuestionnaireSubmission.objects.create(
            user=self.clinical_patient,
            title="Real clinical record",
            simulation_mode="normal",
            is_test_data=False,
        )

        dashboard = self.client.get(reverse("website:dashboard"))
        submissions = self.client.get(reverse(
            "website:patient_submissions",
            args=[self.clinical_patient.id],
        ))
        legacy_report = self.client.get(reverse(
            "website:report_preview",
            args=[legacy.id],
        ))

        patient_card = next(
            card for card in dashboard.context["patients"]
            if card["profile"].pk == self.clinical_patient.userprofile.pk
        )
        self.assertEqual(patient_card["submission_count"], 1)
        self.assertContains(submissions, "Real clinical record")
        self.assertNotContains(submissions, "Legacy simulated clinical record")
        self.assertEqual(legacy_report.status_code, 404)


class ProfessionalTestEnvironmentWorkflowTests(
    ProfessionalTestEnvironmentMixin,
    TestCase,
):
    def setUp(self):
        self.client.force_login(self.administrator)

    def test_administrator_can_configure_simulation_without_impersonation(self):
        url = reverse("administration:test_create_patient")
        get_response = self.client.get(url)

        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "Opções de simulação")
        self.assertContains(get_response, 'name="simulation_mode"')

        response = self.client.post(url, {
            "title": "Configured administrator simulation",
            "spectra": [self.spectrum.id],
            "simulation_mode": "simulated",
            "sociodemographic_simulation_mode": "normal",
            "simulation_response_profile": "high",
            "simulation_missing_percentage": "10",
            "simulation_attention_mode": "one_failure",
            "simulation_seed": "2468",
        })

        submission = QuestionnaireSubmission.objects.get(
            title="Configured administrator simulation"
        )
        profile = submission.user.userprofile
        self.assertRedirects(
            response,
            reverse(
                "administration:test_patient_submissions",
                args=[submission.user_id],
            ),
            fetch_redirect_response=False,
        )
        self.assertTrue(profile.is_test_data)
        self.assertIsNone(profile.professional)
        self.assertEqual(profile.test_environment_owner, self.administrator)
        self.assertTrue(submission.is_test_data)
        self.assertEqual(submission.simulation_mode, "simulated")
        self.assertEqual(submission.simulation_response_profile, "high")
        self.assertEqual(submission.simulation_missing_percentage, 10)
        self.assertEqual(submission.simulation_attention_mode, "one_failure")
        self.assertEqual(submission.simulation_seed, 2468)
        self.assertTrue(submission.completed)
        self.assertTrue(UserAnswer.objects.filter(submission=submission).exists())
        self.assertEqual(
            self.client.session.get("_auth_user_id"),
            str(self.administrator.pk),
        )

    def test_real_and_test_patients_are_isolated_between_dashboards(self):
        professional_dashboard = self.client.get(
            reverse("administration:professional_test_environment")
        )
        self.assertContains(professional_dashboard, self.test_patient.username)
        self.assertNotContains(
            professional_dashboard,
            self.clinical_patient.username,
        )
        self.assertNotContains(
            professional_dashboard,
            self.other_test_patient.username,
        )

        self.client.force_login(self.professional)
        clinical_dashboard = self.client.get(reverse("website:dashboard"))
        self.assertContains(clinical_dashboard, self.clinical_patient.username)
        self.assertNotContains(clinical_dashboard, self.test_patient.username)

    def test_other_administrator_cannot_open_or_mutate_owned_test_data(self):
        self.client.force_login(self.other_administrator)

        responses = (
            self.client.get(reverse(
                "administration:test_patient_submissions",
                args=[self.test_patient.id],
            )),
            self.client.get(reverse(
                "administration:test_new_questionnaire",
                args=[self.test_patient.userprofile.id],
            )),
            self.client.get(reverse(
                "administration:test_patient_answers",
                args=[self.test_submission.id],
            )),
            self.client.get(reverse(
                "administration:test_report_preview",
                args=[self.test_submission.id],
            )),
            self.client.post(reverse(
                "administration:test_archive_patient",
                args=[self.test_patient.userprofile.id],
            )),
        )

        for response in responses:
            self.assertEqual(response.status_code, 404)
        self.test_patient.userprofile.refresh_from_db()
        self.assertIsNone(self.test_patient.userprofile.archived_at)

    def test_test_patient_can_be_archived_and_restored(self):
        profile = self.test_patient.userprofile

        archive_response = self.client.post(reverse(
            "administration:test_archive_patient",
            args=[profile.id],
        ))
        self.assertRedirects(
            archive_response,
            reverse("administration:professional_test_environment"),
        )
        profile.refresh_from_db()
        self.assertIsNotNone(profile.archived_at)
        self.assertNotContains(
            self.client.get(reverse("administration:professional_test_environment")),
            self.test_patient.username,
        )
        archived_response = self.client.get(
            reverse("administration:test_archived_patients")
        )
        self.assertContains(archived_response, self.test_patient.username)
        self.assertNotContains(archived_response, "Eliminar permanentemente")

        restore_response = self.client.post(reverse(
            "administration:test_restore_patient",
            args=[profile.id],
        ))
        self.assertRedirects(
            restore_response,
            reverse("administration:test_archived_patients"),
        )
        profile.refresh_from_db()
        self.assertIsNone(profile.archived_at)
        self.assertContains(
            self.client.get(reverse("administration:professional_test_environment")),
            self.test_patient.username,
        )

    def test_test_archive_endpoint_rejects_real_patient(self):
        response = self.client.post(reverse(
            "administration:test_archive_patient",
            args=[self.clinical_patient.userprofile.id],
        ))

        self.assertEqual(response.status_code, 404)
        self.clinical_patient.userprofile.refresh_from_db()
        self.assertIsNone(self.clinical_patient.userprofile.archived_at)

    def test_test_submission_page_shows_computed_normative_state(self):
        response = self.client.get(reverse(
            "administration:test_patient_submissions",
            args=[self.test_patient.id],
        ))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Elegibilidade normativa:")
        self.assertContains(response, "Indeterminada")


class ProfessionalTestEnvironmentReportTests(
    ProfessionalTestEnvironmentMixin,
    TestCase,
):
    def setUp(self):
        self.client.force_login(self.administrator)

    @patch("website.views.calculate_percentile", return_value=50)
    @patch("website.views.calculate_spectrum_percentile", return_value=50)
    def test_test_report_preview_has_permanent_simulation_indication(
        self,
        _spectrum_percentile,
        _scale_percentile,
    ):
        response = self.client.get(reverse(
            "administration:test_report_preview",
            args=[self.test_submission.id],
        ))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SIMULAÇÃO / TESTE")
        self.assertContains(response, "não corresponde a dados clínicos reais")
        self.assertContains(
            response,
            reverse(
                "administration:test_export_report_docx",
                args=[self.test_submission.id],
            ),
        )

    @patch("website.views.calculate_percentile", return_value=50)
    @patch("website.views.calculate_spectrum_percentile", return_value=50)
    def test_test_docx_report_has_simulation_banner(
        self,
        _spectrum_percentile,
        _scale_percentile,
    ):
        response = self.client.get(reverse(
            "administration:test_export_report_docx",
            args=[self.test_submission.id],
        ))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document",
        )
        with ZipFile(BytesIO(response.content)) as archive:
            document_xml = archive.read("word/document.xml").decode()
        self.assertIn("SIMULAÇÃO / TESTE", document_xml)
