from django.test import TestCase

from django.contrib.auth.models import User
from django.urls import reverse

from .models import UserProfile


class ProfessionalVerificationTests(TestCase):
    def create_user(self, username, user_type, is_verified=False):
        user = User.objects.create_user(
            username=username,
            password="Uma-palavra-passe-segura-123",
        )
        profile = user.userprofile
        profile.user_type = user_type
        profile.is_verified = is_verified
        profile.save()
        return user

    def test_new_professional_registration_is_pending_and_not_logged_in(self):
        response = self.client.post(
            reverse("website:register"),
            {
                "first_name": "Ana",
                "last_name": "Silva",
                "email": "ana.silva@example.com",
                "password1": "Uma-palavra-passe-segura-123",
                "password2": "Uma-palavra-passe-segura-123",
                "area_formacao": "Psicologia",
                "objetivo_uso": "clinico",
                "cedula_profissional": "12345",
            },
            follow=True,
        )

        user = User.objects.get(username="ana.silva")

        self.assertEqual(user.userprofile.user_type, "professional")
        self.assertFalse(user.userprofile.is_verified)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "aguarda verificação por um administrador")

    def test_duplicate_generated_username_shows_friendly_error_page(self):
        self.create_user("ana.silva", "professional")

        response = self.client.post(
            reverse("website:register"),
            {
                "first_name": "Outra",
                "last_name": "Pessoa",
                "email": "ana.silva@outro-dominio.pt",
                "password1": "Uma-palavra-passe-segura-123",
                "password2": "Uma-palavra-passe-segura-123",
                "area_formacao": "Psicologia",
                "objetivo_uso": "clinico",
                "cedula_profissional": "67890",
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertContains(
            response,
            "Nome de utilizador indisponível",
            status_code=409,
        )
        self.assertEqual(User.objects.filter(username="ana.silva").count(), 1)

    def test_unverified_professional_cannot_log_in(self):
        self.create_user("pending-professional", "professional")

        response = self.client.post(
            reverse("website:home"),
            {
                "username": "pending-professional",
                "password": "Uma-palavra-passe-segura-123",
            },
            follow=True,
        )

        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "aguarda verificação por um administrador")

    def test_unverified_professional_is_logged_out_from_protected_views(self):
        user = self.create_user("pending-professional", "professional")
        self.client.force_login(user)

        response = self.client.get(
            reverse("website:dashboard"),
            follow=True,
        )

        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "aguarda verificação por um administrador")

    def test_verified_professional_can_log_in(self):
        self.create_user(
            "verified-professional",
            "professional",
            is_verified=True,
        )

        response = self.client.post(
            reverse("website:home"),
            {
                "username": "verified-professional",
                "password": "Uma-palavra-passe-segura-123",
            },
        )

        self.assertRedirects(
            response,
            reverse("website:dashboard"),
            fetch_redirect_response=False,
        )
        self.assertIn("_auth_user_id", self.client.session)

    def test_patient_login_is_not_affected_by_verification(self):
        self.create_user("patient", "patient")

        response = self.client.post(
            reverse("website:home"),
            {
                "username": "patient",
                "password": "Uma-palavra-passe-segura-123",
            },
        )

        self.assertRedirects(
            response,
            reverse("polls:questionnaire"),
            fetch_redirect_response=False,
        )

    def test_admin_login_redirects_to_django_admin_dashboard(self):
        admin_user = self.create_user("admin", "admin")
        admin_user.is_staff = True
        admin_user.save()

        response = self.client.post(
            reverse("website:home"),
            {
                "username": "admin",
                "password": "Uma-palavra-passe-segura-123",
            },
        )

        self.assertRedirects(
            response,
            reverse("admin:index"),
            fetch_redirect_response=False,
        )

# Create your tests here.
