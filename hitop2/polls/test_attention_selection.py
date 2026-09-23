from django.contrib.auth.models import User
from django.test import TestCase

from website.forms import CreatePatientForm, EditPatientForm, NewQuestionnaireForm

from .attention_checks import evaluate_attention_checks
from .models import Question, QuestionnaireSubmission, Scale, Spectra, Subfactor, UserAnswer
from .questions import get_questions_for_submission
from .scoring import calculate_scale_scores_from_answers
from .simulation import simulate_submission


class AutomaticAttentionQuestionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.patient = User.objects.create_user(username="attention-real-patient")
        cls.patient.userprofile.user_type = "patient"
        cls.patient.userprofile.save(update_fields=["user_type"])
        cls.administrator = User.objects.create_user(username="attention-test-admin")
        cls.administrator.userprofile.user_type = "admin"
        cls.administrator.userprofile.save(update_fields=["user_type"])
        cls.test_patient = User.objects.create_user(username="attention-test-patient")
        cls.test_patient.userprofile.user_type = "patient"
        cls.test_patient.userprofile.is_test_data = True
        cls.test_patient.userprofile.test_environment_owner = cls.administrator
        cls.test_patient.userprofile.save(update_fields=[
            "user_type",
            "is_test_data",
            "test_environment_owner",
        ])

        cls.spectrum = Spectra.objects.create(name="Scientific spectrum")
        subfactor = Subfactor.objects.create(name="Scientific subfactor", spectra=cls.spectrum)
        cls.scale = Scale.objects.create(name="Scientific scale", subfactor=subfactor)
        cls.scientific_question = Question.objects.create(
            scale=cls.scale,
            item_code="science-1",
            question_text="Scientific question",
        )
        cls.mixed_attention_question = Question.objects.create(
            scale=cls.scale,
            item_code="attention-mixed-1",
            question_text="Mixed attention question",
            is_attention_check=True,
            expected_answer="2",
        )

        cls.catch_spectrum = Spectra.objects.create(name="Catch")
        catch_subfactor = Subfactor.objects.create(name="Catch", spectra=cls.catch_spectrum)
        catch_scale = Scale.objects.create(name="Catch", subfactor=catch_subfactor)
        cls.catch_question = Question.objects.create(
            scale=catch_scale,
            item_code="attention-catch-1",
            question_text="Catch attention question",
            is_attention_check=True,
            expected_answer="1",
        )

    def make_submission(self, *, simulated=False):
        submission = QuestionnaireSubmission.objects.create(
            user=self.test_patient if simulated else self.patient,
            is_test_data=simulated,
            simulation_mode="simulated" if simulated else "normal",
            simulation_seed=17,
        )
        submission.spectra.add(self.spectrum)
        return submission

    def test_real_question_set_injects_all_attention_checks_once(self):
        questions = list(get_questions_for_submission(self.make_submission()))
        self.assertEqual(
            {question.id for question in questions},
            {
                self.scientific_question.id,
                self.mixed_attention_question.id,
                self.catch_question.id,
            },
        )
        self.assertEqual(len(questions), len({question.id for question in questions}))

    def test_simulation_uses_same_automatic_attention_question_set(self):
        submission = self.make_submission(simulated=True)
        simulate_submission(submission)
        answers = UserAnswer.objects.filter(submission=submission).select_related("question")
        self.assertEqual(answers.count(), 3)
        self.assertEqual(answers.filter(question__is_attention_check=True).count(), 2)
        self.assertEqual(evaluate_attention_checks(answers)["incorrect"], 0)

    def test_attention_checks_are_evaluated_but_not_scored(self):
        submission = self.make_submission()
        UserAnswer.objects.create(
            user=self.patient,
            submission=submission,
            question=self.scientific_question,
            answer="4",
        )
        UserAnswer.objects.create(
            user=self.patient,
            submission=submission,
            question=self.catch_question,
            answer="2",
        )
        answers = UserAnswer.objects.filter(submission=submission).select_related("question__scale")
        scores = calculate_scale_scores_from_answers(answers)
        self.assertEqual(scores[self.scale]["total_items"], 1)
        self.assertEqual(scores[self.scale]["score"], 4)
        self.assertEqual(evaluate_attention_checks(answers)["incorrect"], 1)

    def test_attention_only_spectrum_is_not_selectable_in_any_form(self):
        for form in (
            CreatePatientForm(),
            NewQuestionnaireForm(),
            EditPatientForm(),
        ):
            with self.subTest(form=form.__class__.__name__):
                queryset = form.fields["spectra"].queryset
                self.assertIn(self.spectrum, queryset)
                self.assertNotIn(self.catch_spectrum, queryset)
