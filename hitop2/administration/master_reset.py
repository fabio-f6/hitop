from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction

from polls.models import (
    DynamicAnswer,
    NormativeAnswer,
    NormativeDatasetMembership,
    NormativeDatasetVersion,
    NormativeParticipant,
    NormativeScaleScore,
    NormativeSpectrumScore,
    QuestionnaireSubmission,
    Scale,
    SociodemographicAnswer,
    Spectra,
    UserAnswer,
)
from polls.normative_test import clear_normative_test_environment
from website.models import UserProfile

from .audit import record_admin_action
from .models import AdministrativeAuditLog, MASTER_RESET_ACTION, SYSTEM_OBJECT_TYPE
from .permissions import can_master_reset


ORIGINAL_VERSION_NAME = "v1"
ORIGINAL_PARTICIPANT_COUNT = 255


class MasterResetError(Exception):
    """Raised when a Master Reset cannot safely complete."""


@dataclass(frozen=True)
class MasterResetPreview:
    users: int
    submissions: int
    test_submissions: int
    actor_username: str
    normative_version: str
    normative_participants: int


def get_master_reset_preview(actor):
    User = get_user_model()
    v1 = NormativeDatasetVersion.objects.filter(name=ORIGINAL_VERSION_NAME).first()
    return MasterResetPreview(
        users=User.objects.exclude(pk=actor.pk).count(),
        submissions=QuestionnaireSubmission.objects.count(),
        test_submissions=QuestionnaireSubmission.objects.filter(is_test_data=True).count(),
        actor_username=actor.get_username(),
        normative_version=ORIGINAL_VERSION_NAME,
        normative_participants=(v1.memberships.count() if v1 else 0),
    )


def _validate_original_version(locked_versions):
    matches = [version for version in locked_versions if version.name == ORIGINAL_VERSION_NAME]
    if len(matches) != 1:
        raise MasterResetError("A versão normativa original não é identificável.")
    version = matches[0]
    if version.environment != NormativeDatasetVersion.Environment.PRODUCTION:
        raise MasterResetError("A versão normativa original não é de produção.")
    if version.status not in {
        NormativeDatasetVersion.Status.ACTIVE,
        NormativeDatasetVersion.Status.RETIRED,
    } or version.prepared_at is None or version.activated_at is None:
        raise MasterResetError("A versão normativa original não é restaurável.")

    membership_ids = set(
        NormativeDatasetMembership.objects.select_for_update()
        .filter(version=version)
        .values_list("participant_id", flat=True)
    )
    if len(membership_ids) != ORIGINAL_PARTICIPANT_COUNT:
        raise MasterResetError("A versão normativa original não tem 255 participantes.")

    scale_scores = NormativeScaleScore.objects.filter(version=version)
    spectrum_scores = NormativeSpectrumScore.objects.filter(version=version)
    if Scale.objects.exists() and not scale_scores.exists():
        raise MasterResetError("A versão normativa original não tem scores de escalas.")
    if Spectra.objects.exists() and not spectrum_scores.exists():
        raise MasterResetError("A versão normativa original não tem scores de espectros.")
    if scale_scores.exclude(participant_id__in=membership_ids).exists():
        raise MasterResetError("Os scores de escalas da v1 são inconsistentes.")
    if spectrum_scores.exclude(participant_id__in=membership_ids).exists():
        raise MasterResetError("Os scores de espectros da v1 são inconsistentes.")
    return version


def _restore_existing_version_as_active(version, locked_versions):
    """Restore a historical snapshot without recalculation or timestamp loss."""
    other_active_ids = [
        item.pk for item in locked_versions
        if item.status == NormativeDatasetVersion.Status.ACTIVE
        and item.environment == NormativeDatasetVersion.Environment.PRODUCTION
        and item.pk != version.pk
    ]
    if other_active_ids:
        NormativeDatasetVersion.objects.filter(pk__in=other_active_ids).update(
            status=NormativeDatasetVersion.Status.RETIRED,
        )
    NormativeDatasetVersion.objects.filter(pk=version.pk).update(
        status=NormativeDatasetVersion.Status.ACTIVE,
    )


@transaction.atomic
def perform_master_reset(actor):
    """Atomically remove operational data and restore the original v1 snapshot."""
    User = get_user_model()
    actor_pk = actor.pk
    if actor_pk is None or not can_master_reset(actor):
        raise MasterResetError("O actor não tem autorização.")

    # Report generation locks a submission before its selected version. Match
    # that order before taking lifecycle locks so reset and report cannot
    # deadlock while trying to acquire the same rows.
    list(
        QuestionnaireSubmission.objects.select_for_update()
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    # Lock every lifecycle row in a stable order. This is also the global reset
    # mutex: concurrent reset/activation operations serialize on these rows.
    locked_versions = list(
        NormativeDatasetVersion.objects.select_for_update().order_by("pk")
    )
    v1 = _validate_original_version(locked_versions)

    try:
        locked_actor = User.objects.select_for_update().get(pk=actor_pk)
    except User.DoesNotExist as exception:
        raise MasterResetError("O actor deixou de existir.") from exception
    if not can_master_reset(locked_actor):
        raise MasterResetError("O actor perdeu autorização.")

    actor_profile = UserProfile.objects.select_for_update().get(user=locked_actor)
    actor_state = {
        "profile_pk": actor_profile.pk,
        "user_type": actor_profile.user_type,
        "is_staff": locked_actor.is_staff,
        "is_superuser": locked_actor.is_superuser,
        "password": locked_actor.password,
        "user_permissions": tuple(
            locked_actor.user_permissions.order_by("pk").values_list("pk", flat=True)
        ),
        "groups": tuple(locked_actor.groups.order_by("pk").values_list("pk", flat=True)),
    }

    previous_active = next(
        (item.name for item in locked_versions
         if item.status == item.Status.ACTIVE
         and item.environment == item.Environment.PRODUCTION),
        None,
    )
    users_deleted = User.objects.exclude(pk=actor_pk).count()
    submissions_deleted = QuestionnaireSubmission.objects.count()
    test_submissions_deleted = QuestionnaireSubmission.objects.filter(
        is_test_data=True,
    ).count()
    audit_count_before = AdministrativeAuditLog.objects.count()
    production_versions = NormativeDatasetVersion.objects.filter(
        environment=NormativeDatasetVersion.Environment.PRODUCTION
    )
    real_participants = NormativeParticipant.objects.filter(
        source=NormativeParticipant.Source.REAL
    )
    normative_counts_before = {
        "participants": real_participants.count(),
        "answers": NormativeAnswer.objects.filter(participant__source="real").count(),
        "versions": production_versions.count(),
        "memberships": NormativeDatasetMembership.objects.filter(version__environment="production").count(),
        "scale_scores": NormativeScaleScore.objects.filter(version__environment="production").count(),
        "spectrum_scores": NormativeSpectrumScore.objects.filter(version__environment="production").count(),
    }

    # Submission-owned answers cascade; the explicit deletes also remove all
    # legacy/unattached clinical and sociodemographic application data.
    QuestionnaireSubmission.objects.all().delete()
    UserAnswer.objects.all().delete()
    DynamicAnswer.objects.all().delete()
    SociodemographicAnswer.objects.all().delete()
    test_cleanup = clear_normative_test_environment()

    doomed_users = User.objects.exclude(pk=actor_pk)
    doomed_user_ids = list(doomed_users.values_list("pk", flat=True))
    if actor_pk in doomed_user_ids:
        raise MasterResetError("O actor entrou no conjunto destrutivo.")
    # Remove doomed profiles first to resolve their PROTECT references to test
    # environment owners. The actor's own profile is never in this queryset.
    UserProfile.objects.filter(user_id__in=doomed_user_ids).delete()
    doomed_users.delete()

    _restore_existing_version_as_active(v1, locked_versions)

    if not User.objects.filter(pk=actor_pk).exists():
        raise MasterResetError("O actor foi removido.")
    if User.objects.exclude(pk=actor_pk).exists():
        raise MasterResetError("Ainda existem outros utilizadores.")
    if QuestionnaireSubmission.objects.exists():
        raise MasterResetError("Ainda existem aplicações de questionário.")
    if QuestionnaireSubmission.objects.filter(is_test_data=True).exists():
        raise MasterResetError("Ainda existem aplicações de teste.")

    locked_actor.refresh_from_db()
    actor_profile.refresh_from_db()
    if (
        actor_profile.pk != actor_state["profile_pk"]
        or actor_profile.user_type != actor_state["user_type"]
        or locked_actor.is_staff != actor_state["is_staff"]
        or locked_actor.is_superuser != actor_state["is_superuser"]
        or locked_actor.password != actor_state["password"]
        or tuple(locked_actor.user_permissions.order_by("pk").values_list("pk", flat=True))
        != actor_state["user_permissions"]
        or tuple(locked_actor.groups.order_by("pk").values_list("pk", flat=True))
        != actor_state["groups"]
    ):
        raise MasterResetError("A identidade do actor foi alterada.")

    v1.refresh_from_db()
    if v1.status != v1.Status.ACTIVE or v1.memberships.count() != 255:
        raise MasterResetError("A v1 não ficou ativa e íntegra.")
    if NormativeDatasetVersion.objects.filter(
        status=v1.Status.ACTIVE, environment=v1.Environment.PRODUCTION
    ).count() != 1:
        raise MasterResetError("O lifecycle normativo ficou inconsistente.")
    normative_counts_after = {
        "participants": NormativeParticipant.objects.filter(source="real").count(),
        "answers": NormativeAnswer.objects.filter(participant__source="real").count(),
        "versions": NormativeDatasetVersion.objects.filter(environment="production").count(),
        "memberships": NormativeDatasetMembership.objects.filter(version__environment="production").count(),
        "scale_scores": NormativeScaleScore.objects.filter(version__environment="production").count(),
        "spectrum_scores": NormativeSpectrumScore.objects.filter(version__environment="production").count(),
    }
    if normative_counts_after != normative_counts_before:
        raise MasterResetError("Os dados normativos foram alterados.")
    if AdministrativeAuditLog.objects.count() != audit_count_before:
        raise MasterResetError("O histórico de auditoria foi alterado.")

    try:
        entry = record_admin_action(
            actor=locked_actor,
            action=MASTER_RESET_ACTION,
            object_type=SYSTEM_OBJECT_TYPE,
            object_id="master-reset",
            object_label="Master Reset",
            metadata={
                "users_deleted": users_deleted,
                "submissions_deleted": submissions_deleted,
                "test_submissions_deleted": test_submissions_deleted,
                "previous_active_normative_version": previous_active,
                "restored_normative_version": ORIGINAL_VERSION_NAME,
                "restored_normative_participant_count": ORIGINAL_PARTICIPANT_COUNT,
                "test_versions_deleted": test_cleanup.versions,
                "synthetic_participants_deleted": test_cleanup.participants,
            },
        )
    except Exception as exception:
        raise MasterResetError("Não foi possível registar a auditoria.") from exception
    if not AdministrativeAuditLog.objects.filter(
        pk=entry.pk,
        action=MASTER_RESET_ACTION,
        actor_id=actor_pk,
    ).exists():
        raise MasterResetError("A auditoria obrigatória não foi criada.")

    return entry
