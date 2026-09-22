import json
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django.urls import NoReverseMatch, reverse

from polls.models import NormativeDatasetVersion
from polls.normative_versions import (
    create_normative_version,
    prepare_normative_version,
)

from .audit import record_admin_action
from .models import AdministrativeAuditLog


class AuditTestMixin:
    password = "Uma-palavra-passe-segura-123"

    @classmethod
    def create_user(cls, username, user_type, **user_fields):
        user = User.objects.create_user(
            username=username,
            password=cls.password,
            **user_fields,
        )
        user.userprofile.user_type = user_type
        user.userprofile.save(update_fields=["user_type"])
        return user

    def record_professional_approval(
        self,
        *,
        actor,
        object_id="1",
        label="Profissional de teste",
    ):
        return record_admin_action(
            actor=actor,
            action=AdministrativeAuditLog.Action.PROFESSIONAL_APPROVED,
            object_type=AdministrativeAuditLog.ObjectType.PROFESSIONAL,
            object_id=object_id,
            object_label=label,
            metadata={
                "previous_is_verified": False,
                "new_is_verified": True,
            },
        )


class AdministrativeAuditServiceTests(AuditTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.administrator = cls.create_user("audit-service-admin", "admin")

    def test_service_creates_log_with_actor_action_and_metadata(self):
        entry = self.record_professional_approval(actor=self.administrator)

        entry.refresh_from_db()
        self.assertEqual(entry.actor, self.administrator)
        self.assertEqual(
            entry.action,
            AdministrativeAuditLog.Action.PROFESSIONAL_APPROVED,
        )
        self.assertEqual(
            entry.metadata,
            {
                "previous_is_verified": False,
                "new_is_verified": True,
            },
        )
        self.assertEqual(entry.result, AdministrativeAuditLog.Result.SUCCESS)

    def test_service_rejects_unexpected_or_sensitive_metadata(self):
        with self.assertRaises(ValidationError):
            record_admin_action(
                actor=self.administrator,
                action=AdministrativeAuditLog.Action.PROFESSIONAL_APPROVED,
                object_type=AdministrativeAuditLog.ObjectType.PROFESSIONAL,
                object_id="99",
                object_label="Profissional",
                metadata={"access_token": "secret-token"},
            )

        self.assertFalse(AdministrativeAuditLog.objects.exists())

    def test_saved_log_cannot_be_changed_or_deleted_through_model_instance(self):
        entry = self.record_professional_approval(actor=self.administrator)
        entry.object_label = "Descrição alterada"

        with self.assertRaises(ValidationError):
            entry.save()
        with self.assertRaises(ValidationError):
            entry.delete()

        entry.refresh_from_db()
        self.assertEqual(entry.object_label, "Profissional de teste")

    def test_removing_affected_object_preserves_audit_history(self):
        professional = self.create_user("removed-professional", "professional")
        entry = self.record_professional_approval(
            actor=self.administrator,
            object_id=professional.userprofile.pk,
            label=professional.username,
        )

        professional.delete()

        entry.refresh_from_db()
        self.assertEqual(entry.object_label, "removed-professional")

    def test_removing_actor_sets_actor_to_null_and_preserves_history(self):
        entry = self.record_professional_approval(actor=self.administrator)

        self.administrator.delete()

        entry.refresh_from_db()
        self.assertIsNone(entry.actor)

    def test_normative_object_has_no_cascade_relationship_to_audit_log(self):
        version = create_normative_version("v-removable-audit-object")
        entry = record_admin_action(
            actor=self.administrator,
            action=AdministrativeAuditLog.Action.NORMATIVE_VERSION_CREATED,
            object_type=AdministrativeAuditLog.ObjectType.NORMATIVE_VERSION,
            object_id=version.pk,
            object_label=version.name,
            metadata={
                "new_status": version.status,
                "participant_count": 0,
            },
        )

        version.delete()

        self.assertTrue(
            AdministrativeAuditLog.objects.filter(pk=entry.pk).exists()
        )


class AdministrativeActionAuditTests(AuditTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.administrator = cls.create_user("action-audit-admin", "admin")

    def setUp(self):
        self.client.force_login(self.administrator)

    def create_professional(self, username, *, verified=False):
        professional = self.create_user(
            username,
            "professional",
            email=f"{username}@example.com",
        )
        professional.userprofile.is_verified = verified
        professional.userprofile.save(update_fields=["is_verified"])
        return professional.userprofile

    def test_professional_approval_creates_exactly_one_log(self):
        professional = self.create_professional("audited-approval")
        url = reverse(
            "administration:approve_professional",
            args=[professional.pk],
        )

        self.client.post(url)

        entries = AdministrativeAuditLog.objects.filter(
            action=AdministrativeAuditLog.Action.PROFESSIONAL_APPROVED,
            object_id=str(professional.pk),
        )
        self.assertEqual(entries.count(), 1)
        entry = entries.get()
        self.assertEqual(entry.actor, self.administrator)
        self.assertEqual(
            entry.metadata,
            {
                "previous_is_verified": False,
                "new_is_verified": True,
            },
        )

    def test_repeated_approval_does_not_create_false_logs(self):
        professional = self.create_professional("repeated-approval")
        url = reverse(
            "administration:approve_professional",
            args=[professional.pk],
        )

        self.client.post(url)
        self.client.post(url)

        self.assertEqual(
            AdministrativeAuditLog.objects.filter(
                action=AdministrativeAuditLog.Action.PROFESSIONAL_APPROVED,
                object_id=str(professional.pk),
            ).count(),
            1,
        )

    def test_professional_access_revocation_creates_exactly_one_log(self):
        professional = self.create_professional(
            "audited-revocation",
            verified=True,
        )
        url = reverse(
            "administration:deactivate_professional",
            args=[professional.pk],
        )

        self.client.post(url)

        entry = AdministrativeAuditLog.objects.get(
            action=AdministrativeAuditLog.Action.PROFESSIONAL_ACCESS_REVOKED,
            object_id=str(professional.pk),
        )
        self.assertEqual(entry.actor, self.administrator)
        self.assertEqual(
            entry.metadata,
            {
                "previous_is_active": True,
                "new_is_active": False,
            },
        )

    def test_normative_version_creation_through_panel_creates_log(self):
        self.client.post(
            reverse("administration:create_normative_version"),
            {"name": "v-audited-creation"},
        )

        version = NormativeDatasetVersion.objects.get(name="v-audited-creation")
        entry = AdministrativeAuditLog.objects.get(
            action=AdministrativeAuditLog.Action.NORMATIVE_VERSION_CREATED,
            object_id=str(version.pk),
        )
        self.assertEqual(entry.actor, self.administrator)
        self.assertEqual(entry.metadata["new_status"], "draft")
        self.assertEqual(entry.metadata["participant_count"], 0)

    def test_normative_version_preparation_logs_only_after_success(self):
        version = create_normative_version("v-audited-preparation")

        self.client.post(
            reverse(
                "administration:prepare_normative_version",
                args=[version.pk],
            )
        )

        version.refresh_from_db()
        entry = AdministrativeAuditLog.objects.get(
            action=AdministrativeAuditLog.Action.NORMATIVE_VERSION_PREPARED,
            object_id=str(version.pk),
        )
        self.assertIsNotNone(version.prepared_at)
        self.assertEqual(entry.metadata["participant_count"], 0)
        self.assertFalse(entry.metadata["previously_prepared"])

    def test_normative_version_activation_logs_previous_active_version(self):
        previous = create_normative_version("v-previous-active")
        prepare_normative_version(previous)
        from polls.normative_versions import activate_normative_version

        activate_normative_version(previous)
        version = create_normative_version("v-audited-activation")
        prepare_normative_version(version)

        self.client.post(
            reverse(
                "administration:activate_normative_version",
                args=[version.pk],
            )
        )

        entry = AdministrativeAuditLog.objects.get(
            action=AdministrativeAuditLog.Action.NORMATIVE_VERSION_ACTIVATED,
            object_id=str(version.pk),
        )
        self.assertEqual(entry.metadata["previous_status"], "draft")
        self.assertEqual(entry.metadata["new_status"], "active")
        self.assertEqual(
            entry.metadata["previous_active_version_id"],
            previous.pk,
        )
        self.assertEqual(
            entry.metadata["previous_active_version_label"],
            previous.name,
        )

    def test_failed_preparation_does_not_create_success_log(self):
        version = create_normative_version("v-failed-preparation")

        with patch(
            "administration.views.prepare_normative_version_service",
            side_effect=ValidationError("Falha controlada."),
        ):
            response = self.client.post(
                reverse(
                    "administration:prepare_normative_version",
                    args=[version.pk],
                )
            )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            AdministrativeAuditLog.objects.filter(
                action=AdministrativeAuditLog.Action.NORMATIVE_VERSION_PREPARED,
                object_id=str(version.pk),
            ).exists()
        )

    def test_unprepared_activation_does_not_create_false_log(self):
        version = create_normative_version("v-invalid-activation-audit")

        self.client.post(
            reverse(
                "administration:activate_normative_version",
                args=[version.pk],
            )
        )

        self.assertFalse(
            AdministrativeAuditLog.objects.filter(
                action=AdministrativeAuditLog.Action.NORMATIVE_VERSION_ACTIVATED,
                object_id=str(version.pk),
            ).exists()
        )

    def test_audit_failure_rolls_back_the_primary_operation(self):
        professional = self.create_professional("audit-write-failure")

        with patch(
            "administration.views.record_admin_action",
            side_effect=RuntimeError("Audit storage unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse(
                        "administration:approve_professional",
                        args=[professional.pk],
                    )
                )

        professional.refresh_from_db()
        self.assertFalse(professional.is_verified)
        self.assertFalse(AdministrativeAuditLog.objects.exists())

    def test_real_logs_contain_no_clinical_answers_or_access_tokens(self):
        professional = self.create_professional("privacy-audit")
        self.client.post(
            reverse(
                "administration:approve_professional",
                args=[professional.pk],
            )
        )

        entry = AdministrativeAuditLog.objects.get()
        stored_content = json.dumps(entry.metadata) + entry.object_label
        self.assertNotIn("access_token", stored_content)
        self.assertNotIn("questionnaire", stored_content)
        self.assertCountEqual(
            entry.metadata,
            ("previous_is_verified", "new_is_verified"),
        )


class AdministrativeAuditPageTests(AuditTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.administrator = cls.create_user("audit-page-admin", "admin")
        cls.second_administrator = cls.create_user("second-audit-admin", "admin")
        cls.professional = cls.create_user("audit-page-professional", "professional")
        cls.patient = cls.create_user("audit-page-patient", "patient")

    def setUp(self):
        self.client.force_login(self.administrator)

    def test_administrator_can_consult_audit_page(self):
        response = self.client.get(reverse("administration:audit"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "administration/audit.html")

    def test_professional_cannot_consult_audit_page(self):
        self.client.force_login(self.professional)

        response = self.client.get(reverse("administration:audit"))

        self.assertEqual(response.status_code, 403)

    def test_patient_cannot_consult_audit_page(self):
        self.client.force_login(self.patient)

        response = self.client.get(reverse("administration:audit"))

        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_is_redirected_to_login(self):
        self.client.logout()

        response = self.client.get(reverse("administration:audit"))

        self.assertRedirects(response, reverse("website:home"))

    def test_logs_are_ordered_from_newest_to_oldest(self):
        older = self.record_professional_approval(
            actor=self.administrator,
            object_id="older",
            label="Registo antigo",
        )
        newer = self.record_professional_approval(
            actor=self.administrator,
            object_id="newer",
            label="Registo recente",
        )

        response = self.client.get(reverse("administration:audit"))

        self.assertEqual(
            list(response.context["audit_logs"]),
            [newer, older],
        )

    def test_audit_list_is_paginated(self):
        for index in range(21):
            self.record_professional_approval(
                actor=self.administrator,
                object_id=index,
                label=f"Profissional {index:02d}",
            )

        first_page = self.client.get(reverse("administration:audit"))
        second_page = self.client.get(
            reverse("administration:audit"),
            {"page": 2},
        )

        self.assertEqual(first_page.context["page_obj"].paginator.per_page, 20)
        self.assertEqual(len(first_page.context["audit_logs"]), 20)
        self.assertEqual(len(second_page.context["audit_logs"]), 1)

    def test_action_actor_and_object_label_filters_work_together(self):
        expected = self.record_professional_approval(
            actor=self.second_administrator,
            object_id="target",
            label="Madalena Ferreira",
        )
        self.record_professional_approval(
            actor=self.administrator,
            object_id="other",
            label="Outro profissional",
        )

        response = self.client.get(
            reverse("administration:audit"),
            {
                "action": AdministrativeAuditLog.Action.PROFESSIONAL_APPROVED,
                "actor": self.second_administrator.pk,
                "period": "7",
                "q": "Madalena",
            },
        )

        self.assertEqual(list(response.context["audit_logs"]), [expected])

    def test_list_does_not_render_raw_metadata(self):
        record_admin_action(
            actor=self.administrator,
            action=AdministrativeAuditLog.Action.NORMATIVE_VERSION_CREATED,
            object_type=AdministrativeAuditLog.ObjectType.NORMATIVE_VERSION,
            object_id="37",
            object_label="v37",
            metadata={
                "new_status": "draft",
                "participant_count": 287,
            },
        )

        response = self.client.get(reverse("administration:audit"))

        self.assertNotContains(response, "participant_count")
        self.assertNotContains(response, "287")

    def test_interface_has_no_edit_or_delete_routes_and_rejects_post(self):
        with self.assertRaises(NoReverseMatch):
            reverse("administration:audit_edit", args=[1])
        with self.assertRaises(NoReverseMatch):
            reverse("administration:audit_delete", args=[1])

        response = self.client.post(reverse("administration:audit"))
        self.assertEqual(response.status_code, 405)

    def test_dashboard_links_to_audit_page(self):
        response = self.client.get(reverse("administration:dashboard"))

        self.assertContains(response, "Auditoria")
        self.assertContains(response, reverse("administration:audit"))


class AdministrativeAuditDjangoAdminTests(AuditTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username="audit-superuser",
            password=cls.password,
        )

    def test_django_admin_registration_is_read_only(self):
        model_admin = admin.site._registry[AdministrativeAuditLog]
        request = RequestFactory().get("/admin/administration/audit/")
        request.user = self.superuser

        self.assertTrue(model_admin.has_view_permission(request))
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))
        self.assertCountEqual(
            model_admin.get_readonly_fields(request),
            (
                "id",
                "actor",
                "action",
                "object_type",
                "object_id",
                "object_label",
                "result",
                "metadata",
                "created_at",
            ),
        )
