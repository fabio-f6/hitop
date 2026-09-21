from unittest.mock import patch
from io import BytesIO
from zipfile import ZipFile

from django.test import TestCase, override_settings

from django.contrib.auth.models import User
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
    QuestionnaireSubmission,
    Scale,
    SociodemographicAnswer,
    Spectra,
    Subfactor,
    UserAnswer,
)

from .models import UserProfile
from .patient_deletion import permanently_delete_patient
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


class PatientArchivingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.professional = User.objects.create_user(
            username="professional-archive",
            password="test-password",
        )
        cls.professional.userprofile.user_type = "professional"
        cls.professional.userprofile.is_verified = True
        cls.professional.userprofile.save()

        cls.other_professional = User.objects.create_user(
            username="other-professional",
            password="test-password",
        )
        cls.other_professional.userprofile.user_type = "professional"
        cls.other_professional.userprofile.is_verified = True
        cls.other_professional.userprofile.save()

        cls.patient = User.objects.create_user(username="patient-to-archive")
        cls.patient.userprofile.user_type = "patient"
        cls.patient.userprofile.professional = cls.professional
        cls.patient.userprofile.save()

    def setUp(self):
        self.client.force_login(self.professional)

    def test_archive_patient_hides_it_from_dashboard_and_lists_it_as_archived(self):
        response = self.client.post(
            reverse("website:archive_patient", args=[self.patient.userprofile.id]),
        )

        self.assertRedirects(response, reverse("website:dashboard"))
        self.patient.userprofile.refresh_from_db()
        self.assertIsNotNone(self.patient.userprofile.archived_at)

        dashboard = self.client.get(reverse("website:dashboard"))
        self.assertNotContains(dashboard, self.patient.username)
        self.assertContains(dashboard, "Pacientes arquivados [1]")

        archived = self.client.get(reverse("website:archived_patients"))
        self.assertContains(archived, self.patient.username)

    def test_restore_patient_returns_it_to_dashboard(self):
        self.patient.userprofile.archived_at = timezone.now()
        self.patient.userprofile.save(update_fields=["archived_at"])

        response = self.client.post(
            reverse("website:restore_patient", args=[self.patient.userprofile.id]),
        )

        self.assertRedirects(response, reverse("website:archived_patients"))
        self.patient.userprofile.refresh_from_db()
        self.assertIsNone(self.patient.userprofile.archived_at)
        self.assertContains(
            self.client.get(reverse("website:dashboard")),
            self.patient.username,
        )
        self.assertNotContains(
            self.client.get(reverse("website:archived_patients")),
            self.patient.username,
        )

    def test_professional_cannot_archive_or_restore_another_professionals_patient(self):
        self.client.force_login(self.other_professional)
        profile = self.patient.userprofile

        archive_response = self.client.post(
            reverse("website:archive_patient", args=[profile.id]),
        )
        self.assertEqual(archive_response.status_code, 404)
        profile.refresh_from_db()
        self.assertIsNone(profile.archived_at)

        profile.archived_at = timezone.now()
        profile.save(update_fields=["archived_at"])
        restore_response = self.client.post(
            reverse("website:restore_patient", args=[profile.id]),
        )
        self.assertEqual(restore_response.status_code, 404)
        profile.refresh_from_db()
        self.assertIsNotNone(profile.archived_at)

    def test_archive_and_restore_only_accept_post(self):
        archive_response = self.client.get(
            reverse("website:archive_patient", args=[self.patient.userprofile.id]),
        )
        restore_response = self.client.get(
            reverse("website:restore_patient", args=[self.patient.userprofile.id]),
        )

        self.assertEqual(archive_response.status_code, 405)
        self.assertEqual(restore_response.status_code, 405)

    def test_archiving_does_not_delete_submissions_or_answers(self):
        submission = QuestionnaireSubmission.objects.create(user=self.patient)
        answer = SociodemographicAnswer.objects.create(
            user=self.patient,
            question_id="age",
            answer_value="35",
            answer_label="35",
        )

        self.client.post(
            reverse("website:archive_patient", args=[self.patient.userprofile.id]),
        )

        self.assertTrue(
            QuestionnaireSubmission.objects.filter(id=submission.id).exists(),
        )
        self.assertTrue(
            SociodemographicAnswer.objects.filter(id=answer.id).exists(),
        )

    def test_active_and_archived_patient_lists_are_paginated(self):
        for index in range(11):
            patient = User.objects.create_user(username=f"active-{index:02d}")
            patient.userprofile.user_type = "patient"
            patient.userprofile.professional = self.professional
            patient.userprofile.save()

        for index in range(11):
            patient = User.objects.create_user(username=f"archived-{index:02d}")
            patient.userprofile.user_type = "patient"
            patient.userprofile.professional = self.professional
            patient.userprofile.archived_at = timezone.now()
            patient.userprofile.save()

        dashboard = self.client.get(reverse("website:dashboard"))
        archived = self.client.get(reverse("website:archived_patients"))

        self.assertEqual(dashboard.context["patient_page"].paginator.per_page, 10)
        self.assertEqual(archived.context["patient_page"].paginator.per_page, 10)
        self.assertContains(dashboard, "Página 1 de 2")
        self.assertContains(archived, "Página 1 de 2")


class PermanentPatientDeletionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.professional = User.objects.create_user(username="deletion-professional")
        cls.professional.userprofile.user_type = "professional"
        cls.professional.userprofile.is_verified = True
        cls.professional.userprofile.save()

        cls.other_professional = User.objects.create_user(username="deletion-other")
        cls.other_professional.userprofile.user_type = "professional"
        cls.other_professional.userprofile.is_verified = True
        cls.other_professional.userprofile.save()

        cls.spectrum = Spectra.objects.create(name="Deletion spectrum")
        cls.subfactor = Subfactor.objects.create(name="Deletion subfactor", spectra=cls.spectrum)
        cls.scale = Scale.objects.create(name="Deletion scale", subfactor=cls.subfactor)
        cls.question = Question.objects.create(
            scale=cls.scale,
            item_code="DELETE-1",
            question_text="Deletion question",
        )
        cls.category = QuestionCategory.objects.create(name="Deletion demographics")
        cls.dynamic_question = DynamicQuestion.objects.create(
            category=cls.category,
            question_id="deletion_age",
            label="Age",
            question_type="number",
        )

    def setUp(self):
        self.client.force_login(self.professional)

    def make_patient(self, username, *, archived=True, professional=None):
        patient = User.objects.create_user(username=username)
        profile = patient.userprofile
        profile.user_type = "patient"
        profile.professional = professional or self.professional
        profile.archived_at = timezone.now() if archived else None
        profile.save()
        return patient

    def make_submission(self, patient, status):
        return QuestionnaireSubmission.objects.create(
            user=patient,
            normative_status=status,
        )

    def delete_url(self, patient):
        return reverse(
            "website:permanently_delete_patient",
            args=[patient.userprofile.id],
        )

    def test_active_patient_cannot_be_deleted(self):
        patient = self.make_patient("active-delete", archived=False)
        url = self.delete_url(patient)

        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(User.objects.filter(pk=patient.pk).exists())

    def test_confirmation_is_explicit_and_only_post_deletes(self):
        patient = self.make_patient("confirmation-delete")
        self.make_submission(patient, QuestionnaireSubmission.NormativeStatus.INELIGIBLE)

        response = self.client.get(self.delete_url(patient))

        self.assertContains(
            response,
            "Esta ação eliminará permanentemente os dados clínicos deste paciente e não pode ser revertida.",
        )
        self.assertTrue(User.objects.filter(pk=patient.pk).exists())

    def test_archived_patient_with_only_ineligible_submissions_can_be_deleted(self):
        patient = self.make_patient("ineligible-delete")
        self.make_submission(patient, QuestionnaireSubmission.NormativeStatus.INELIGIBLE)

        self.client.post(self.delete_url(patient))

        self.assertFalse(User.objects.filter(pk=patient.pk).exists())

    def test_archived_patient_with_only_exported_submissions_can_be_deleted(self):
        patient = self.make_patient("exported-delete")
        self.make_submission(patient, QuestionnaireSubmission.NormativeStatus.EXPORTED)

        self.client.post(self.delete_url(patient))

        self.assertFalse(User.objects.filter(pk=patient.pk).exists())

    def test_exported_and_ineligible_mix_can_be_deleted(self):
        patient = self.make_patient("mixed-delete")
        self.make_submission(patient, QuestionnaireSubmission.NormativeStatus.EXPORTED)
        self.make_submission(patient, QuestionnaireSubmission.NormativeStatus.INELIGIBLE)

        self.client.post(self.delete_url(patient))

        self.assertFalse(User.objects.filter(pk=patient.pk).exists())

    def test_one_pending_submission_blocks_the_whole_deletion(self):
        patient = self.make_patient("pending-delete")
        exported = self.make_submission(
            patient, QuestionnaireSubmission.NormativeStatus.EXPORTED,
        )
        pending = self.make_submission(
            patient, QuestionnaireSubmission.NormativeStatus.PENDING,
        )

        response = self.client.post(self.delete_url(patient), follow=True)

        self.assertContains(
            response,
            "existem aplicações cujo estado relativamente à base normativa ainda não foi determinado",
        )
        self.assertTrue(User.objects.filter(pk=patient.pk).exists())
        self.assertTrue(QuestionnaireSubmission.objects.filter(pk=exported.pk).exists())
        self.assertTrue(QuestionnaireSubmission.objects.filter(pk=pending.pk).exists())

    def test_professional_cannot_delete_another_professionals_patient(self):
        patient = self.make_patient(
            "other-owned-delete", professional=self.other_professional,
        )

        response = self.client.post(self.delete_url(patient))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(User.objects.filter(pk=patient.pk).exists())

    def test_clinical_answers_and_sociodemographics_are_deleted(self):
        patient = self.make_patient("clinical-data-delete")
        submission = self.make_submission(
            patient, QuestionnaireSubmission.NormativeStatus.INELIGIBLE,
        )
        user_answer = UserAnswer.objects.create(
            user=patient, submission=submission, question=self.question, answer="1",
        )
        dynamic_answer = DynamicAnswer.objects.create(
            user=patient,
            submission=submission,
            question=self.dynamic_question,
            answer_value="42",
        )
        legacy_socio = SociodemographicAnswer.objects.create(
            user=patient,
            question_id="age",
            answer_value="42",
            answer_label="42",
        )

        self.client.post(self.delete_url(patient))

        self.assertFalse(QuestionnaireSubmission.objects.filter(pk=submission.pk).exists())
        self.assertFalse(UserAnswer.objects.filter(pk=user_answer.pk).exists())
        self.assertFalse(DynamicAnswer.objects.filter(pk=dynamic_answer.pk).exists())
        self.assertFalse(SociodemographicAnswer.objects.filter(pk=legacy_socio.pk).exists())

    def test_exported_normative_data_remains_after_clinical_deletion(self):
        patient = self.make_patient("normative-preserved-delete")
        self.make_submission(patient, QuestionnaireSubmission.NormativeStatus.EXPORTED)
        participant = NormativeParticipant.objects.create(age=42, sex="Feminino")
        answer = NormativeAnswer.objects.create(
            participant=participant, question=self.question, answer="1",
        )
        version = NormativeDatasetVersion.objects.create(name="deletion-test-v1")
        NormativeDatasetMembership.objects.create(
            version=version,
            participant=participant,
        )
        scale_score = NormativeScaleScore.objects.create(
            version=version,
            participant=participant,
            scale=self.scale,
            raw_score=1,
        )
        spectrum_score = NormativeSpectrumScore.objects.create(
            version=version,
            participant=participant,
            spectrum=self.spectrum,
            raw_score=1,
        )

        self.client.post(self.delete_url(patient))

        self.assertTrue(NormativeParticipant.objects.filter(pk=participant.pk).exists())
        self.assertTrue(NormativeAnswer.objects.filter(pk=answer.pk).exists())
        self.assertTrue(NormativeScaleScore.objects.filter(pk=scale_score.pk).exists())
        self.assertTrue(NormativeSpectrumScore.objects.filter(pk=spectrum_score.pk).exists())

    def test_failure_rolls_back_all_clinical_deletions(self):
        patient = self.make_patient("rollback-delete")
        submission = self.make_submission(
            patient, QuestionnaireSubmission.NormativeStatus.INELIGIBLE,
        )
        answer = UserAnswer.objects.create(
            user=patient, submission=submission, question=self.question, answer="1",
        )

        with patch.object(User, "delete", side_effect=RuntimeError("forced failure")):
            with self.assertRaises(RuntimeError):
                permanently_delete_patient(
                    patient_id=patient.userprofile.id,
                    professional=self.professional,
                )

        self.assertTrue(User.objects.filter(pk=patient.pk).exists())
        self.assertTrue(QuestionnaireSubmission.objects.filter(pk=submission.pk).exists())
        self.assertTrue(UserAnswer.objects.filter(pk=answer.pk).exists())


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
