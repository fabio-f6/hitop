import json
import random

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from .attention_checks import evaluate_attention_checks
from .models import (
    DynamicAnswer,
    DynamicQuestion,
    NormativeParticipant,
    Question,
    QuestionnaireSubmission,
    Scale,
    Spectra,
    Subfactor,
    UserAnswer,
)
from .normative_export import evaluate_normative_eligibility
from .scoring import calculate_scale_scores_from_answers
from .simulation import simulate_submission
from .sociodemographic import question_is_visible


class HitopSimulationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.patient = User.objects.create_user(username="simulation-patient")
        cls.spectrum = Spectra.objects.create(name="Simulation spectrum")
        subfactor = Subfactor.objects.create(
            name="Simulation subfactor",
            spectra=cls.spectrum,
        )
        cls.scale = Scale.objects.create(name="Simulation scale", subfactor=subfactor)
        cls.questions = [
            Question.objects.create(
                scale=cls.scale,
                item_code=f"simulation-{index:03d}",
                question_text=f"Simulation question {index}",
            )
            for index in range(100)
        ]
        cls.attention_questions = [
            Question.objects.create(
                scale=cls.scale,
                item_code=f"simulation-catch-{index}",
                question_text=f"Attention question {index}",
                is_attention_check=True,
                expected_answer=expected,
            )
            for index, expected in enumerate(("1", "2", "4"))
        ]

    def make_submission(self, **configuration):
        defaults = {
            "simulation_mode": "simulated",
            "simulation_seed": 1234,
        }
        defaults.update(configuration)
        submission = QuestionnaireSubmission.objects.create(
            user=self.patient,
            **defaults,
        )
        submission.spectra.add(self.spectrum)
        return submission

    def answers(self, submission):
        return UserAnswer.objects.filter(submission=submission).select_related(
            "question"
        )

    def test_normal_mode_does_not_simulate_or_complete(self):
        submission = self.make_submission(simulation_mode="normal")

        result = simulate_submission(submission)

        submission.refresh_from_db()
        self.assertIsNone(result)
        self.assertFalse(submission.completed)
        self.assertTrue(submission.is_open)
        self.assertFalse(self.answers(submission).exists())

    def test_simulated_mode_still_generates_valid_answers_and_completes(self):
        submission = self.make_submission()

        simulate_submission(submission)

        submission.refresh_from_db()
        values = set(self.answers(submission).values_list("answer", flat=True))
        self.assertTrue(submission.completed)
        self.assertFalse(submission.is_open)
        self.assertEqual(self.answers(submission).count(), 103)
        self.assertTrue(values <= {"1", "2", "3", "4"})

    def test_legacy_simulated_nulls_maps_default_percentage_to_ten(self):
        submission = self.make_submission(
            simulation_mode="simulated_nulls",
            simulation_missing_percentage=0,
        )

        simulate_submission(submission)

        regular_answers = self.answers(submission).filter(
            question__is_attention_check=False
        )
        self.assertEqual(submission.effective_simulation_missing_percentage, 10)
        self.assertEqual(regular_answers.filter(answer="5").count(), 10)

    def test_zero_percent_produces_no_omissions(self):
        submission = self.make_submission(simulation_missing_percentage=0)
        simulate_submission(submission)
        self.assertFalse(self.answers(submission).filter(answer="5").exists())

    def test_ten_percent_is_deterministic_and_close_to_requested_rate(self):
        first = self.make_submission(simulation_missing_percentage=10)
        second = self.make_submission(simulation_missing_percentage=10)

        simulate_submission(first)
        simulate_submission(second)

        first_missing = list(self.answers(first).filter(answer="5").values_list(
            "question__item_code", flat=True
        ))
        second_missing = list(self.answers(second).filter(answer="5").values_list(
            "question__item_code", flat=True
        ))
        self.assertEqual(len(first_missing), 10)
        self.assertEqual(first_missing, second_missing)

    def test_twenty_five_percent_reaches_current_invalidity_boundary(self):
        submission = self.make_submission(simulation_missing_percentage=25)
        simulate_submission(submission)

        scores = calculate_scale_scores_from_answers(self.answers(submission))

        self.assertEqual(scores[self.scale]["missing_percentage"], 25)
        self.assertFalse(scores[self.scale]["is_valid"])

    def test_thirty_percent_can_generate_an_invalid_scale(self):
        submission = self.make_submission(simulation_missing_percentage=30)
        simulate_submission(submission)

        scores = calculate_scale_scores_from_answers(self.answers(submission))

        self.assertEqual(scores[self.scale]["missing_percentage"], 30)
        self.assertFalse(scores[self.scale]["is_valid"])

    def test_all_attention_checks_are_correct(self):
        submission = self.make_submission(simulation_attention_mode="all_correct")
        simulate_submission(submission)
        result = evaluate_attention_checks(self.answers(submission))
        self.assertEqual(result["incorrect"], 0)

    def test_exactly_one_attention_check_fails(self):
        submission = self.make_submission(simulation_attention_mode="one_failure")
        simulate_submission(submission)
        result = evaluate_attention_checks(self.answers(submission))
        self.assertEqual(result["incorrect"], 1)

    def test_multiple_attention_checks_fail_when_possible(self):
        submission = self.make_submission(
            simulation_attention_mode="multiple_failures"
        )
        simulate_submission(submission)
        result = evaluate_attention_checks(self.answers(submission))
        self.assertGreaterEqual(result["incorrect"], 2)

    def test_missing_answers_never_override_attention_scenario(self):
        submission = self.make_submission(
            simulation_attention_mode="one_failure",
            simulation_missing_percentage=30,
        )
        simulate_submission(submission)

        attention_answers = self.answers(submission).filter(
            question__is_attention_check=True
        )
        self.assertFalse(attention_answers.filter(answer="5").exists())
        self.assertEqual(evaluate_attention_checks(attention_answers)["incorrect"], 1)

    def test_multiple_failures_degrades_to_available_attention_checks(self):
        self.attention_questions[1].delete()
        self.attention_questions[2].delete()
        submission = self.make_submission(
            simulation_attention_mode="multiple_failures"
        )
        simulate_submission(submission)
        result = evaluate_attention_checks(self.answers(submission))
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["incorrect"], 1)

    def profile_counts(self, profile):
        submission = self.make_submission(simulation_response_profile=profile)
        simulate_submission(submission)
        values = self.answers(submission).filter(
            question__is_attention_check=False
        ).values_list("answer", flat=True)
        return {value: list(values).count(value) for value in ("1", "2", "3", "4")}

    def test_low_profile_favours_one_and_two_with_variation(self):
        counts = self.profile_counts("low")
        self.assertGreater(counts["1"] + counts["2"], counts["3"] + counts["4"])
        self.assertGreater(sum(count > 0 for count in counts.values()), 1)

    def test_medium_profile_favours_two_and_three_with_variation(self):
        counts = self.profile_counts("medium")
        self.assertGreater(counts["2"] + counts["3"], counts["1"] + counts["4"])
        self.assertGreater(sum(count > 0 for count in counts.values()), 1)

    def test_high_profile_favours_three_and_four_with_variation(self):
        counts = self.profile_counts("high")
        self.assertGreater(counts["3"] + counts["4"], counts["1"] + counts["2"])
        self.assertGreater(sum(count > 0 for count in counts.values()), 1)

    def test_random_profile_has_only_valid_varied_answers(self):
        counts = self.profile_counts("random")
        self.assertEqual(sum(counts.values()), 100)
        self.assertGreater(sum(count > 0 for count in counts.values()), 1)

    def test_same_seed_and_configuration_generate_identical_answers(self):
        first = self.make_submission(
            simulation_response_profile="high",
            simulation_missing_percentage=25,
            simulation_attention_mode="one_failure",
        )
        second = self.make_submission(
            simulation_response_profile="high",
            simulation_missing_percentage=25,
            simulation_attention_mode="one_failure",
        )

        simulate_submission(first)
        simulate_submission(second)

        def answer_map(submission):
            return dict(self.answers(submission).values_list(
                "question__item_code", "answer"
            ))

        self.assertEqual(answer_map(first), answer_map(second))

    def test_different_seeds_can_generate_different_answers(self):
        first = self.make_submission(simulation_seed=1)
        second = self.make_submission(simulation_seed=2)
        simulate_submission(first)
        simulate_submission(second)
        first_values = list(self.answers(first).order_by("question_id").values_list(
            "answer", flat=True
        ))
        second_values = list(self.answers(second).order_by("question_id").values_list(
            "answer", flat=True
        ))
        self.assertNotEqual(first_values, second_values)

    def test_local_seed_does_not_change_global_random_state(self):
        submission = self.make_submission(simulation_seed=9876)
        state = random.getstate()
        simulate_submission(submission)
        self.assertEqual(random.getstate(), state)


class SociodemographicSimulationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_sociodemographic", verbosity=0)
        cls.patient = User.objects.create_user(username="socio-simulation-patient")
        cls.spectrum = Spectra.objects.create(name="Socio simulation spectrum")
        subfactor = Subfactor.objects.create(
            name="Socio simulation subfactor",
            spectra=cls.spectrum,
        )
        scale = Scale.objects.create(name="Socio simulation scale", subfactor=subfactor)
        Question.objects.create(
            scale=scale,
            item_code="socio-sim-1",
            question_text="Socio simulation question",
        )

    def simulate(self, mode, seed=4321):
        submission = QuestionnaireSubmission.objects.create(
            user=self.patient,
            simulation_mode="simulated",
            sociodemographic_simulation_mode=mode,
            simulation_seed=seed,
        )
        submission.spectra.add(self.spectrum)
        simulate_submission(submission)
        submission.refresh_from_db()
        return submission

    def values(self, submission):
        return dict(DynamicAnswer.objects.filter(
            submission=submission
        ).values_list("question__question_id", "answer_value"))

    def test_eligible_generates_both_required_normative_values(self):
        submission = self.simulate("eligible")
        values = self.values(submission)
        self.assertEqual(values["PT_lang"], "2")
        self.assertEqual(values["mental_diagnosis"], "1")

    def test_eligible_is_exported_by_real_normative_service(self):
        submission = self.simulate("eligible")
        self.assertIs(evaluate_normative_eligibility(submission)["eligible"], True)
        self.assertEqual(submission.normative_status, "exported")
        self.assertEqual(NormativeParticipant.objects.count(), 1)

    def test_ineligible_language_fails_only_language_criterion(self):
        submission = self.simulate("ineligible_language")
        values = self.values(submission)
        self.assertNotEqual(values["PT_lang"], "2")
        self.assertEqual(values["mental_diagnosis"], "1")
        self.assertEqual(submission.normative_status, "ineligible")

    def test_ineligible_mental_health_fails_only_mental_health_criterion(self):
        submission = self.simulate("ineligible_mental_health")
        values = self.values(submission)
        self.assertEqual(values["PT_lang"], "2")
        self.assertNotEqual(values["mental_diagnosis"], "1")
        self.assertEqual(submission.normative_status, "ineligible")

    def test_ineligible_both_fails_both_criteria(self):
        submission = self.simulate("ineligible_both")
        values = self.values(submission)
        self.assertNotEqual(values["PT_lang"], "2")
        self.assertNotEqual(values["mental_diagnosis"], "1")
        self.assertEqual(submission.normative_status, "ineligible")

    def test_pending_missing_omits_a_criterion_and_remains_pending(self):
        submission = self.simulate("pending_missing")
        values = self.values(submission)
        self.assertEqual(values["PT_lang"], "2")
        self.assertNotIn("mental_diagnosis", values)
        self.assertIsNone(evaluate_normative_eligibility(submission)["eligible"])
        self.assertEqual(submission.normative_status, "pending")
        self.assertFalse(NormativeParticipant.objects.exists())

    def test_other_sociodemographic_answers_use_configured_valid_values(self):
        submission = self.simulate("eligible")
        answers = DynamicAnswer.objects.filter(
            submission=submission
        ).select_related("question").prefetch_related("question__choices")
        for answer in answers:
            question = answer.question
            valid = {choice.value for choice in question.choices.all()}
            if question.question_type == "radio":
                self.assertIn(answer.answer_value, valid)
            elif question.question_type == "checkbox":
                self.assertTrue(set(json.loads(answer.answer_value)) <= valid)
            elif question.question_type == "number":
                self.assertTrue(answer.answer_value.isdecimal())
                self.assertGreaterEqual(int(answer.answer_value), 18)
                self.assertLessEqual(int(answer.answer_value), 80)
            elif question.question_type == "text":
                self.assertEqual(answer.answer_value, "Resposta simulada")

    def test_dynamic_questionnaire_conditionals_are_respected(self):
        submission = self.simulate("eligible")
        stored = self.values(submission)
        questions = DynamicQuestion.objects.filter(is_active=True).order_by(
            "order", "id"
        )
        values = {}
        for question in questions:
            visible = question_is_visible(question, values)
            if visible:
                self.assertIn(question.question_id, stored)
                answer = stored[question.question_id]
                values[question.question_id] = (
                    json.loads(answer)
                    if question.question_type == "checkbox"
                    else answer
                )
            else:
                self.assertNotIn(question.question_id, stored)

    def test_same_seed_reproduces_sociodemographic_answers(self):
        first = self.simulate("ineligible_mental_health", seed=77)
        second = self.simulate("ineligible_mental_health", seed=77)
        self.assertEqual(self.values(first), self.values(second))

    def test_ineligible_and_pending_submissions_are_not_exported(self):
        self.simulate("ineligible_language")
        self.simulate("pending_missing")
        self.assertFalse(NormativeParticipant.objects.exists())

    def test_eligible_submission_is_never_exported_twice(self):
        submission = self.simulate("eligible")
        simulate_submission(submission)
        submission.refresh_from_db()
        self.assertEqual(submission.normative_status, "exported")
        self.assertEqual(NormativeParticipant.objects.count(), 1)
