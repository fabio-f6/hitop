import uuid

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from polls.models import (
    DynamicQuestion,
    NormativeDatasetVersion,
    NormativeParticipant,
    Question,
    QuestionnaireSubmission,
    Scale,
    Spectra,
    Subfactor,
    UserAnswer,
)
from polls.normative_export import (
    MENTAL_DIAGNOSIS_QUESTION_ID,
    PORTUGUESE_LANGUAGE_QUESTION_ID,
)
from polls.normative_versions import (
    activate_normative_version,
    create_normative_version,
    prepare_normative_version,
)

from .health_checks import get_system_health_report
from .models import AdministrativeAuditLog
from .monitoring import get_questionnaire_monitoring_report


class MonitoringHealthTestMixin:
    password = "Uma-palavra-passe-segura-123"

    @classmethod
    def create_user(cls, username, user_type, *, verified=False):
        user = User.objects.create_user(
            username=username,
            password=cls.password,
        )
        user.userprofile.user_type = user_type
        user.userprofile.is_verified = verified
        user.userprofile.save(update_fields=["user_type", "is_verified"])
        return user

    @staticmethod
    def create_structure(prefix="health"):
        spectrum = Spectra.objects.create(name=f"{prefix} spectrum")
        subfactor = Subfactor.objects.create(
            name=f"{prefix} subfactor",
            spectra=spectrum,
        )
        scale = Scale.objects.create(
            name=f"{prefix} scale",
            subfactor=subfactor,
        )
        question = Question.objects.create(
            scale=scale,
            item_code=f"{prefix[:12]}-1",
            question_text=f"{prefix} question",
        )
        return spectrum, subfactor, scale, question


class QuestionnaireMonitoringTests(MonitoringHealthTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.administrator = cls.create_user("monitoring-admin", "admin")
        cls.professional = cls.create_user(
            "monitoring-professional",
            "professional",
            verified=True,
        )
        cls.patient = cls.create_user("monitoring-patient", "patient")

    def setUp(self):
        self.client.force_login(self.administrator)

    def create_submission(self, **fields):
        return QuestionnaireSubmission.objects.create(
            user=self.patient,
            **fields,
        )

    def test_administrator_can_access_questionnaire_monitoring(self):
        response = self.client.get(
            reverse("administration:questionnaire_monitoring")
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "administration/questionnaire_monitoring.html",
        )

    def test_professional_and_patient_cannot_access_monitoring(self):
        for user in (self.professional, self.patient):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.client.get(
                    reverse("administration:questionnaire_monitoring")
                )
                self.assertEqual(response.status_code, 403)

    def test_anonymous_user_is_redirected_to_login(self):
        self.client.logout()

        response = self.client.get(
            reverse("administration:questionnaire_monitoring")
        )

        self.assertRedirects(response, reverse("website:home"))

    def test_submission_totals_and_workflow_counts_use_real_fields(self):
        self.create_submission(is_open=True, completed=False)
        self.create_submission(is_open=False, completed=False)
        self.create_submission(is_open=False, completed=True)

        report = get_questionnaire_monitoring_report()

        self.assertEqual(report["summary"]["total"], 3)
        self.assertEqual(report["summary"]["open"], 1)
        self.assertEqual(report["summary"]["completed"], 1)

    def test_test_submissions_are_reported_separately_from_real_metrics(self):
        self.create_submission(is_open=True, completed=False)
        self.create_submission(
            is_test_data=True,
            is_open=True,
            completed=False,
            simulation_mode="simulated",
        )
        self.create_submission(
            is_test_data=True,
            is_open=False,
            completed=True,
            simulation_mode="simulated",
        )

        summary = get_questionnaire_monitoring_report()["summary"]

        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["open"], 1)
        self.assertEqual(summary["completed"], 0)
        self.assertEqual(summary["test_total"], 2)
        self.assertEqual(summary["test_open"], 1)
        self.assertEqual(summary["test_completed"], 1)

    def test_legacy_simulation_mode_is_not_counted_as_clinical_activity(self):
        self.create_submission(simulation_mode="normal")
        self.create_submission(
            simulation_mode="simulated_nulls",
            is_test_data=False,
            completed=True,
            is_open=False,
        )

        summary = get_questionnaire_monitoring_report()["summary"]

        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["completed"], 0)
        self.assertEqual(summary["test_total"], 1)
        self.assertEqual(summary["test_completed"], 1)

    def test_normative_status_counts_are_correct(self):
        self.create_submission(
            normative_status=QuestionnaireSubmission.NormativeStatus.PENDING,
        )
        self.create_submission(
            completed=True,
            is_open=False,
            normative_status=QuestionnaireSubmission.NormativeStatus.PENDING,
        )
        self.create_submission(
            completed=True,
            is_open=False,
            normative_status=QuestionnaireSubmission.NormativeStatus.INELIGIBLE,
        )
        self.create_submission(
            completed=True,
            is_open=False,
            normative_status=QuestionnaireSubmission.NormativeStatus.EXPORTED,
            normative_exported_at=timezone.now(),
        )

        summary = get_questionnaire_monitoring_report()["summary"]

        self.assertEqual(summary["pending"], 2)
        self.assertEqual(summary["pending_incomplete"], 1)
        self.assertEqual(summary["completed_pending"], 1)
        self.assertEqual(summary["ineligible"], 1)
        self.assertEqual(summary["exported"], 1)

    def test_monitoring_summary_uses_one_aggregate_query(self):
        self.create_submission()

        with self.assertNumQueries(1):
            get_questionnaire_monitoring_report()

    def test_page_does_not_show_access_token(self):
        secret_token = uuid.UUID("12345678-1234-5678-1234-567812345678")
        self.create_submission(access_token=secret_token)

        response = self.client.get(
            reverse("administration:questionnaire_monitoring")
        )

        self.assertNotContains(response, str(secret_token))

    def test_page_does_not_show_user_answers_or_patient_identity(self):
        _spectrum, _subfactor, _scale, question = self.create_structure(
            "private-monitor"
        )
        submission = self.create_submission(title="PRIVATE CLINICAL TITLE")
        UserAnswer.objects.create(
            user=self.patient,
            submission=submission,
            question=question,
            answer="4",
        )

        response = self.client.get(
            reverse("administration:questionnaire_monitoring")
        )

        self.assertNotContains(response, self.patient.username)
        self.assertNotContains(response, question.question_text)
        self.assertNotContains(response, "PRIVATE CLINICAL TITLE")

    def test_objective_operational_alerts_are_detected(self):
        self.create_submission(completed=True, is_open=False)
        self.create_submission(completed=True, is_open=True)
        self.create_submission(
            completed=True,
            is_open=False,
            normative_status=QuestionnaireSubmission.NormativeStatus.EXPORTED,
            normative_exported_at=None,
        )

        alerts = get_questionnaire_monitoring_report()["alerts"]
        alert_codes = {alert["code"] for alert in alerts}

        self.assertIn("completed_normative_pending", alert_codes)
        self.assertIn("completed_submission_still_open", alert_codes)
        self.assertIn("exported_without_timestamp", alert_codes)

    def test_normal_open_pending_submission_is_not_an_alert(self):
        self.create_submission(
            completed=False,
            is_open=True,
            normative_status=QuestionnaireSubmission.NormativeStatus.PENDING,
        )

        report = get_questionnaire_monitoring_report()

        self.assertEqual(report["alerts"], [])
        self.assertFalse(report["failure_tracking_available"])

    def test_absence_of_submissions_renders_empty_state_without_error(self):
        response = self.client.get(
            reverse("administration:questionnaire_monitoring")
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"]["total"], 0)
        self.assertContains(response, "Não foram detetadas inconsistências")


class SystemHealthTests(MonitoringHealthTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.administrator = cls.create_user("health-admin", "admin")
        cls.professional = cls.create_user(
            "health-professional",
            "professional",
            verified=True,
        )
        cls.patient = cls.create_user("health-patient", "patient")
        (
            cls.spectrum,
            cls.subfactor,
            cls.scale,
            cls.question,
        ) = cls.create_structure("baseline")
        call_command("seed_sociodemographic", verbosity=0)

    def setUp(self):
        self.client.force_login(self.administrator)

    def test_administrator_can_access_system_health(self):
        response = self.client.get(reverse("administration:system_health"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "administration/system_health.html")

    def test_non_administrators_cannot_access_system_health(self):
        for user in (self.professional, self.patient):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.client.get(reverse("administration:system_health"))
                self.assertEqual(response.status_code, 403)

        self.client.logout()
        response = self.client.get(reverse("administration:system_health"))
        self.assertRedirects(response, reverse("website:home"))

    def test_spectra_count_is_correct(self):
        report = get_system_health_report()

        self.assertEqual(report["structure"]["spectra_count"], 1)

    def test_subfactor_count_is_correct(self):
        report = get_system_health_report()

        self.assertEqual(report["structure"]["subfactor_count"], 1)

    def test_scale_count_is_correct(self):
        report = get_system_health_report()

        self.assertEqual(report["structure"]["scale_count"], 1)

    def test_question_count_is_correct(self):
        report = get_system_health_report()

        self.assertEqual(report["structure"]["question_count"], 1)

    def test_structurally_incomplete_question_is_detected(self):
        Question.objects.create(
            scale=self.scale,
            item_code="",
            question_text="",
        )

        problem_codes = {
            problem["code"] for problem in get_system_health_report()["problems"]
        }

        self.assertIn("question_empty_item_code", problem_codes)
        self.assertIn("question_empty_text", problem_codes)

    def test_attention_check_without_expected_answer_is_detected(self):
        Question.objects.create(
            scale=self.scale,
            item_code="ATT-MISSING",
            question_text="Attention check",
            is_attention_check=True,
        )

        problems = get_system_health_report()["problems"]
        problem = next(
            item
            for item in problems
            if item["code"] == "attention_check_missing_expected_answer"
        )

        self.assertEqual(problem["severity"], "warning")
        self.assertEqual(problem["count"], 1)

    def test_valid_configuration_generates_no_false_problem(self):
        version = create_normative_version("v-valid-health")
        prepare_normative_version(version)
        activate_normative_version(version)

        report = get_system_health_report()

        self.assertEqual(report["problems"], [])
        self.assertEqual(report["issue_counts"]["total"], 0)

    def test_normative_eligibility_questions_are_located_by_stable_ids(self):
        report = get_system_health_report()
        criteria = {
            criterion["question_id"]: criterion
            for criterion in report["sociodemographic"]["criteria"]
        }

        self.assertTrue(criteria[PORTUGUESE_LANGUAGE_QUESTION_ID]["ready"])
        self.assertTrue(criteria[MENTAL_DIAGNOSIS_QUESTION_ID]["ready"])
        self.assertTrue(
            report["sociodemographic"]["eligibility_configuration_ready"]
        )

    def test_missing_eligibility_question_generates_specific_health_check(self):
        DynamicQuestion.objects.get(
            question_id=PORTUGUESE_LANGUAGE_QUESTION_ID
        ).delete()

        problem_codes = {
            problem["code"] for problem in get_system_health_report()["problems"]
        }

        self.assertIn(
            "normative_eligibility_portuguese_language_question_missing",
            problem_codes,
        )

    def test_valid_active_normative_version_is_recognized(self):
        version = create_normative_version("v-active-health")
        prepare_normative_version(version)
        activate_normative_version(version)

        report = get_system_health_report()

        self.assertEqual(report["normative"]["active_version"].pk, version.pk)
        self.assertEqual(report["normative"]["active_version_count"], 1)
        self.assertNotIn(
            "active_normative_version_without_prepared_at",
            {problem["code"] for problem in report["problems"]},
        )

    def test_simulated_normative_inconsistency_is_detected(self):
        version = create_normative_version("v-corrupt-health")
        NormativeDatasetVersion.objects.filter(pk=version.pk).update(
            status=NormativeDatasetVersion.Status.ACTIVE,
            activated_at=timezone.now(),
            prepared_at=None,
        )

        problems = get_system_health_report()["problems"]
        problem = next(
            item
            for item in problems
            if item["code"] == "active_normative_version_without_prepared_at"
        )

        self.assertEqual(problem["severity"], "error")
        self.assertEqual(problem["count"], 1)

    def test_new_normative_participants_are_information_not_error(self):
        version = create_normative_version("v-new-participant-health")
        prepare_normative_version(version)
        activate_normative_version(version)
        NormativeParticipant.objects.create(age=40, sex="Feminino")

        problems = get_system_health_report()["problems"]
        problem = next(
            item
            for item in problems
            if item["code"] == "normative_participants_not_in_active_version"
        )

        self.assertEqual(problem["severity"], "info")
        self.assertEqual(problem["count"], 1)

    def test_monitoring_pages_do_not_modify_data_or_create_audit_logs(self):
        submission = QuestionnaireSubmission.objects.create(user=self.patient)
        before = {
            "submission": QuestionnaireSubmission.objects.values(
                "completed",
                "is_open",
                "normative_status",
                "normative_exported_at",
            ).get(pk=submission.pk),
            "questions": Question.objects.count(),
            "dynamic_questions": DynamicQuestion.objects.count(),
            "audit_logs": AdministrativeAuditLog.objects.count(),
        }

        monitoring_response = self.client.get(
            reverse("administration:questionnaire_monitoring")
        )
        health_response = self.client.get(reverse("administration:system_health"))

        after = {
            "submission": QuestionnaireSubmission.objects.values(
                "completed",
                "is_open",
                "normative_status",
                "normative_exported_at",
            ).get(pk=submission.pk),
            "questions": Question.objects.count(),
            "dynamic_questions": DynamicQuestion.objects.count(),
            "audit_logs": AdministrativeAuditLog.objects.count(),
        }
        self.assertEqual(monitoring_response.status_code, 200)
        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(after, before)

    def test_absence_of_normative_versions_does_not_cause_server_error(self):
        response = self.client.get(reverse("administration:system_health"))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["normative"]["active_version"])
        self.assertContains(response, "Não existe versão normativa ativa")

    def test_dashboard_contains_both_monitoring_links_for_administrator(self):
        response = self.client.get(reverse("administration:dashboard"))

        self.assertContains(
            response,
            reverse("administration:questionnaire_monitoring"),
        )
        self.assertContains(response, reverse("administration:system_health"))

    def test_monitoring_links_do_not_appear_for_common_users(self):
        self.client.force_login(self.professional)
        professional_response = self.client.get(reverse("website:dashboard"))
        self.client.force_login(self.patient)
        patient_response = self.client.get(reverse("polls:thank_you"))

        for response in (professional_response, patient_response):
            self.assertNotContains(
                response,
                reverse("administration:questionnaire_monitoring"),
            )
            self.assertNotContains(
                response,
                reverse("administration:system_health"),
            )

    def test_dashboard_health_summary_matches_health_report(self):
        Question.objects.create(
            scale=self.scale,
            item_code="ATT-DASH",
            question_text="Dashboard attention check",
            is_attention_check=True,
        )

        expected = get_system_health_report()["issue_counts"]
        response = self.client.get(reverse("administration:dashboard"))

        self.assertEqual(
            response.context["system_health"]["issue_counts"],
            expected,
        )
