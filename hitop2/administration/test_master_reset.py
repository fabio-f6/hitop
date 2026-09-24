from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from django.db.models.deletion import ProtectedError

from polls.models import (
    DynamicAnswer,
    DynamicQuestion,
    NormativeAnswer,
    NormativeDatasetMembership,
    NormativeDatasetVersion,
    NormativeParticipant,
    NormativeScaleScore,
    NormativeSpectrumScore,
    NormativeAnswer,
    Question,
    QuestionCategory,
    QuestionnaireSubmission,
    Scale,
    SociodemographicAnswer,
    Spectra,
    Subfactor,
    UserAnswer,
)
from polls.normative_versions import create_normative_version
from polls.normative_versions import NormativeVersionError

from .master_reset import MasterResetError, perform_master_reset
from .models import AdministrativeAuditLog, MASTER_RESET_ACTION


PASSWORD = "safe-test-password"


class MasterResetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = cls.make_user("actor", "admin", is_staff=True, is_superuser=True)
        cls.second_admin = cls.make_user("second-admin", "admin")
        cls.professional = cls.make_user("professional", "professional")
        cls.patient = cls.make_user("patient", "patient")
        cls.staff_only = cls.make_user("staff-only", "professional", is_staff=True)
        cls.other_superuser = cls.make_user(
            "other-superuser", "professional", is_staff=True, is_superuser=True
        )
        cls.test_user = cls.make_user("test-user", "patient")
        cls.test_user.userprofile.is_test_data = True
        cls.test_user.userprofile.test_environment_owner = cls.actor
        cls.test_user.userprofile.save(
            update_fields=["is_test_data", "test_environment_owner"]
        )

        spectra = Spectra.objects.create(name="Spectrum")
        subfactor = Subfactor.objects.create(name="Subfactor", spectra=spectra)
        scale = Scale.objects.create(name="Scale", subfactor=subfactor)
        question = Question.objects.create(
            scale=scale, item_code="TEST-1", question_text="Test question"
        )
        category = QuestionCategory.objects.create(name="Test category")
        dynamic_question = DynamicQuestion.objects.create(
            category=category,
            question_id="test_dynamic",
            label="Dynamic test question",
            question_type="text",
        )

        participants = NormativeParticipant.objects.bulk_create(
            [NormativeParticipant(age=30) for _ in range(256)]
        )
        cls.v1 = cls.make_version("v1", NormativeDatasetVersion.Status.RETIRED)
        cls.v2 = cls.make_version("v2", NormativeDatasetVersion.Status.RETIRED)
        cls.v3 = cls.make_version("v3", NormativeDatasetVersion.Status.ACTIVE)
        cls.v4 = NormativeDatasetVersion.objects.create(name="v4")
        for version, members in (
            (cls.v1, participants[:255]),
            (cls.v2, participants[:20]),
            (cls.v3, participants[:30]),
            (cls.v4, participants[:40]),
        ):
            NormativeDatasetMembership.objects.bulk_create(
                [
                    NormativeDatasetMembership(version=version, participant=participant)
                    for participant in members
                ]
            )
        for version, participant in (
            (cls.v1, participants[0]),
            (cls.v2, participants[1]),
            (cls.v3, participants[2]),
            (cls.v4, participants[3]),
        ):
            NormativeScaleScore.objects.bulk_create([
                NormativeScaleScore(
                    version=version, participant=participant, scale=scale, raw_score=1
                )
            ])
            NormativeSpectrumScore.objects.bulk_create([
                NormativeSpectrumScore(
                    version=version,
                    participant=participant,
                    spectrum=spectra,
                    raw_score=1,
                )
            ])
        cls.synthetic_participant = NormativeParticipant.objects.create(
            source=NormativeParticipant.Source.SYNTHETIC,
            age=31,
        )
        cls.test_version = create_normative_version(
            "master-reset-test-v1",
            environment=NormativeDatasetVersion.Environment.TEST,
            baseline_version=cls.v1,
        )
        test_now = timezone.now()
        NormativeDatasetVersion.objects.filter(pk=cls.test_version.pk).update(
            status=NormativeDatasetVersion.Status.ACTIVE,
            prepared_at=test_now,
            activated_at=test_now,
        )
        cls.test_version.refresh_from_db()
        NormativeAnswer.objects.create(
            participant=cls.synthetic_participant,
            question=question,
            answer="3",
        )
        NormativeScaleScore.objects.bulk_create([
            NormativeScaleScore(
                version=cls.test_version,
                participant=cls.synthetic_participant,
                scale=scale,
                raw_score=3,
            )
        ])
        NormativeSpectrumScore.objects.bulk_create([
            NormativeSpectrumScore(
                version=cls.test_version,
                participant=cls.synthetic_participant,
                spectrum=spectra,
                raw_score=3,
            )
        ])
        NormativeAnswer.objects.create(
            participant=participants[255], question=question, answer="1"
        )

        cls.actor_submission = QuestionnaireSubmission.objects.create(user=cls.actor)
        cls.completed_submission = QuestionnaireSubmission.objects.create(
            user=cls.patient, completed=True, report_normative_version=cls.v3
        )
        cls.test_submission = QuestionnaireSubmission.objects.create(
            user=cls.test_user, is_test_data=True, simulation_mode="simulated",
            report_normative_version=cls.test_version,
        )
        UserAnswer.objects.create(
            user=cls.actor,
            question=question,
            answer="1",
            submission=cls.actor_submission,
        )
        UserAnswer.objects.create(user=cls.patient, question=question, answer="2")
        DynamicAnswer.objects.create(
            user=cls.patient,
            submission=cls.completed_submission,
            question=dynamic_question,
            answer_value="answer",
        )
        SociodemographicAnswer.objects.create(
            user=cls.patient,
            question_id="age",
            answer_value="30",
            answer_label="Age",
        )

        cls.actor_log = AdministrativeAuditLog.objects.create(
            actor=cls.actor,
            action=AdministrativeAuditLog.Action.NORMATIVE_VERSION_ACTIVATED,
            object_type=AdministrativeAuditLog.ObjectType.NORMATIVE_VERSION,
            object_id=str(cls.v3.pk),
            object_label="v3",
        )
        cls.deleted_actor_log = AdministrativeAuditLog.objects.create(
            actor=cls.second_admin,
            action=AdministrativeAuditLog.Action.PROFESSIONAL_APPROVED,
            object_type=AdministrativeAuditLog.ObjectType.PROFESSIONAL,
            object_id=str(cls.professional.pk),
            object_label="professional",
        )

    @classmethod
    def make_user(cls, username, user_type, **fields):
        user = User.objects.create_user(username, password=PASSWORD, **fields)
        user.userprofile.user_type = user_type
        user.userprofile.save(update_fields=["user_type"])
        return user

    @classmethod
    def make_version(cls, name, status):
        version = NormativeDatasetVersion.objects.create(name=name)
        now = timezone.now()
        NormativeDatasetVersion.objects.filter(pk=version.pk).update(
            status=status, prepared_at=now, activated_at=now
        )
        version.refresh_from_db()
        return version

    def post_reset(self, user=None, **data):
        self.client.force_login(user or self.actor)
        payload = {"confirmation": "MASTER RESET", "password": PASSWORD}
        payload.update(data)
        return self.client.post(reverse("administration:master_reset"), payload)

    def test_visibility_requires_operational_admin_and_staff(self):
        dashboard = reverse("administration:dashboard")
        for user, visible in (
            (self.actor, True),
            (self.second_admin, False),
        ):
            self.client.force_login(user)
            response = self.client.get(dashboard)
            self.assertEqual(response.status_code, 200)
            self.assertEqual("Abrir zona de perigo" in response.content.decode(), visible)

        for user in (self.staff_only, self.professional, self.patient):
            self.client.force_login(user)
            response = self.client.get(dashboard)
            self.assertIn(response.status_code, (302, 403))
            self.assertNotContains(response, "Abrir zona de perigo", status_code=response.status_code)

        self.client.logout()
        response = self.client.get(dashboard)
        self.assertEqual(response.status_code, 302)

    def test_endpoint_rejects_every_unauthorized_role_and_get_never_resets(self):
        initial_users = User.objects.count()
        initial_submissions = QuestionnaireSubmission.objects.count()
        for user in (self.second_admin, self.staff_only, self.professional, self.patient):
            self.client.force_login(user)
            response = self.client.post(
                reverse("administration:master_reset"),
                {"confirmation": "MASTER RESET", "password": PASSWORD},
            )
            self.assertEqual(response.status_code, 403)
        self.client.force_login(self.actor)
        self.assertEqual(self.client.get(reverse("administration:master_reset")).status_code, 200)
        self.assertEqual(User.objects.count(), initial_users)
        self.assertEqual(QuestionnaireSubmission.objects.count(), initial_submissions)

    def test_csrf_is_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor)
        response = client.post(
            reverse("administration:master_reset"),
            {"confirmation": "MASTER RESET", "password": PASSWORD},
        )
        self.assertEqual(response.status_code, 403)

    def test_bad_or_empty_confirmation_and_password_change_nothing(self):
        initial = (User.objects.count(), QuestionnaireSubmission.objects.count())
        for changes in (
            {"confirmation": "master reset"},
            {"confirmation": ""},
            {"password": "wrong"},
            {"password": ""},
        ):
            response = self.post_reset(**changes)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                (User.objects.count(), QuestionnaireSubmission.objects.count()), initial
            )
        self.assertFalse(
            AdministrativeAuditLog.objects.filter(
                action=MASTER_RESET_ACTION
            ).exists()
        )

    def test_success_removes_operational_data_and_preserves_actor(self):
        actor_pk = self.actor.pk
        profile_pk = self.actor.userprofile.pk
        password_hash = self.actor.password
        response = self.post_reset()
        self.assertRedirects(response, reverse("administration:system"))

        actor = User.objects.get(pk=actor_pk)
        self.assertEqual(list(User.objects.values_list("pk", flat=True)), [actor_pk])
        self.assertEqual(actor.userprofile.pk, profile_pk)
        self.assertEqual(actor.userprofile.user_type, "admin")
        self.assertTrue(actor.is_staff)
        self.assertTrue(actor.is_superuser)
        self.assertEqual(actor.password, password_hash)
        self.assertTrue(actor.check_password(PASSWORD))
        self.assertFalse(QuestionnaireSubmission.objects.exists())
        self.assertFalse(UserAnswer.objects.exists())
        self.assertFalse(DynamicAnswer.objects.exists())
        self.assertFalse(SociodemographicAnswer.objects.exists())

    def test_normative_history_and_audit_are_preserved(self):
        version_ids = set(NormativeDatasetVersion.objects.filter(
            environment=NormativeDatasetVersion.Environment.PRODUCTION
        ).values_list("pk", flat=True))
        membership_counts = {
            version.pk: version.memberships.count()
            for version in NormativeDatasetVersion.objects.filter(
                environment=NormativeDatasetVersion.Environment.PRODUCTION
            )
        }
        counts = (
            NormativeParticipant.objects.filter(source="real").count(),
            NormativeAnswer.objects.filter(participant__source="real").count(),
            NormativeScaleScore.objects.filter(version__environment="production").count(),
            NormativeSpectrumScore.objects.filter(version__environment="production").count(),
        )
        with self.assertRaises(ProtectedError):
            NormativeDatasetVersion.objects.filter(pk=self.test_version.pk).delete()
        self.post_reset()

        self.assertEqual(
            set(NormativeDatasetVersion.objects.filter(
                environment=NormativeDatasetVersion.Environment.PRODUCTION
            ).values_list("pk", flat=True)), version_ids
        )
        self.assertFalse(NormativeDatasetVersion.objects.filter(
            environment=NormativeDatasetVersion.Environment.TEST
        ).exists())
        self.assertEqual(
            {
                version.pk: version.memberships.count()
                for version in NormativeDatasetVersion.objects.filter(
                    environment=NormativeDatasetVersion.Environment.PRODUCTION
                )
            },
            membership_counts,
        )
        self.assertEqual(
            (
                NormativeParticipant.objects.count(),
                NormativeAnswer.objects.count(),
                NormativeScaleScore.objects.count(),
                NormativeSpectrumScore.objects.count(),
            ),
            counts,
        )
        self.assertFalse(NormativeParticipant.objects.filter(source="synthetic").exists())
        self.assertFalse(NormativeScaleScore.objects.filter(version__environment="test").exists())
        self.assertFalse(NormativeSpectrumScore.objects.filter(version__environment="test").exists())
        self.v1.refresh_from_db()
        self.v2.refresh_from_db()
        self.v3.refresh_from_db()
        self.v4.refresh_from_db()
        self.assertEqual(self.v1.status, NormativeDatasetVersion.Status.ACTIVE)
        self.assertEqual(self.v2.status, NormativeDatasetVersion.Status.RETIRED)
        self.assertEqual(self.v3.status, NormativeDatasetVersion.Status.RETIRED)
        self.assertEqual(self.v4.status, NormativeDatasetVersion.Status.DRAFT)
        self.assertEqual(
            NormativeDatasetVersion.objects.filter(status="active").count(), 1
        )

        self.assertTrue(AdministrativeAuditLog.objects.filter(pk=self.actor_log.pk).exists())
        deleted_log = AdministrativeAuditLog.objects.get(pk=self.deleted_actor_log.pk)
        self.assertIsNone(deleted_log.actor_id)
        reset_log = AdministrativeAuditLog.objects.get(action="system.master_reset")
        self.assertEqual(reset_log.actor_id, self.actor.pk)
        self.assertEqual(reset_log.object_type, "system")
        self.assertEqual(reset_log.metadata["users_deleted"], 6)
        self.assertEqual(reset_log.metadata["submissions_deleted"], 3)
        self.assertEqual(reset_log.metadata["test_submissions_deleted"], 1)
        self.assertEqual(reset_log.metadata["test_versions_deleted"], 1)
        self.assertEqual(reset_log.metadata["synthetic_participants_deleted"], 1)
        self.assertEqual(reset_log.metadata["previous_active_normative_version"], "v3")
        self.assertEqual(reset_log.metadata["restored_normative_version"], "v1")
        self.assertNotIn("password", str(reset_log.metadata).lower())

    def test_invalid_v1_aborts_before_deletion(self):
        NormativeDatasetMembership.objects.filter(version=self.v4).delete()
        # Historical memberships are protected, so make v1 invalid without
        # invoking protected deletion by adding a 256th member.
        extra = NormativeParticipant.objects.order_by("pk").last()
        NormativeDatasetMembership.objects.bulk_create([
            NormativeDatasetMembership(version=self.v1, participant=extra)
        ])
        before = (User.objects.count(), QuestionnaireSubmission.objects.count())
        with self.assertRaises(MasterResetError):
            perform_master_reset(self.actor)
        self.assertEqual((User.objects.count(), QuestionnaireSubmission.objects.count()), before)
        self.v3.refresh_from_db()
        self.assertEqual(self.v3.status, NormativeDatasetVersion.Status.ACTIVE)

    def test_missing_v1_aborts_before_deletion(self):
        NormativeDatasetVersion.objects.filter(pk=self.v1.pk).update(name="legacy")
        before = (User.objects.count(), QuestionnaireSubmission.objects.count())
        with self.assertRaises(MasterResetError):
            perform_master_reset(self.actor)
        self.assertEqual((User.objects.count(), QuestionnaireSubmission.objects.count()), before)
        self.v3.refresh_from_db()
        self.assertEqual(self.v3.status, NormativeDatasetVersion.Status.ACTIVE)

    def test_reset_cleans_chained_test_versions(self):
        child = NormativeDatasetVersion.objects.create(
            name="test-derived-child", environment="test",
            baseline_version=self.test_version,
        )
        entry = perform_master_reset(self.actor)
        self.assertFalse(NormativeDatasetVersion.objects.filter(pk=child.pk).exists())
        self.assertFalse(NormativeDatasetVersion.objects.filter(environment="test").exists())
        self.assertEqual(entry.metadata["test_versions_deleted"], 2)
        self.assertTrue(User.objects.filter(pk=self.actor.pk).exists())

    def test_unexpected_failure_is_logged_without_sensitive_exception_text(self):
        with patch("administration.views.perform_master_reset", side_effect=RuntimeError("private clinical value")):
            with self.assertLogs("administration.views", level="ERROR") as captured:
                response = self.post_reset()
        self.assertContains(response, "Nenhuma alteração foi aplicada.")
        self.assertIn("RuntimeError", " ".join(captured.output))
        self.assertNotIn("private clinical value", " ".join(captured.output))
        self.assertNotIn(PASSWORD, " ".join(captured.output))

    def test_known_failure_explains_reason_on_page(self):
        NormativeDatasetVersion.objects.filter(pk=self.v1.pk).update(name="legacy")
        with self.assertLogs("administration.views", level="ERROR"):
            response = self.post_reset()
        self.assertContains(response, "A versão normativa original não é identificável.")
        self.assertTrue(User.objects.filter(pk=self.patient.pk).exists())

    def test_cyclic_test_versions_abort_and_restore_deleted_submissions(self):
        child = NormativeDatasetVersion.objects.create(
            name="test-cycle-child", environment="test", baseline_version=self.test_version,
        )
        NormativeDatasetVersion.objects.filter(pk=self.test_version.pk).update(baseline_version=child)
        before = QuestionnaireSubmission.objects.count()
        with self.assertRaisesRegex(RuntimeError, "ciclo"):
            perform_master_reset(self.actor)
        self.assertEqual(QuestionnaireSubmission.objects.count(), before)
        self.assertTrue(User.objects.filter(pk=self.patient.pk).exists())
        self.assertTrue(NormativeDatasetVersion.objects.filter(pk=child.pk).exists())

    def test_failure_during_audit_rolls_back_everything(self):
        before = (
            User.objects.count(),
            QuestionnaireSubmission.objects.count(),
            NormativeDatasetVersion.objects.count(),
            NormativeDatasetMembership.objects.count(),
            NormativeScaleScore.objects.count(),
            NormativeSpectrumScore.objects.count(),
            NormativeParticipant.objects.count(),
            NormativeAnswer.objects.count(),
        )
        with patch(
            "administration.master_reset.record_admin_action",
            side_effect=RuntimeError("forced test failure"),
        ):
            with self.assertRaises(MasterResetError):
                perform_master_reset(self.actor)
        self.assertEqual((
            User.objects.count(),
            QuestionnaireSubmission.objects.count(),
            NormativeDatasetVersion.objects.count(),
            NormativeDatasetMembership.objects.count(),
            NormativeScaleScore.objects.count(),
            NormativeSpectrumScore.objects.count(),
            NormativeParticipant.objects.count(),
            NormativeAnswer.objects.count(),
        ), before)
        self.test_submission.refresh_from_db()
        self.assertEqual(self.test_submission.report_normative_version, self.test_version)
        self.v1.refresh_from_db()
        self.v3.refresh_from_db()
        self.assertEqual(self.v1.status, NormativeDatasetVersion.Status.RETIRED)
        self.assertEqual(self.v3.status, NormativeDatasetVersion.Status.ACTIVE)
        self.assertFalse(
            AdministrativeAuditLog.objects.filter(action="system.master_reset").exists()
        )
