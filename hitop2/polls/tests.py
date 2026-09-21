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
        self.assertEqual(DynamicQuestion.objects.count(), len(SOCIO_QUESTIONS))
        question = DynamicQuestion.objects.get(question_id="sex")
        question.label = "Texto antigo"
        question.save(update_fields=["label"])

        call_command("seed_sociodemographic", verbosity=0)

        question.refresh_from_db()
        self.assertEqual(DynamicQuestion.objects.count(), len(SOCIO_QUESTIONS))
        self.assertEqual(question.label, "Que sexo lhe foi atribuído à nascença?")
        self.assertEqual(question.choices.count(), 3)
        intro = DynamicQuestion.objects.get(question_id="subs_use_lastyear_alc")
        next_question = DynamicQuestion.objects.get(question_id="subs_use_lastyear_can")
        self.assertIn("No último ano", intro.group_intro)
        self.assertEqual(next_question.group_intro, "")

    def test_uuid_flow_resumes_and_new_submission_asks_again(self):
        first = self.make_submission()
        SociodemographicAnswer.objects.create(
            user=self.patient, question_id="age", answer_value="40",
            answer_label="40",
        )
        response = self.open_link(first)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dados Sociodemográficos")

        questions = list(DynamicQuestion.objects.order_by("order"))
        section_names = list(dict.fromkeys(q.section for q in questions))
        self.assertEqual(len(section_names), 11)

        for index, section_name in enumerate(section_names):
            section_questions = [q for q in questions if q.section == section_name]
            response = self.client.post(
                reverse("polls:sociodemographic") + f"?section={index}",
                self.section_data(section_questions),
            )
            self.assertEqual(response.status_code, 302)
            if index == 0:
                resumed = self.open_link(first)
                self.assertContains(resumed, "Consumo de substâncias")

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

    def test_conditional_health_questions_are_not_required_when_hidden(self):
        submission = self.make_submission()
        self.open_link(submission)
        questions = list(DynamicQuestion.objects.order_by("order"))
        section_names = list(dict.fromkeys(q.section for q in questions))

        for index, section_name in enumerate(section_names[:3]):
            section_questions = [q for q in questions if q.section == section_name]
            self.client.post(
                reverse("polls:sociodemographic") + f"?section={index}",
                self.section_data(section_questions),
            )

        health_index = section_names.index("Saúde física")
        response = self.client.post(
            reverse("polls:sociodemographic") + f"?section={health_index}",
            {"question_%s" % DynamicQuestion.objects.get(question_id="Health").id: "3"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(DynamicAnswer.objects.filter(
            submission=submission, question__question_id="Diagnosis"
        ).exists())

    @override_settings(SOCIODEMOGRAPHIC_REQUIRE_ANSWERS=True)
    def test_conditional_text_is_required_when_parent_option_is_selected(self):
        submission = self.make_submission()
        self.open_link(submission)
        questions = list(DynamicQuestion.objects.order_by("order"))
        sections = list(dict.fromkeys(q.section for q in questions))

        for index, section_name in enumerate(sections[:2]):
            section_questions = [q for q in questions if q.section == section_name]
            self.client.post(
                reverse("polls:sociodemographic") + f"?section={index}",
                self.section_data(section_questions),
            )

        mental_questions = [q for q in questions if q.section == "Saúde Mental"]
        data = self.section_data(mental_questions)
        treatment = DynamicQuestion.objects.get(question_id="mental_treatment")
        medication = DynamicQuestion.objects.get(question_id="mental_med")
        data[f"question_{treatment.id}"] = ["4"]
        data.pop(f"question_{medication.id}")
        response = self.client.post(
            reverse("polls:sociodemographic") + "?section=2", data,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Revise as respostas obrigatórias")
        self.assertFalse(DynamicAnswer.objects.filter(
            submission=submission, question=medication,
        ).exists())

    @override_settings(SOCIODEMOGRAPHIC_REQUIRE_ANSWERS=False)
    def test_blank_sections_can_advance_and_resume(self):
        submission = self.make_submission()
        self.open_link(submission)
        sections = list(dict.fromkeys(
            DynamicQuestion.objects.order_by("order").values_list("section", flat=True)
        ))

        first_response = self.client.post(
            reverse("polls:sociodemographic") + "?section=0", {},
        )
        self.assertRedirects(
            first_response,
            reverse("polls:sociodemographic") + "?section=1",
            fetch_redirect_response=False,
        )
        response = self.open_link(submission)
        self.assertContains(response, "Consumo de substâncias")
        intro = DynamicQuestion.objects.get(question_id="subs_use_lastyear_alc").group_intro
        html = response.content.decode()
        self.assertEqual(html.count(intro), 1)
        self.assertLess(html.index(intro), html.index("Álcool (etanol)"))
        self.assertFalse(response.context["require_answers"])
        self.assertNotIn('aria-hidden="true">*</span>', html)

        for index in range(1, len(sections)):
            response = self.client.post(
                reverse("polls:sociodemographic") + f"?section={index}", {},
            )
            self.assertEqual(response.status_code, 302)

        submission.refresh_from_db()
        self.assertTrue(submission.sociodemographic_completed)
        self.assertEqual(submission.sociodemographic_step, len(sections))
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
