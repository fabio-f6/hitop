from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from polls.models import QuestionnaireCollection, QuestionnaireSubmission
from website.models import UserProfile

from .digests import collection_digest_period, queue_collection_digests
from .models import EmailNotification, EmailNotificationPreferences
from .services import (
    deliver_notification,
    deliver_notification_safely,
    notify_professional_approved,
    notify_professional_registration,
    notify_questionnaire_completed,
    queue_notification,
)


TEST_EMAIL_SETTINGS = override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PLATFORM_BASE_URL="https://hitop.test",
)


def make_user(username, role, *, email=None, verified=False, researcher=False, active=True):
    user = User.objects.create_user(
        username=username,
        email=email or f"{username}@hitop.test",
        password="test-password-123",
        is_active=active,
    )
    profile = user.userprofile
    profile.user_type = role
    profile.is_verified = verified
    profile.is_researcher = researcher
    profile.save()
    return user


@TEST_EMAIL_SETTINGS
class NotificationServiceTests(TransactionTestCase):
    reset_sequences = True

    def test_registration_notifies_only_enabled_operational_admin(self):
        enabled = make_user("admin-a", "admin")
        disabled = make_user("admin-b", "admin")
        EmailNotificationPreferences.objects.create(
            user=disabled, professional_registration=False
        )
        professional = make_user("professional", "professional").userprofile

        notify_professional_registration(professional)

        self.assertEqual([message.to for message in mail.outbox], [[enabled.email]])
        self.assertEqual(EmailNotification.objects.count(), 2)

    def test_essential_approval_ignores_general_preference_and_is_idempotent(self):
        professional = make_user("professional", "professional")
        EmailNotificationPreferences.objects.create(
            user=professional, email_notifications_enabled=False
        )
        notify_professional_approved(professional.userprofile)
        notify_professional_approved(professional.userprofile)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [professional.email])

    def test_clinical_completion_routes_to_responsible_professional(self):
        professional = make_user("clinician", "professional", verified=True)
        patient = make_user("patient", "patient")
        patient.userprofile.professional = professional
        patient.userprofile.save(update_fields=["professional"])
        submission = QuestionnaireSubmission.objects.create(
            user=patient, completed=True, completed_at=timezone.now(), is_open=False
        )
        notify_questionnaire_completed(submission)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [professional.email])
        self.assertNotIn("score", mail.outbox[0].body.lower())
        self.assertEqual(len(mail.outbox[0].alternatives), 1)

    def test_collection_test_and_simulation_do_not_create_clinical_email(self):
        researcher = make_user("researcher", "professional", verified=True, researcher=True)
        collection = QuestionnaireCollection.objects.create(owner=researcher, name="Study")
        submission = QuestionnaireSubmission.objects.create(
            collection=collection, participant_number=1, completed=True,
            completed_at=timezone.now(), is_open=False,
        )
        self.assertIsNone(notify_questionnaire_completed(submission))
        self.assertEqual(len(mail.outbox), 0)

    def test_disabled_general_control_cancels_optional_email(self):
        professional = make_user("clinician", "professional", verified=True)
        EmailNotificationPreferences.objects.create(
            user=professional, email_notifications_enabled=False
        )
        patient = make_user("patient", "patient")
        patient.userprofile.professional = professional
        patient.userprofile.save(update_fields=["professional"])
        submission = QuestionnaireSubmission.objects.create(user=patient)
        notify_questionnaire_completed(submission)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(EmailNotification.objects.get().status, EmailNotification.Status.CANCELLED)

    def test_smtp_failure_is_persisted_and_retryable(self):
        professional = make_user("professional", "professional")
        with patch("email_notifications.services.EmailMultiAlternatives.send", side_effect=OSError("offline")):
            notification, _ = notify_professional_approved(professional.userprofile)
        notification.refresh_from_db()
        self.assertEqual(notification.status, EmailNotification.Status.FAILED)
        self.assertEqual(notification.attempts, 1)
        self.assertNotIn("offline", notification.last_error)

        deliver_notification_safely(notification.pk)
        notification.refresh_from_db()
        self.assertEqual(notification.status, EmailNotification.Status.SENT)
        self.assertEqual(notification.attempts, 2)

    def test_rollback_does_not_leave_outbox_row_or_send_email(self):
        professional = make_user("professional", "professional")
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                notify_professional_approved(professional.userprofile)
                raise RuntimeError("rollback")
        self.assertFalse(EmailNotification.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_email_fails_without_calling_smtp(self):
        professional = make_user("professional", "professional", email="invalid")
        notification, _ = notify_professional_approved(professional.userprofile)
        notification.refresh_from_db()
        self.assertEqual(notification.status, EmailNotification.Status.FAILED)
        self.assertEqual(notification.attempts, 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_retry_uses_corrected_account_email(self):
        professional = make_user("professional", "professional")
        professional.email = ""
        professional.save(update_fields=["email"])
        notification, _ = notify_professional_approved(professional.userprofile)
        notification.refresh_from_db()
        self.assertEqual(notification.status, EmailNotification.Status.FAILED)

        professional.email = "corrected@hitop.test"
        professional.save(update_fields=["email"])
        deliver_notification_safely(notification.pk)

        notification.refresh_from_db()
        self.assertEqual(notification.status, EmailNotification.Status.SENT)
        self.assertEqual(notification.recipient_email, "corrected@hitop.test")
        self.assertEqual(mail.outbox[-1].to, ["corrected@hitop.test"])

    def test_deleted_recipient_is_cancelled_on_retry(self):
        professional = make_user("professional", "professional")
        with transaction.atomic():
            notification, _ = queue_notification(
                notification_type=EmailNotification.Type.PROFESSIONAL_APPROVED,
                logical_key="deleted-recipient",
                recipient=professional,
                context={"login_url": "https://hitop.test/"},
            )
            # Keep the callback from running until after the account is gone.
            professional.delete()
        notification.refresh_from_db()
        self.assertEqual(notification.status, EmailNotification.Status.CANCELLED)
        self.assertEqual(len(mail.outbox), 0)


@TEST_EMAIL_SETTINGS
class DigestTests(TransactionTestCase):
    def test_digest_groups_collections_once_and_excludes_test_and_simulated(self):
        owner = make_user("researcher", "professional", verified=True, researcher=True)
        day = date(2026, 10, 14)
        start, _ = collection_digest_period(day)
        first = QuestionnaireCollection.objects.create(owner=owner, name="Estudo A")
        second = QuestionnaireCollection.objects.create(owner=owner, name="Estudo B")
        test_collection = QuestionnaireCollection.objects.create(owner=owner, name="Teste", is_test_data=True)
        for number, collection, mode, is_test in (
            (1, first, "normal", False),
            (2, first, "normal", False),
            (1, second, "normal", False),
            (1, test_collection, "normal", True),
            (3, first, "simulated", False),
        ):
            QuestionnaireSubmission.objects.create(
                collection=collection,
                participant_number=number,
                completed=True,
                completed_at=start,
                is_open=False,
                is_test_data=is_test,
                simulation_mode=mode,
            )
        queue_collection_digests(day)
        queue_collection_digests(day)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Estudo A", mail.outbox[0].body)
        self.assertIn("Novas submissões concluídas: 2", mail.outbox[0].body)
        self.assertNotIn("Teste", mail.outbox[0].body)


@TEST_EMAIL_SETTINGS
class PreferencesViewTests(TestCase):
    def test_user_can_only_edit_own_preferences_and_role_controls_fields(self):
        professional = make_user("professional", "professional", verified=True)
        other = make_user("other", "professional", verified=True)
        self.client.force_login(professional)
        response = self.client.get(reverse("website:notification_preferences"))
        self.assertContains(response, "Questionários concluídos")
        self.assertNotContains(response, "Resumos diários das Coletas Gerais")
        self.client.post(reverse("website:notification_preferences"), {
            "email_notifications_enabled": "on",
        })
        self.assertFalse(professional.email_notification_preferences.questionnaire_completed)
        self.assertFalse(hasattr(other, "email_notification_preferences"))

    def test_researcher_sees_digest_option_and_admin_sees_registration_option(self):
        researcher = make_user("researcher", "professional", verified=True, researcher=True)
        self.client.force_login(researcher)
        response = self.client.get(reverse("website:notification_preferences"))
        self.assertContains(response, "Resumos diários das Coletas Gerais")
        self.client.logout()
        admin = make_user("admin", "admin")
        self.client.force_login(admin)
        response = self.client.get(reverse("website:notification_preferences"))
        self.assertContains(response, "Novos registos profissionais")
        self.assertNotContains(response, "Questionários concluídos")


@TEST_EMAIL_SETTINGS
class EventIntegrationTests(TransactionTestCase):
    def setUp(self):
        self.admin = make_user("admin", "admin")
        self.client.force_login(self.admin)

    def test_approval_and_repeated_post_send_once(self):
        professional = make_user("pending", "professional")
        url = reverse("administration:approve_professional", args=[professional.userprofile.pk])
        self.client.post(url)
        self.client.post(url)
        professional.userprofile.refresh_from_db()
        self.assertTrue(professional.userprofile.is_verified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [professional.email])

    def test_rejection_deactivates_pending_account_and_sends_once(self):
        professional = make_user("pending", "professional")
        url = reverse("administration:reject_professional", args=[professional.userprofile.pk])
        self.client.post(url)
        self.client.post(url)
        professional.refresh_from_db()
        self.assertFalse(professional.is_active)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [professional.email])

    def test_public_registration_notifies_operational_admin(self):
        self.client.logout()
        response = self.client.post(reverse("website:register"), {
            "first_name": "Ana",
            "last_name": "Silva",
            "email": "ana.silva@hitop.test",
            "password1": "A-secure-password-987",
            "password2": "A-secure-password-987",
            "area_formacao": "Psicologia",
            "objetivo_uso": "clinico",
            "cedula_profissional": "CP-123",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.admin.email])
