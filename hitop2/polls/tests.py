from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.contrib import admin
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from .models import (
    DynamicAnswer,
    DynamicQuestion,
    NormativeAnswer,
    NormativeParticipant,
    NormativeScaleScore,
    NormativeSpectrumScore,
    Question,
    QuestionnaireSubmission,
    Scale,
    SociodemographicAnswer,
    Spectra,
    Subfactor,
    UserAnswer,
)
from .normative_versions import (
    activate_normative_version,
    create_normative_version,
    prepare_normative_version,
)
from .normative_export import (
    SubmissionAlreadyExported,
    evaluate_normative_eligibility,
    export_submission_to_normative,
    process_normative_eligibility,
)
from .socio_config import SOCIO_QUESTIONS


PDF_SOCIODEMOGRAPHIC_STRUCTURE = {
    "Dados Sociodemográficos": (
        "age", "country_born", "country_residence", "PT_residence_years",
        "PT_residence_years_other", "PT_lang", "PT_residence_region",
        "freguesia", "urbanicity", "race", "gender", "sex", "education",
        "employment", "socioeconomic", "income", "marital_status",
        "household_adults", "household_children", "spirituality",
    ),
    "Consumo de substâncias": (
        "subs_use_lastyear_alc", "subs_use_lastyear_can",
        "subs_use_lastyear_nic", "subs_use_lastyear_stimulant",
        "subs_use_lastyear_inal", "subs_use_lastyear_aluc",
        "subs_use_lastyear_opiod", "subs_use_lastyear_medicines",
        "subs_use_life_4", "subs_use_life_24", "subs_use_life_25",
        "subs_use_life_26", "subs_use_life_27",
    ),
    "Saúde Mental": (
        "mental_diagnosis", "mental_treatment", "mental_med",
        "treatment_access", "insurance", "absenteeism", "presenteeism",
        "life_events", "social_support",
    ),
    "Estado de saúde física": (
        "Health", "Diagnosis", "Diagnosis_descript", "Diagnosis_onset",
        "Diagnosis_med", "Diagnosis_med_name", "Diagnosis_med_freq",
        "Diagnosis_med_freq_other", "Medication_regular",
    ),
    "Validação respostas": ("Answer_validation",),
}


class QuestionnaireSubmissionNormativeStatusTests(TestCase):
    def setUp(self):
        self.patient = User.objects.create_user(username="normative-status-patient")

    def test_new_submission_defaults_to_pending_without_export_timestamp(self):
        submission = QuestionnaireSubmission.objects.create(user=self.patient)

        self.assertEqual(
            submission.normative_status,
            QuestionnaireSubmission.NormativeStatus.PENDING,
        )
        self.assertIsNone(submission.normative_exported_at)

    def test_all_normative_statuses_can_be_persisted(self):
        submission = QuestionnaireSubmission.objects.create(user=self.patient)

        for status in QuestionnaireSubmission.NormativeStatus.values:
            submission.normative_status = status
            submission.save(update_fields=["normative_status"])
            submission.refresh_from_db()
            self.assertEqual(submission.normative_status, status)

        exported_at = timezone.now()
        submission.normative_status = QuestionnaireSubmission.NormativeStatus.EXPORTED
        submission.normative_exported_at = exported_at
        submission.save(update_fields=["normative_status", "normative_exported_at"])
        submission.refresh_from_db()
        self.assertEqual(submission.normative_exported_at, exported_at)

    def test_admin_lists_and_filters_by_normative_status(self):
        model_admin = admin.site._registry[QuestionnaireSubmission]

        self.assertIn("normative_status", model_admin.list_display)
        self.assertIn("normative_exported_at", model_admin.list_display)
        self.assertIn("normative_status", model_admin.list_filter)


class NormativeExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_sociodemographic", verbosity=0)
        cls.patient = User.objects.create_user(username="normative-export-patient")
        spectrum = Spectra.objects.create(name="Spectrum")
        subfactor = Subfactor.objects.create(name="Subfactor", spectra=spectrum)
        cls.scale = Scale.objects.create(name="Scale", subfactor=subfactor)
        cls.question = Question.objects.create(
            scale=cls.scale,
            item_code="export-1",
            question_text="Export test",
        )

    def make_submission(self):
        submission = QuestionnaireSubmission.objects.create(
            user=self.patient,
            completed=True,
        )
        UserAnswer.objects.create(
            user=self.patient,
            submission=submission,
            question=self.question,
            answer="3",
        )
        for question_id, value in (("age", "34"), ("sex", "1")):
            DynamicAnswer.objects.create(
                user=self.patient,
                submission=submission,
                question=DynamicQuestion.objects.get(question_id=question_id),
                answer_value=value,
            )
        return submission

    def test_submission_is_exported_without_changing_a_normative_version(self):
        submission = self.make_submission()

        participant = export_submission_to_normative(submission)

        submission.refresh_from_db()
        self.assertEqual(submission.normative_status, "exported")
        self.assertIsNotNone(submission.normative_exported_at)
        self.assertEqual(participant.age, 34)
        self.assertEqual(participant.sex, "Feminino")
        self.assertEqual(participant.answers.get().answer, "3")
        self.assertFalse(participant.dataset_versions.exists())
        self.assertFalse(participant.scale_scores.exists())
        self.assertFalse(participant.spectrum_scores.exists())

    def test_second_export_is_rejected_without_creating_data(self):
        submission = self.make_submission()
        export_submission_to_normative(submission)

        with self.assertRaises(SubmissionAlreadyExported):
            export_submission_to_normative(submission)

        self.assertEqual(NormativeParticipant.objects.count(), 1)
        self.assertEqual(NormativeAnswer.objects.count(), 1)

    def test_failure_rolls_back_all_normative_data_and_status(self):
        submission = self.make_submission()

        with patch.object(
            NormativeAnswer.objects,
            "bulk_create",
            side_effect=RuntimeError("forced failure"),
        ):
            with self.assertRaises(RuntimeError):
                export_submission_to_normative(submission)

        submission.refresh_from_db()
        self.assertEqual(submission.normative_status, "pending")
        self.assertIsNone(submission.normative_exported_at)
        self.assertFalse(NormativeParticipant.objects.exists())
        self.assertFalse(NormativeAnswer.objects.exists())
        self.assertFalse(NormativeScaleScore.objects.exists())
        self.assertFalse(NormativeSpectrumScore.objects.exists())

    def test_normative_models_have_no_foreign_keys_to_clinical_models(self):
        clinical_models = {
            QuestionnaireSubmission,
            UserAnswer,
            DynamicAnswer,
            User,
        }
        for model in (
            NormativeParticipant,
            NormativeAnswer,
            NormativeScaleScore,
            NormativeSpectrumScore,
        ):
            related_models = {
                field.related_model
                for field in model._meta.fields
                if field.many_to_one
            }
            self.assertTrue(related_models.isdisjoint(clinical_models))

    def test_normative_data_survives_deletion_of_clinical_data(self):
        submission = self.make_submission()
        participant = export_submission_to_normative(submission)
        version = create_normative_version("test-v1")
        prepare_normative_version(version)
        activate_normative_version(version)

        self.patient.delete()

        participant.refresh_from_db()
        self.assertEqual(participant.answers.count(), 1)
        self.assertEqual(participant.scale_scores.count(), 1)
        self.assertEqual(participant.spectrum_scores.count(), 1)


class NormativeEligibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_sociodemographic", verbosity=0)
        cls.patient = User.objects.create_user(username="eligibility-patient")
        spectrum = Spectra.objects.create(name="Eligibility spectrum")
        subfactor = Subfactor.objects.create(name="Eligibility subfactor", spectra=spectrum)
        cls.scale = Scale.objects.create(name="Eligibility scale", subfactor=subfactor)
        cls.clinical_question = Question.objects.create(
            scale=cls.scale, item_code="elig-1", question_text="Eligibility test",
        )

    def make_submission(self, completed=True, pt="2", mental="1"):
        submission = QuestionnaireSubmission.objects.create(
            user=self.patient, completed=completed,
        )
        UserAnswer.objects.create(
            user=self.patient, submission=submission,
            question=self.clinical_question, answer="3",
        )
        for question_id, value in (("PT_lang", pt), ("mental_diagnosis", mental)):
            if value is not None:
                DynamicAnswer.objects.create(
                    user=self.patient, submission=submission,
                    question=DynamicQuestion.objects.get(question_id=question_id),
                    answer_value=value,
                )
        return submission

    def test_both_criteria_met_is_eligible(self):
        result = evaluate_normative_eligibility(self.make_submission())
        self.assertIs(result["eligible"], True)

    def test_portuguese_criterion_failed_is_ineligible(self):
        result = evaluate_normative_eligibility(self.make_submission(pt="1"))
        self.assertIs(result["eligible"], False)

    def test_mental_health_criterion_failed_is_ineligible(self):
        result = evaluate_normative_eligibility(self.make_submission(mental="2"))
        self.assertIs(result["eligible"], False)

    def test_both_criteria_failed_is_ineligible(self):
        result = evaluate_normative_eligibility(self.make_submission(pt="1", mental="3"))
        self.assertIs(result["eligible"], False)

    def test_missing_portuguese_answer_stays_pending_without_export(self):
        submission = self.make_submission(pt=None)
        result = process_normative_eligibility(submission)
        submission.refresh_from_db()
        self.assertIsNone(result["eligible"])
        self.assertEqual(submission.normative_status, "pending")
        self.assertFalse(NormativeParticipant.objects.exists())

    def test_missing_mental_health_answer_stays_pending_without_export(self):
        submission = self.make_submission(mental=None)
        result = process_normative_eligibility(submission)
        submission.refresh_from_db()
        self.assertIsNone(result["eligible"])
        self.assertEqual(submission.normative_status, "pending")
        self.assertFalse(NormativeParticipant.objects.exists())

    def test_incomplete_submission_is_not_exported(self):
        submission = self.make_submission(completed=False)
        result = process_normative_eligibility(submission)
        self.assertIsNone(result["eligible"])
        self.assertFalse(NormativeParticipant.objects.exists())

    def test_completed_eligible_submission_is_exported_once(self):
        submission = self.make_submission()
        process_normative_eligibility(submission)
        process_normative_eligibility(submission)
        submission.refresh_from_db()
        self.assertEqual(submission.normative_status, "exported")
        self.assertEqual(NormativeParticipant.objects.count(), 1)
        self.assertEqual(NormativeAnswer.objects.count(), 1)

    def test_attention_checks_are_not_exported_to_normative_answers(self):
        submission = self.make_submission()
        attention_question = Question.objects.create(
            scale=self.scale,
            item_code="norm-attention-1",
            question_text="Attention check",
            is_attention_check=True,
            expected_answer="1",
        )
        UserAnswer.objects.create(
            user=self.patient,
            submission=submission,
            question=attention_question,
            answer="1",
        )

        process_normative_eligibility(submission)

        self.assertEqual(NormativeAnswer.objects.count(), 1)
        self.assertFalse(
            NormativeAnswer.objects.filter(question=attention_question).exists()
        )

    def test_evaluating_exported_submission_does_not_duplicate_data(self):
        submission = self.make_submission()
        process_normative_eligibility(submission)
        evaluate_normative_eligibility(submission)
        process_normative_eligibility(submission)
        self.assertEqual(NormativeParticipant.objects.count(), 1)
        self.assertEqual(NormativeAnswer.objects.count(), 1)

    def test_ineligible_submission_creates_no_normative_data(self):
        submission = self.make_submission(pt="1")
        process_normative_eligibility(submission)
        submission.refresh_from_db()
        self.assertEqual(submission.normative_status, "ineligible")
        self.assertFalse(NormativeParticipant.objects.exists())
        self.assertFalse(NormativeAnswer.objects.exists())


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
        diagnosis = DynamicQuestion.objects.get(question_id="mental_diagnosis")
        self.assertEqual(
            list(diagnosis.choices.order_by("order").values_list("value", "label")),
            [
                ("1", "Não, nunca tive"),
                ("2", "Sim, durante o último ano"),
                ("3", "Sim, há mais de um ano"),
            ],
        )
        self.assertFalse(DynamicQuestion.objects.get(
            question_id="obsolete_question"
        ).is_active)

    def test_pdf_questions_are_complete_and_in_the_expected_block_order(self):
        configured_structure = {}
        for question in SOCIO_QUESTIONS:
            configured_structure.setdefault(question["section"], []).append(
                question["id"]
            )

        self.assertEqual(
            list(configured_structure),
            list(PDF_SOCIODEMOGRAPHIC_STRUCTURE),
        )
        self.assertEqual(
            configured_structure,
            {
                section: list(question_ids)
                for section, question_ids in PDF_SOCIODEMOGRAPHIC_STRUCTURE.items()
            },
        )
        self.assertEqual(len(SOCIO_QUESTIONS), 52)
        self.assertEqual(
            PDF_SOCIODEMOGRAPHIC_STRUCTURE["Validação respostas"],
            ("Answer_validation",),
        )

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
        self.assertEqual(section_names, list(PDF_SOCIODEMOGRAPHIC_STRUCTURE))

        first_section_questions = [
            question for question in questions
            if question.section == section_names[0]
        ]
        response = self.client.post(
            reverse("polls:sociodemographic") + "?section=0",
            self.section_data(first_section_questions),
        )
        self.assertRedirects(
            response,
            reverse("polls:sociodemographic") + "?section=1",
            fetch_redirect_response=False,
        )
        response = self.open_link(first)
        self.assertContains(response, "Consumo de substâncias")

        response = self.client.get(
            reverse("polls:sociodemographic") + "?section=0"
        )
        age = DynamicQuestion.objects.get(question_id="age")
        self.assertEqual(response.context["answers"][age.id], "33")

        for index, section_name in enumerate(section_names[1:], start=1):
            section_questions = [
                question for question in questions
                if question.section == section_name
            ]
            response = self.client.post(
                reverse("polls:sociodemographic") + f"?section={index}",
                self.section_data(section_questions),
            )
            self.assertEqual(response.status_code, 302)

        self.assertEqual(response.url, reverse("polls:questionnaire"))

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

        for index in range(len(PDF_SOCIODEMOGRAPHIC_STRUCTURE)):
            response = self.client.post(
                reverse("polls:sociodemographic") + f"?section={index}", {},
            )
            self.assertEqual(response.status_code, 302)

        submission.refresh_from_db()
        self.assertTrue(submission.sociodemographic_completed)
        self.assertEqual(
            submission.sociodemographic_step,
            len(PDF_SOCIODEMOGRAPHIC_STRUCTURE),
        )
        self.assertFalse(DynamicAnswer.objects.filter(submission=submission).exists())

    def test_progress_matches_the_current_block(self):
        submission = self.make_submission()
        response = self.open_link(submission)

        self.assertEqual(response.context["progress"], 20)
        self.assertContains(response, 'data-progress-value="20.0"')
        self.assertContains(response, "Página 1 de 5")

        questions = DynamicQuestion.objects.filter(
            is_active=True,
            section="Dados Sociodemográficos",
        ).order_by("order")
        self.client.post(
            reverse("polls:sociodemographic") + "?section=0",
            self.section_data(questions),
        )
        response = self.client.get(
            reverse("polls:sociodemographic") + "?section=1"
        )

        self.assertEqual(response.context["progress"], 40)
        self.assertContains(response, 'data-progress-value="40.0"')
        self.assertContains(response, "Página 2 de 5")

    def test_conditional_mental_medication_is_required_when_selected(self):
        submission = self.make_submission()
        self.open_link(submission)
        sections = list(PDF_SOCIODEMOGRAPHIC_STRUCTURE)

        for index in range(2):
            questions = DynamicQuestion.objects.filter(
                is_active=True,
                section=sections[index],
            ).order_by("order")
            self.client.post(
                reverse("polls:sociodemographic") + f"?section={index}",
                self.section_data(questions),
            )

        questions = list(DynamicQuestion.objects.filter(
            is_active=True,
            section="Saúde Mental",
        ).order_by("order"))
        data = self.section_data(questions)
        treatment = DynamicQuestion.objects.get(question_id="mental_treatment")
        medication = DynamicQuestion.objects.get(question_id="mental_med")
        data[f"question_{treatment.id}"] = ["4"]
        data.pop(f"question_{medication.id}")

        response = self.client.post(
            reverse("polls:sociodemographic") + "?section=2",
            data,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Revise as respostas obrigatórias")
        self.assertFalse(DynamicAnswer.objects.filter(
            submission=submission,
            question=medication,
        ).exists())

    def test_hidden_physical_health_questions_are_not_required(self):
        submission = self.make_submission()
        self.open_link(submission)
        sections = list(PDF_SOCIODEMOGRAPHIC_STRUCTURE)

        for index in range(3):
            questions = DynamicQuestion.objects.filter(
                is_active=True,
                section=sections[index],
            ).order_by("order")
            self.client.post(
                reverse("polls:sociodemographic") + f"?section={index}",
                self.section_data(questions),
            )

        questions = list(DynamicQuestion.objects.filter(
            is_active=True,
            section="Estado de saúde física",
        ).order_by("order"))
        data = self.section_data(questions)
        health = DynamicQuestion.objects.get(question_id="Health")
        data[f"question_{health.id}"] = "3"

        response = self.client.post(
            reverse("polls:sociodemographic") + "?section=3",
            data,
        )

        self.assertRedirects(
            response,
            reverse("polls:sociodemographic") + "?section=4",
            fetch_redirect_response=False,
        )
        self.assertFalse(DynamicAnswer.objects.filter(
            submission=submission,
            question__question_id="Diagnosis",
        ).exists())

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
