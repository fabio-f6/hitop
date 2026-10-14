from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from polls.models import (
    NormativeDatasetVersion,
    QuestionnaireCollection,
    QuestionnaireSubmission,
    Question,
    Scale,
    Spectra,
    Subfactor,
)
from administration.models import AdministrativeAuditLog


class QuestionnaireCollectionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="secret")
        profile = self.owner.userprofile
        profile.user_type = "professional"
        profile.is_verified = True
        profile.is_researcher = True
        profile.save()
        self.other = User.objects.create_user(username="other", password="secret")
        other_profile = self.other.userprofile
        other_profile.user_type = "professional"
        other_profile.is_verified = True
        other_profile.save()
        self.spectrum = Spectra.objects.create(name="Internalizing")
        subfactor = Subfactor.objects.create(name="Distress", spectra=self.spectrum)
        scale = Scale.objects.create(name="Example", subfactor=subfactor)
        Question.objects.create(
            scale=scale, item_code="COL_TEST_1", question_text="Example?",
        )
        version = NormativeDatasetVersion.objects.create(
            name="active-test-version",
            environment=NormativeDatasetVersion.Environment.PRODUCTION,
        )
        NormativeDatasetVersion.objects.filter(pk=version.pk).update(
            status=NormativeDatasetVersion.Status.ACTIVE,
            prepared_at=timezone.now(),
            activated_at=timezone.now(),
        )
        self.collection = QuestionnaireCollection.objects.create(
            owner=self.owner, name="Estudo HiTOP 2026",
        )
        self.collection.spectra.add(self.spectrum)

    def public_url(self):
        return reverse("website:collection_public", args=[self.collection.public_token])

    def start_url(self):
        return reverse("website:collection_start", args=[self.collection.public_token])

    def test_public_get_does_not_create_submission(self):
        response = self.client.get(self.public_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(QuestionnaireSubmission.objects.count(), 0)

    def test_verified_professional_can_create_collection(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("website:collection_create"), {
            "name": "Recolha Universitária",
            "spectra": [self.spectrum.pk],
        })
        created = QuestionnaireCollection.objects.get(name="Recolha Universitária")
        self.assertRedirects(
            response, reverse("website:collection_detail", args=[created.pk])
        )
        self.assertEqual(created.owner, self.owner)
        self.assertTrue(created.public_token)

    def test_start_is_anonymous_and_idempotent_in_same_session(self):
        users_before = User.objects.count()
        self.client.post(self.start_url())
        self.client.post(self.start_url())
        submission = QuestionnaireSubmission.objects.get()
        self.assertIsNone(submission.user_id)
        self.assertEqual(submission.collection, self.collection)
        self.assertEqual(submission.participant_number, 1)
        self.assertEqual(list(submission.spectra.all()), [self.spectrum])
        self.assertEqual(User.objects.count(), users_before)

    def test_independent_clients_create_independent_participants_and_keep_link(self):
        token = self.collection.public_token
        Client().post(self.start_url())
        Client().post(self.start_url())
        self.assertEqual(
            list(self.collection.submissions.order_by("participant_number").values_list(
                "participant_number", flat=True
            )),
            [1, 2],
        )
        self.collection.refresh_from_db()
        self.assertEqual(self.collection.public_token, token)

    def test_inactive_collection_blocks_new_but_preserves_existing(self):
        self.collection.is_active = False
        self.collection.save()
        response = self.client.post(self.start_url())
        self.assertRedirects(response, self.public_url())
        self.assertFalse(QuestionnaireSubmission.objects.exists())
        token = self.collection.public_token
        profile = self.owner.userprofile
        profile.is_researcher = False
        profile.save(update_fields=["is_researcher"])
        profile.is_researcher = True
        profile.save(update_fields=["is_researcher"])
        self.collection.refresh_from_db()
        self.assertFalse(self.collection.is_active)
        self.collection.is_active = True
        self.collection.save()
        self.assertEqual(self.collection.public_token, token)

    def test_owner_permissions_are_enforced(self):
        self.other.userprofile.is_researcher = True
        self.other.userprofile.save(update_fields=["is_researcher"])
        self.client.force_login(self.other)
        response = self.client.get(
            reverse("website:collection_detail", args=[self.collection.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_non_researcher_cannot_open_any_private_collection_endpoint(self):
        self.client.force_login(self.other)
        submission = QuestionnaireSubmission.objects.create(
            collection=self.collection, participant_number=1, completed=True,
        )
        for url in (
            reverse("website:collection_list"),
            reverse("website:collection_create"),
            reverse("website:collection_detail", args=[self.collection.pk]),
            reverse("website:collection_report_preview", args=[submission.pk]),
            reverse("website:collection_report_export", args=[submission.pk]),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(
            self.client.post(
                reverse("website:collection_toggle", args=[self.collection.pk])
            ).status_code,
            403,
        )

    def test_navbar_only_shows_collections_to_authorized_researcher(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse("website:dashboard"))
        self.assertNotContains(response, "Coletas Gerais")
        profile = self.other.userprofile
        profile.is_researcher = True
        profile.save(update_fields=["is_researcher"])
        response = self.client.get(reverse("website:dashboard"))
        self.assertContains(response, "Coletas Gerais")

    def test_revocation_blocks_start_and_resume_without_deleting_data(self):
        self.client.post(self.start_url())
        submission = QuestionnaireSubmission.objects.get(collection=self.collection)
        token = self.collection.public_token
        profile = self.owner.userprofile
        profile.is_researcher = False
        profile.save(update_fields=["is_researcher"])

        self.assertEqual(self.client.get(reverse("polls:sociodemographic")).status_code, 403)
        response = Client().get(self.public_url())
        self.assertContains(response, "Esta coleta não está disponível neste momento.")
        self.assertNotContains(response, "permiss")
        Client().post(self.start_url())
        self.assertEqual(self.collection.submissions.count(), 1)
        self.assertTrue(QuestionnaireSubmission.objects.filter(pk=submission.pk).exists())

        profile.is_researcher = True
        profile.save(update_fields=["is_researcher"])
        self.collection.refresh_from_db()
        self.assertEqual(self.collection.public_token, token)
        self.assertNotEqual(
            self.client.get(reverse("polls:sociodemographic")).status_code,
            403,
        )

    def test_pending_researcher_cannot_use_collections(self):
        profile = self.owner.userprofile
        profile.is_verified = False
        profile.save(update_fields=["is_verified"])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("website:collection_list")).status_code, 403)
        self.assertFalse(Client().get(self.public_url()).context["collection_available"])

    def test_operational_admin_can_grant_and_revoke_with_audit(self):
        administrator = User.objects.create_user(username="operational-admin")
        administrator.userprofile.user_type = "admin"
        administrator.userprofile.save(update_fields=["user_type"])
        self.client.force_login(administrator)
        url = reverse(
            "administration:update_professional_researcher",
            args=[self.other.userprofile.pk],
        )
        self.client.post(url, {"is_researcher": "on"})
        self.other.userprofile.refresh_from_db()
        self.assertTrue(self.other.userprofile.is_researcher)
        self.assertTrue(AdministrativeAuditLog.objects.filter(
            action=AdministrativeAuditLog.Action.PROFESSIONAL_RESEARCHER_GRANTED,
            actor=administrator,
            object_id=str(self.other.userprofile.pk),
        ).exists())

        self.client.post(url, {})
        self.other.userprofile.refresh_from_db()
        self.assertFalse(self.other.userprofile.is_researcher)
        self.assertTrue(AdministrativeAuditLog.objects.filter(
            action=AdministrativeAuditLog.Action.PROFESSIONAL_RESEARCHER_REVOKED,
            actor=administrator,
            object_id=str(self.other.userprofile.pk),
        ).exists())

    def test_professional_cannot_grant_researcher_to_self(self):
        self.client.force_login(self.other)
        response = self.client.post(
            reverse(
                "administration:update_professional_researcher",
                args=[self.other.userprofile.pk],
            ),
            {"is_researcher": "on"},
        )
        self.assertEqual(response.status_code, 403)
        self.other.userprofile.refresh_from_db()
        self.assertFalse(self.other.userprofile.is_researcher)

    def test_researcher_defaults_false_and_grants_no_admin_privileges(self):
        user = User.objects.create_user(username="default-professional")
        self.assertFalse(user.userprofile.is_researcher)
        user.userprofile.user_type = "professional"
        user.userprofile.is_verified = True
        user.userprofile.is_researcher = True
        user.userprofile.save()
        user.refresh_from_db()
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.client.force_login(user)
        self.assertEqual(
            self.client.get(reverse("administration:dashboard")).status_code,
            403,
        )

    def test_submission_origin_constraint_rejects_patient_and_collection(self):
        patient = User.objects.create_user(username="patient")
        with self.assertRaises(IntegrityError), transaction.atomic():
            QuestionnaireSubmission.objects.create(
                user=patient,
                collection=self.collection,
                participant_number=1,
            )
