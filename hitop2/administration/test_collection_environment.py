from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from polls.models import (
    DynamicQuestion,
    NormativeDatasetVersion,
    QuestionnaireCollection,
    QuestionnaireSubmission,
    Question,
    Scale,
    Spectra,
    Subfactor,
)
from website.models import UserProfile
from administration.professional_test_cleanup import clear_professional_test_environment
from polls.normative_test import clear_normative_test_environment
from polls.normative_export import TestSubmissionExportBlocked, export_submission_to_normative


class TestCollectionEnvironmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="collection-test-admin")
        cls.admin.userprofile.user_type = "admin"
        cls.admin.userprofile.save(update_fields=["user_type"])
        cls.other_admin = User.objects.create_user(username="other-collection-admin")
        cls.other_admin.userprofile.user_type = "admin"
        cls.other_admin.userprofile.save(update_fields=["user_type"])
        cls.professional = User.objects.create_user(username="collection-professional")
        cls.professional.userprofile.user_type = "professional"
        cls.professional.userprofile.is_verified = True
        cls.professional.userprofile.is_researcher = True
        cls.professional.userprofile.save()

        cls.spectrum = Spectra.objects.create(name="Test collection spectrum")
        subfactor = Subfactor.objects.create(name="Test subfactor", spectra=cls.spectrum)
        scale = Scale.objects.create(name="Test scale", subfactor=subfactor)
        Question.objects.create(
            scale=scale, item_code="TEST-COLLECTION-1", question_text="Test?",
        )
        version = NormativeDatasetVersion.objects.create(name="test-collection-production")
        NormativeDatasetVersion.objects.filter(pk=version.pk).update(
            status=NormativeDatasetVersion.Status.ACTIVE,
            prepared_at=timezone.now(),
            activated_at=timezone.now(),
        )
        call_command("seed_sociodemographic", verbosity=0)

    def setUp(self):
        self.client.force_login(self.admin)

    def create_test_collection(self, *, active=True):
        collection = QuestionnaireCollection.objects.create(
            owner=self.admin,
            name="Coleta Administrativa",
            is_test_data=True,
            is_active=active,
        )
        collection.spectra.add(self.spectrum)
        return collection

    def test_admin_creates_structurally_test_collection_without_role_mutation(self):
        response = self.client.post(
            reverse("administration:test_collection_create"),
            {"name": "Coleta criada", "spectra": [self.spectrum.pk]},
        )
        collection = QuestionnaireCollection.objects.get(name="Coleta criada")
        self.assertTrue(collection.is_test_data)
        self.assertEqual(collection.owner, self.admin)
        self.assertRedirects(
            response,
            reverse("administration:test_collection_detail", args=[collection.pk]),
        )
        self.admin.userprofile.refresh_from_db()
        self.assertEqual(self.admin.userprofile.user_type, "admin")
        self.assertFalse(self.admin.userprofile.is_researcher)

    def test_production_and_test_lists_are_isolated(self):
        test_collection = self.create_test_collection()
        real = QuestionnaireCollection.objects.create(
            owner=self.professional, name="Real", is_test_data=False,
        )
        response = self.client.get(reverse("administration:test_collection_list"))
        self.assertContains(response, test_collection.name)
        self.assertNotContains(response, real.name)

        self.client.force_login(self.professional)
        response = self.client.get(reverse("website:collection_list"))
        self.assertContains(response, real.name)
        self.assertNotContains(response, test_collection.name)

    def test_public_link_get_does_not_create_and_start_inherits_test_context(self):
        collection = self.create_test_collection()
        public = Client()
        url = reverse("website:collection_public", args=[collection.public_token])
        self.assertContains(public.get(url), "Ambiente de Teste")
        self.assertFalse(collection.submissions.exists())
        users_before = User.objects.count()
        patients_before = UserProfile.objects.filter(user_type="patient").count()
        public.post(reverse("website:collection_start", args=[collection.public_token]))
        submission = collection.submissions.get()
        self.assertTrue(submission.is_test_data)
        self.assertIsNone(submission.user_id)
        self.assertEqual(User.objects.count(), users_before)
        self.assertEqual(UserProfile.objects.filter(user_type="patient").count(), patients_before)

    def test_two_public_clients_create_independent_test_submissions(self):
        collection = self.create_test_collection()
        start = reverse("website:collection_start", args=[collection.public_token])
        Client().post(start)
        Client().post(start)
        self.assertEqual(
            list(collection.submissions.order_by("participant_number").values_list(
                "participant_number", "is_test_data"
            )),
            [(1, True), (2, True)],
        )
        dashboard = self.client.get(reverse("administration:professional_test_environment"))
        self.assertEqual(dashboard.context["total_submissions"], 2)

    def test_manual_public_participation_completes_shared_questionnaire_flow(self):
        collection = self.create_test_collection()
        public = Client()
        public.post(reverse("website:collection_start", args=[collection.public_token]))
        submission = collection.submissions.get()

        questions = list(
            DynamicQuestion.objects.filter(is_active=True)
            .prefetch_related("choices")
            .order_by("order", "id")
        )
        sections = list(dict.fromkeys(question.section for question in questions))
        for index, section in enumerate(sections):
            data = {}
            for question in (item for item in questions if item.section == section):
                field = f"question_{question.pk}"
                choices = list(question.choices.order_by("order", "id"))
                if question.question_type == "checkbox":
                    data[field] = [choices[0].value] if choices else []
                elif question.question_type in ("radio", "matrix"):
                    data[field] = choices[0].value if choices else ""
                elif question.question_type == "number":
                    data[field] = "30"
                else:
                    data[field] = "Resposta de teste"
            public.post(
                reverse("polls:sociodemographic") + f"?section={index}", data,
            )

        submission.refresh_from_db()
        self.assertTrue(submission.sociodemographic_completed)
        questionnaire = public.get(reverse("polls:questionnaire"))
        answer_data = {
            f"question_{question.pk}": "2"
            for question in questionnaire.context["page_obj"]
        }
        public.post(reverse("polls:questionnaire") + "?page=1", answer_data)
        submission.refresh_from_db()
        self.assertTrue(submission.completed)
        self.assertFalse(submission.is_open)

    def test_simulator_creates_collection_owned_test_submissions(self):
        collection = self.create_test_collection()
        response = self.client.post(
            reverse("administration:test_collection_simulate", args=[collection.pk]),
            {
                "simulation_mode": "simulated",
                "simulation_quantity": 2,
                "sociodemographic_simulation_mode": "eligible",
                "simulation_response_profile": "high",
                "simulation_missing_percentage": "0",
                "simulation_attention_mode": "all_correct",
                "simulation_seed": "42",
            },
        )
        self.assertRedirects(
            response,
            reverse("administration:test_collection_detail", args=[collection.pk]),
        )
        submissions = list(collection.submissions.order_by("participant_number"))
        self.assertEqual(len(submissions), 2)
        self.assertTrue(all(item.completed and item.is_test_data for item in submissions))
        self.assertTrue(all(item.user_id is None for item in submissions))
        self.assertTrue(all(item.simulation_response_profile == "high" for item in submissions))
        self.assertTrue(all(item.useranswer_set.exists() for item in submissions))
        with self.assertRaises(TestSubmissionExportBlocked):
            export_submission_to_normative(submissions[0])

    def test_professional_and_other_admin_cannot_access_test_collection(self):
        collection = self.create_test_collection()
        url = reverse("administration:test_collection_detail", args=[collection.pk])
        self.client.force_login(self.professional)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.other_admin)
        self.assertEqual(self.client.get(url).status_code, 404)

    @patch("website.views.calculate_percentile", return_value=50)
    @patch("website.views.calculate_spectrum_percentile", return_value=50)
    def test_test_collection_reports_are_available_and_marked_as_test(
        self, _spectrum_percentile, _scale_percentile,
    ):
        collection = self.create_test_collection()
        self.client.post(
            reverse("administration:test_collection_simulate", args=[collection.pk]),
            {
                "simulation_mode": "simulated",
                "simulation_quantity": 1,
                "sociodemographic_simulation_mode": "eligible",
                "simulation_response_profile": "random",
                "simulation_missing_percentage": "0",
                "simulation_attention_mode": "all_correct",
                "simulation_seed": "7",
            },
        )
        submission = collection.submissions.get()
        preview = self.client.get(reverse(
            "administration:test_collection_report_preview", args=[submission.pk]
        ))
        exported = self.client.get(reverse(
            "administration:test_collection_report_export", args=[submission.pk]
        ))
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "SIMULAÇÃO / TESTE")
        self.assertEqual(exported.status_code, 200)
        with ZipFile(BytesIO(exported.content)) as archive:
            document_xml = archive.read("word/document.xml").decode()
        self.assertIn("SIMULAÇÃO / TESTE", document_xml)

    def test_inactive_test_collection_blocks_new_participation(self):
        collection = self.create_test_collection(active=False)
        response = Client().post(
            reverse("website:collection_start", args=[collection.public_token])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(collection.submissions.exists())

    def test_normative_cleanup_preserves_operational_test_collection(self):
        collection = self.create_test_collection()
        clear_normative_test_environment()
        self.assertTrue(QuestionnaireCollection.objects.filter(pk=collection.pk).exists())

    def test_operational_cleanup_deletes_test_collection_not_real_collection(self):
        test_collection = self.create_test_collection()
        real = QuestionnaireCollection.objects.create(
            owner=self.professional, name="Real preserved", is_test_data=False,
        )
        self.admin.is_staff = True
        self.admin.save(update_fields=["is_staff"])
        result = clear_professional_test_environment(self.admin)
        self.assertEqual(result.collections, 1)
        self.assertFalse(QuestionnaireCollection.objects.filter(pk=test_collection.pk).exists())
        self.assertTrue(QuestionnaireCollection.objects.filter(pk=real.pk).exists())

