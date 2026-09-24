from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q

from polls.models import (
    DynamicAnswer,
    NormativeDatasetVersion,
    NormativeParticipant,
    QuestionnaireSubmission,
    SociodemographicAnswer,
    UserAnswer,
)
from polls.normative_test import clear_normative_test_environment
from website.models import UserProfile

from .permissions import can_master_reset


@dataclass(frozen=True)
class ProfessionalTestCleanupPreview:
    patients: int
    submissions: int
    normative_test_versions: int
    synthetic_participants: int


@dataclass(frozen=True)
class ProfessionalTestCleanupResult:
    patients: int
    submissions: int
    normative_test_versions: int
    synthetic_participants: int


def _test_patient_profiles():
    return UserProfile.objects.filter(
        user_type="patient",
        is_test_data=True,
        test_environment_owner__isnull=False,
    )


def _test_submission_scope(patient_user_ids):
    return QuestionnaireSubmission.objects.filter(
        Q(user_id__in=patient_user_ids)
        | Q(is_test_data=True)
        | ~Q(simulation_mode="normal")
    )


def get_professional_test_cleanup_preview():
    patient_user_ids = _test_patient_profiles().values_list("user_id", flat=True)
    return ProfessionalTestCleanupPreview(
        patients=_test_patient_profiles().count(),
        submissions=_test_submission_scope(patient_user_ids).count(),
        normative_test_versions=NormativeDatasetVersion.objects.filter(
            environment=NormativeDatasetVersion.Environment.TEST
        ).count(),
        synthetic_participants=NormativeParticipant.objects.filter(
            source=NormativeParticipant.Source.SYNTHETIC
        ).count(),
    )


@transaction.atomic
def clear_professional_test_environment(actor):
    """Delete the complete PTE and its shared synthetic normative pool."""
    if actor.pk is None or not can_master_reset(actor):
        raise PermissionError("O actor não tem autorização para limpar o PTE.")

    profiles = list(
        _test_patient_profiles().select_for_update().order_by("pk")
    )
    patient_user_ids = [profile.user_id for profile in profiles]
    submissions = _test_submission_scope(patient_user_ids).order_by("pk")
    submission_ids = list(
        submissions.select_for_update().values_list("pk", flat=True)
    )
    submission_count = len(submission_ids)
    patient_count = len(patient_user_ids)

    # Remove submission-owned PROTECT references before deleting the shared
    # TEST normative versions. Raw answers for PTE patients are removed too.
    QuestionnaireSubmission.objects.filter(pk__in=submission_ids).delete()
    UserAnswer.objects.filter(user_id__in=patient_user_ids).delete()
    DynamicAnswer.objects.filter(user_id__in=patient_user_ids).delete()
    SociodemographicAnswer.objects.filter(user_id__in=patient_user_ids).delete()

    normative_result = clear_normative_test_environment()

    User = get_user_model()
    User.objects.filter(pk__in=patient_user_ids).delete()

    if _test_patient_profiles().exists():
        raise RuntimeError("Permanecem pacientes no Ambiente Profissional de Teste.")
    if QuestionnaireSubmission.objects.filter(
        Q(is_test_data=True) | ~Q(simulation_mode="normal")
    ).exists():
        raise RuntimeError("Permanecem submissions de teste ou simulação.")
    if NormativeParticipant.objects.filter(
        source=NormativeParticipant.Source.SYNTHETIC
    ).exists():
        raise RuntimeError("Permanecem participantes normativos sintéticos.")

    return ProfessionalTestCleanupResult(
        patients=patient_count,
        submissions=submission_count,
        normative_test_versions=normative_result.versions,
        synthetic_participants=normative_result.participants,
    )
