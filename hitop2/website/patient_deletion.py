from django.db import transaction

from polls.models import (
    DynamicAnswer,
    QuestionnaireSubmission,
    SociodemographicAnswer,
    UserAnswer,
)

from .models import UserProfile


class PatientDeletionBlocked(Exception):
    """Raised when a patient does not satisfy the permanent-deletion rules."""


class ActivePatientDeletionBlocked(PatientDeletionBlocked):
    pass


class PendingNormativeStatusBlocked(PatientDeletionBlocked):
    pass


@transaction.atomic
def permanently_delete_patient(*, patient_id, professional):
    """Delete one professional's archived clinical patient atomically.

    Normative models are deliberately absent from this operation. Exported
    normative records are independent copies and therefore remain intact.
    """
    patient_profile = UserProfile.objects.select_for_update().get(
        id=patient_id,
        user_type="patient",
        professional=professional,
    )
    if patient_profile.archived_at is None:
        raise ActivePatientDeletionBlocked

    patient = patient_profile.user
    submissions = QuestionnaireSubmission.objects.filter(
        user=patient,
    )
    # Evaluate every submission while holding row locks. One pending record is
    # enough to prevent any clinical object from being deleted.
    normative_statuses = list(
        submissions.select_for_update().values_list("normative_status", flat=True)
    )
    if QuestionnaireSubmission.NormativeStatus.PENDING in normative_statuses:
        raise PendingNormativeStatusBlocked

    # Delete submission-owned rows via their declared CASCADE relationships,
    # then remove any legacy/unattached clinical answers owned by the patient.
    submissions.delete()
    UserAnswer.objects.filter(user=patient).delete()
    DynamicAnswer.objects.filter(user=patient).delete()
    SociodemographicAnswer.objects.filter(user=patient).delete()

    # This also removes UserProfile through its clinical OneToOne CASCADE.
    patient.delete()
