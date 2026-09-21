from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.urls import reverse

from .models import (
    DynamicAnswer,
    DynamicQuestion,
    QuestionnaireSubmission,
    SociodemographicAnswer,
)
from .socio_config import SOCIO_QUESTIONS


class QuestionnaireLinkTests(TestCase):
    def test_malformed_questionnaire_uuid_shows_invalid_link_page(self):
        session = self.client.session
        session["submission_id"] = 1
        session["anonymous_questionnaire"] = True
        session.save()

        response = self.client.get("/polls/access/not-a-valid-uuid/")

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Link inválido", status_code=404)
        self.assertNotIn("submission_id", self.client.session)
        self.assertNotIn("anonymous_questionnaire", self.client.session)

    def test_missing_pdf_user_returns_not_found(self):
        response = self.client.get(
            reverse("polls:export_patient_pdf", args=[999999]),
        )

        self.assertEqual(response.status_code, 404)


class PatientQuestionnaireFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_sociodemographic", verbosity=0)
        cls.patient = User.objects.create_user(username="patient-flow")

    def make_submission(self):
        return QuestionnaireSubmission.objects.create(user=self.patient)

    def open_link(self, submission):
        return self.client.get(
            reverse("polls:questionnaire_by_token", args=[submission.access_token]),
            follow=True,
        )

    def section_data(self, questions):
        data = {}
        for question in questions:
            if question.question_type == "checkbox":
                data[f"question_{question.id}"] = [question.choices.first().value]
            elif question.question_type == "radio":
                data[f"question_{question.id}"] = question.choices.first().value
            elif question.question_type == "number":
                data[f"question_{question.id}"] = "33"
            else:
                data[f"question_{question.id}"] = "Resposta de teste"
        return data

    def test_seed_updates_existing_questions_without_duplicates(self):
        self.assertEqual(
            DynamicQuestion.objects.filter(is_active=True).count(),
            len(SOCIO_QUESTIONS),
        )
        question = DynamicQuestion.objects.get(question_id="sex")
        question.label = "Texto antigo"
        question.save(update_fields=["label"])
        DynamicQuestion.objects.create(
            question_id="obsolete_question",
            category=question.category,
            label="Pergunta removida",
            question_type="text",
            section="Secção removida",
            order=999,
        )

        call_command("seed_sociodemographic", verbosity=0)

        question.refresh_from_db()
        self.assertEqual(
            DynamicQuestion.objects.filter(is_active=True).count(),
            len(SOCIO_QUESTIONS),
        )
        self.assertEqual(question.label, "Que sexo lhe foi atribuído à nascença?")
        self.assertEqual(question.choices.count(), 3)
        self.assertFalse(DynamicQuestion.objects.get(
            question_id="obsolete_question"
        ).is_active)

    def test_uuid_flow_resumes_and_new_submission_asks_again(self):
        first = self.make_submission()
        SociodemographicAnswer.objects.create(
            user=self.patient, question_id="age", answer_value="40",
            answer_label="40",
        )
        response = self.open_link(first)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dados Sociodemográficos")

        questions = list(DynamicQuestion.objects.filter(
            is_active=True
        ).order_by("order"))
        section_names = list(dict.fromkeys(q.section for q in questions))
        self.assertEqual(section_names, ["Dados Sociodemográficos"])

        response = self.client.post(
            reverse("polls:sociodemographic") + "?section=0",
            self.section_data(questions),
        )
        self.assertRedirects(
            response,
            reverse("polls:questionnaire"),
            fetch_redirect_response=False,
        )

        first.refresh_from_db()
        self.assertTrue(first.sociodemographic_completed)
        self.assertTrue(DynamicAnswer.objects.filter(submission=first).exists())

        second = self.make_submission()
        session = self.client.session
        session["question_order"] = [999]
        session["partial_answers"] = {"999": "2"}
        session.save()
        response = self.open_link(second)
        self.assertContains(response, "Dados Sociodemográficos")
        self.assertFalse(second.sociodemographic_completed)
        self.assertFalse(DynamicAnswer.objects.filter(submission=second).exists())
        self.assertNotIn("question_order", self.client.session)
        self.assertNotIn("partial_answers", self.client.session)

        response = self.client.get(reverse("polls:sociodemographic"))
        self.assertContains(response, "Dados Sociodemográficos")

    @override_settings(SOCIODEMOGRAPHIC_REQUIRE_ANSWERS=False)
    def test_blank_page_can_complete_questionnaire(self):
        submission = self.make_submission()
        self.open_link(submission)

        response = self.client.post(
            reverse("polls:sociodemographic") + "?section=0", {},
        )
        self.assertRedirects(
            response,
            reverse("polls:questionnaire"),
            fetch_redirect_response=False,
        )

        submission.refresh_from_db()
        self.assertTrue(submission.sociodemographic_completed)
        self.assertEqual(submission.sociodemographic_step, 1)
        self.assertFalse(DynamicAnswer.objects.filter(submission=submission).exists())

    @override_settings(SOCIODEMOGRAPHIC_REQUIRE_ANSWERS=True)
    def test_required_mode_blocks_blank_section(self):
        submission = self.make_submission()
        self.open_link(submission)

        response = self.client.post(
            reverse("polls:sociodemographic") + "?section=0", {},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Revise as respostas obrigatórias")
        submission.refresh_from_db()
        self.assertEqual(submission.sociodemographic_step, 0)
