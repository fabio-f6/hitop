from unittest.mock import patch

from django.apps import apps
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import resolve, reverse

from polls.models import NormativeDatasetMembership, NormativeParticipant
from polls.normative_versions import (
    activate_normative_version,
    create_normative_version,
    prepare_normative_version,
)
from . import views


class AdministrationAccessTests(TestCase):
    password = "Uma-palavra-passe-segura-123"

    @classmethod
    def setUpTestData(cls):
        cls.administrator = cls.create_user("administrator", "admin")
        cls.professional = cls.create_user(
            "professional",
            "professional",
            is_verified=True,
        )
        cls.patient = cls.create_user("patient", "patient")

    @classmethod
    def create_user(cls, username, user_type, is_verified=False):
        user = User.objects.create_user(
            username=username,
            password=cls.password,
        )
        profile = user.userprofile
        profile.user_type = user_type
        profile.is_verified = is_verified
        profile.save()
        return user

    def test_app_is_installed(self):
        self.assertTrue(apps.is_installed("administration"))

    def test_dashboard_url_resolves_to_administration_view(self):
        match = resolve("/administration/")

        self.assertEqual(match.namespace, "administration")
        self.assertEqual(match.url_name, "dashboard")
        self.assertEqual(match.func, views.dashboard)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("administration:dashboard"))

        self.assertRedirects(response, reverse("website:home"))

    def test_patient_receives_forbidden_response(self):
        self.client.force_login(self.patient)

        response = self.client.get(reverse("administration:dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_professional_receives_forbidden_response(self):
        self.client.force_login(self.professional)

        response = self.client.get(reverse("administration:dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_administrator_can_access_dashboard(self):
        self.client.force_login(self.administrator)

        response = self.client.get(reverse("administration:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "administration/dashboard.html")

    def test_administration_link_appears_for_administrator(self):
        self.client.force_login(self.administrator)

        response = self.client.get(reverse("administration:dashboard"))

        self.assertContains(response, "Administração")
        self.assertContains(response, reverse("administration:dashboard"))

    def test_administration_link_does_not_appear_for_professional(self):
        self.client.force_login(self.professional)

        response = self.client.get(reverse("website:dashboard"))

        self.assertNotContains(response, ">Administração<", html=True)
        self.assertNotContains(response, reverse("administration:dashboard"))

    def test_administration_link_does_not_appear_for_patient(self):
        self.client.force_login(self.patient)

        response = self.client.get(reverse("polls:thank_you"))

        self.assertNotContains(response, ">Administração<", html=True)
        self.assertNotContains(response, reverse("administration:dashboard"))

    def test_administrator_login_redirects_to_operational_dashboard(self):
        response = self.client.post(
            reverse("website:home"),
            {"username": self.administrator.username, "password": self.password},
        )

        self.assertRedirects(
            response,
            reverse("administration:dashboard"),
            fetch_redirect_response=False,
        )

    def test_professional_login_keeps_existing_redirect(self):
        response = self.client.post(
            reverse("website:home"),
            {"username": self.professional.username, "password": self.password},
        )

        self.assertRedirects(
            response,
            reverse("website:dashboard"),
            fetch_redirect_response=False,
        )

    def test_patient_login_keeps_existing_redirect(self):
        response = self.client.post(
            reverse("website:home"),
            {"username": self.patient.username, "password": self.password},
        )

        self.assertRedirects(
            response,
            reverse("polls:questionnaire"),
            fetch_redirect_response=False,
        )

    def test_django_admin_remains_available_to_superusers(self):
        django_superuser = User.objects.create_superuser(
            username="django-superuser",
            password=self.password,
        )
        self.client.force_login(django_superuser)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)

    def test_manual_url_entry_does_not_bypass_authorization(self):
        self.client.force_login(self.professional)

        response = self.client.get("/administration/")

        self.assertEqual(response.status_code, 403)


class AdministrationDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.administrator = User.objects.create_user(username="dashboard-admin")
        cls.administrator.userprofile.user_type = "admin"
        cls.administrator.userprofile.save()

    def setUp(self):
        self.client.force_login(self.administrator)

    def test_professional_totals_use_existing_profile_and_verification_fields(self):
        verified = User.objects.create_user(username="verified-professional")
        verified.userprofile.user_type = "professional"
        verified.userprofile.is_verified = True
        verified.userprofile.save()

        pending = User.objects.create_user(username="pending-professional")
        pending.userprofile.user_type = "professional"
        pending.userprofile.is_verified = False
        pending.userprofile.save()

        response = self.client.get(reverse("administration:dashboard"))

        self.assertEqual(response.context["professional_count"], 2)
        self.assertEqual(response.context["pending_professional_count"], 1)

    def test_dashboard_shows_active_version_and_participant_counts(self):
        participant_ids = [
            self._create_normative_participant(),
            self._create_normative_participant(),
        ]
        version = create_normative_version("v-dashboard")
        prepare_normative_version(version)
        activate_normative_version(version)
        self._create_normative_participant()

        response = self.client.get(reverse("administration:dashboard"))

        self.assertContains(response, "v-dashboard")
        self.assertEqual(response.context["active_normative_version"].pk, version.pk)
        self.assertEqual(response.context["active_normative_participant_count"], 2)
        self.assertEqual(response.context["total_normative_participant_count"], 3)
        self.assertEqual(response.context["unversioned_normative_participant_count"], 1)
        self.assertEqual(
            NormativeDatasetMembership.objects.filter(
                version=version,
                participant_id__in=participant_ids,
            ).count(),
            2,
        )

    def test_absence_of_active_version_shows_clear_empty_state(self):
        self._create_normative_participant()

        response = self.client.get(reverse("administration:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sem versão ativa")
        self.assertEqual(response.context["active_normative_participant_count"], 0)
        self.assertEqual(response.context["total_normative_participant_count"], 1)
        self.assertEqual(response.context["unversioned_normative_participant_count"], 1)

    @patch("administration.views.get_normative_participant_counts")
    @patch("administration.views.get_active_normative_version")
    def test_dashboard_reuses_normative_services(
        self,
        get_active_normative_version,
        get_normative_participant_counts,
    ):
        get_active_normative_version.return_value = None
        get_normative_participant_counts.return_value = {
            "total": 10,
            "active_version": 8,
            "not_in_active_version": 2,
        }

        response = self.client.get(reverse("administration:dashboard"))

        self.assertEqual(response.status_code, 200)
        get_active_normative_version.assert_called_once_with()
        get_normative_participant_counts.assert_called_once_with()
        self.assertEqual(response.context["total_normative_participant_count"], 10)

    @staticmethod
    def _create_normative_participant():
        return NormativeParticipant.objects.create(age=30, sex="Feminino").pk
