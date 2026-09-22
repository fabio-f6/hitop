from unittest.mock import patch

from django.apps import apps
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import resolve, reverse

from polls.models import (
    NormativeDatasetMembership,
    NormativeParticipant,
    QuestionnaireSubmission,
)
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


class ProfessionalManagementTests(TestCase):
    password = "Uma-palavra-passe-segura-123"

    @classmethod
    def setUpTestData(cls):
        cls.administrator = cls.create_user("management-admin", "admin")
        cls.professional_user = cls.create_user(
            "management-professional",
            "professional",
            is_verified=True,
        )
        cls.patient = cls.create_user("management-patient", "patient")

    @classmethod
    def create_user(cls, username, user_type, is_verified=False, **user_fields):
        user = User.objects.create_user(
            username=username,
            password=cls.password,
            **user_fields,
        )
        profile = user.userprofile
        profile.user_type = user_type
        profile.is_verified = is_verified
        profile.save()
        return user

    def setUp(self):
        self.client.force_login(self.administrator)

    def create_professional(
        self,
        username,
        *,
        is_verified=False,
        is_active=True,
        first_name="Ana",
        last_name="Silva",
        email=None,
        cedula="CP-100",
    ):
        user = self.create_user(
            username,
            "professional",
            is_verified=is_verified,
            first_name=first_name,
            last_name=last_name,
            email=email or f"{username}@example.com",
        )
        user.is_active = is_active
        user.save(update_fields=["is_active"])
        profile = user.userprofile
        profile.area_formacao = "Psicologia"
        profile.objetivo_uso = "clinico"
        profile.cedula_profissional = cedula
        profile.save(
            update_fields=[
                "area_formacao",
                "objetivo_uso",
                "cedula_profissional",
            ]
        )
        return profile

    def test_administrator_can_list_professionals(self):
        professional = self.create_professional("list-professional")

        response = self.client.get(reverse("administration:professionals"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "administration/professionals.html")
        self.assertContains(response, professional.user.email)

    def test_dashboard_links_to_professional_management(self):
        response = self.client.get(reverse("administration:dashboard"))

        self.assertContains(response, "Gerir profissionais")
        self.assertContains(response, reverse("administration:professionals"))

    def test_professional_cannot_access_professional_management(self):
        self.client.force_login(self.professional_user)

        response = self.client.get(reverse("administration:professionals"))

        self.assertEqual(response.status_code, 403)

    def test_patient_cannot_access_professional_management(self):
        self.client.force_login(self.patient)

        response = self.client.get(reverse("administration:professionals"))

        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_is_redirected_to_login(self):
        self.client.logout()

        response = self.client.get(reverse("administration:professionals"))

        self.assertRedirects(response, reverse("website:home"))

    def test_pending_filter_only_shows_pending_active_professionals(self):
        pending = self.create_professional("pending-filter")
        verified = self.create_professional(
            "verified-filter",
            is_verified=True,
        )

        response = self.client.get(
            reverse("administration:professionals"),
            {"status": "pending"},
        )

        self.assertContains(response, pending.user.email)
        self.assertNotContains(response, verified.user.email)

    def test_verified_filter_only_shows_active_verified_professionals(self):
        verified = self.create_professional(
            "verified-only",
            is_verified=True,
        )
        pending = self.create_professional("pending-excluded")
        inactive = self.create_professional(
            "inactive-excluded",
            is_verified=True,
            is_active=False,
        )

        response = self.client.get(
            reverse("administration:professionals"),
            {"status": "verified"},
        )

        self.assertContains(response, verified.user.email)
        self.assertNotContains(response, pending.user.email)
        self.assertNotContains(response, inactive.user.email)

    def test_search_matches_name_email_and_professional_number(self):
        target = self.create_professional(
            "search-target",
            first_name="Madalena",
            last_name="Ferreira",
            email="distinctive-address@example.com",
            cedula="CEDULA-7788",
        )
        other = self.create_professional("search-other", cedula="OTHER-1")

        for query in (
            "Madalena Ferreira",
            "distinctive-address",
            "CEDULA-7788",
        ):
            with self.subTest(query=query):
                response = self.client.get(
                    reverse("administration:professionals"),
                    {"q": query},
                )
                self.assertContains(response, target.user.email)
                self.assertNotContains(response, other.user.email)

    def test_detail_shows_the_requested_professional_registration(self):
        professional = self.create_professional(
            "detail-professional",
            first_name="Rita",
            last_name="Costa",
            email="rita.costa@example.com",
            cedula="PSI-4455",
        )

        response = self.client.get(
            reverse(
                "administration:professional_detail",
                args=[professional.pk],
            )
        )

        self.assertEqual(response.context["professional"], professional)
        self.assertContains(response, "Rita Costa")
        self.assertContains(response, "rita.costa@example.com")
        self.assertContains(response, "PSI-4455")
        self.assertContains(response, "Psicologia")
        self.assertContains(response, "Avaliação em contexto clínico")

    def test_professional_cannot_open_another_professionals_detail(self):
        target = self.create_professional("protected-detail")
        self.client.force_login(self.professional_user)

        response = self.client.get(
            reverse(
                "administration:professional_detail",
                args=[target.pk],
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_administrator_can_approve_pending_professional(self):
        professional = self.create_professional("approve-professional")

        response = self.client.post(
            reverse(
                "administration:approve_professional",
                args=[professional.pk],
            )
        )

        self.assertRedirects(
            response,
            reverse(
                "administration:professional_detail",
                args=[professional.pk],
            ),
        )
        professional.refresh_from_db()
        self.assertTrue(professional.is_verified)

    def test_approval_rechecks_and_preserves_already_verified_professional(self):
        professional = self.create_professional(
            "already-approved",
            is_verified=True,
        )

        response = self.client.post(
            reverse(
                "administration:approve_professional",
                args=[professional.pk],
            ),
            follow=True,
        )

        professional.refresh_from_db()
        self.assertTrue(professional.is_verified)
        self.assertContains(response, "já se encontra aprovado")

    def test_approval_requires_post(self):
        professional = self.create_professional("post-required")

        response = self.client.get(
            reverse(
                "administration:approve_professional",
                args=[professional.pk],
            )
        )

        self.assertEqual(response.status_code, 405)
        professional.refresh_from_db()
        self.assertFalse(professional.is_verified)

    def test_professional_cannot_call_approval_endpoint_directly(self):
        pending = self.create_professional("protected-approval")
        self.client.force_login(self.professional_user)

        response = self.client.post(
            reverse(
                "administration:approve_professional",
                args=[pending.pk],
            )
        )

        self.assertEqual(response.status_code, 403)
        pending.refresh_from_db()
        self.assertFalse(pending.is_verified)

    def test_approved_professional_can_use_existing_login_flow(self):
        professional = self.create_professional("login-after-approval")
        self.client.post(
            reverse(
                "administration:approve_professional",
                args=[professional.pk],
            )
        )
        self.client.logout()

        response = self.client.post(
            reverse("website:home"),
            {
                "username": professional.user.username,
                "password": self.password,
            },
        )

        self.assertRedirects(
            response,
            reverse("website:dashboard"),
            fetch_redirect_response=False,
        )

    def test_professional_list_is_paginated(self):
        for index in range(11):
            self.create_professional(f"paginated-{index:02d}")

        first_page = self.client.get(reverse("administration:professionals"))
        second_page = self.client.get(
            reverse("administration:professionals"),
            {"page": 2},
        )

        self.assertEqual(first_page.context["page_obj"].paginator.per_page, 10)
        self.assertEqual(first_page.context["page_obj"].paginator.num_pages, 2)
        self.assertEqual(len(first_page.context["professionals"]), 10)
        self.assertEqual(len(second_page.context["professionals"]), 2)

    def test_list_and_detail_do_not_expose_patient_or_clinical_information(self):
        professional = self.create_professional("privacy-professional")
        patient = self.create_user(
            "private-patient-name",
            "patient",
        )
        patient.userprofile.professional = professional.user
        patient.userprofile.save(update_fields=["professional"])
        QuestionnaireSubmission.objects.create(
            user=patient,
            title="Sensitive clinical assessment",
        )

        list_response = self.client.get(reverse("administration:professionals"))
        detail_response = self.client.get(
            reverse(
                "administration:professional_detail",
                args=[professional.pk],
            )
        )

        for response in (list_response, detail_response):
            self.assertNotContains(response, "private-patient-name")
            self.assertNotContains(response, "Sensitive clinical assessment")

    def test_deactivation_requires_explicit_confirmation_and_post(self):
        professional = self.create_professional(
            "deactivation-confirmation",
            is_verified=True,
        )
        url = reverse(
            "administration:deactivate_professional",
            args=[professional.pk],
        )

        confirmation = self.client.get(url)
        professional.user.refresh_from_db()

        self.assertEqual(confirmation.status_code, 200)
        self.assertTemplateUsed(
            confirmation,
            "administration/confirm_professional_deactivation.html",
        )
        self.assertContains(confirmation, "Confirmar retirada de acesso")
        self.assertTrue(professional.user.is_active)

        self.client.post(url)
        professional.refresh_from_db()
        professional.user.refresh_from_db()

        self.assertTrue(professional.is_verified)
        self.assertFalse(professional.user.is_active)

    def test_deactivated_professional_can_no_longer_log_in(self):
        professional = self.create_professional(
            "deactivated-login",
            is_verified=True,
        )
        self.client.post(
            reverse(
                "administration:deactivate_professional",
                args=[professional.pk],
            )
        )
        self.client.logout()

        response = self.client.post(
            reverse("website:home"),
            {
                "username": professional.user.username,
                "password": self.password,
            },
        )

        self.assertRedirects(response, reverse("website:home"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_pending_professional_cannot_be_deactivated_as_rejection(self):
        professional = self.create_professional("pending-not-rejected")

        response = self.client.post(
            reverse(
                "administration:deactivate_professional",
                args=[professional.pk],
            ),
            follow=True,
        )

        professional.refresh_from_db()
        professional.user.refresh_from_db()
        self.assertTrue(professional.user.is_active)
        self.assertFalse(professional.is_verified)
        self.assertContains(
            response,
            "apenas a profissionais já aprovados",
        )

    def test_professional_cannot_call_deactivation_endpoint_directly(self):
        professional = self.create_professional(
            "protected-deactivation",
            is_verified=True,
        )
        self.client.force_login(self.professional_user)

        response = self.client.post(
            reverse(
                "administration:deactivate_professional",
                args=[professional.pk],
            )
        )

        self.assertEqual(response.status_code, 403)
        professional.user.refresh_from_db()
        self.assertTrue(professional.user.is_active)
