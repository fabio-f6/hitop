from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    NormativeAnswer,
    NormativeDatasetMembership,
    NormativeDatasetVersion,
    NormativeParticipant,
    NormativeScaleScore,
    NormativeSpectrumScore,
    QuestionnaireSubmission,
)
from .scoring import calculate_scale_scores_from_answers
from .spectrum_scores import calculate_spectrum_scores


class NormativeVersionError(ValidationError):
    """Raised when a normative version operation violates its lifecycle."""


@dataclass(frozen=True)
class NormativePreparationResult:
    version_id: int
    participant_count: int
    scale_score_count: int
    spectrum_score_count: int


def get_active_normative_version(environment=NormativeDatasetVersion.Environment.PRODUCTION):
    return NormativeDatasetVersion.objects.filter(
        status=NormativeDatasetVersion.Status.ACTIVE,
        environment=environment,
    ).first()


def get_normative_versions(environment=NormativeDatasetVersion.Environment.PRODUCTION):
    """Return versions with counts needed by the future administration UI."""
    return NormativeDatasetVersion.objects.filter(environment=environment).annotate(
        snapshot_participant_count=Count("memberships", distinct=True),
    )


def get_normative_version_details(version_id):
    # Detail routes address an explicit primary key and are shared by the two
    # administration environments. Do not apply the production list default.
    return NormativeDatasetVersion.objects.annotate(
        snapshot_participant_count=Count("memberships", distinct=True),
    ).get(pk=version_id)


def get_total_normative_participant_count():
    return NormativeParticipant.objects.filter(source=NormativeParticipant.Source.REAL).count()


def get_active_normative_participant_count():
    active_version = get_active_normative_version()
    return active_version.participant_count if active_version is not None else 0


def get_unversioned_normative_participant_count(version=None):
    """Count participants absent from the supplied (or active) snapshot."""
    if version is None:
        version = get_active_normative_version()
    if version is None:
        return get_total_normative_participant_count()
    if version.environment == NormativeDatasetVersion.Environment.TEST:
        return NormativeParticipant.objects.filter(
            source=NormativeParticipant.Source.SYNTHETIC,
        ).exclude(version_memberships__version=version).count()
    return NormativeParticipant.objects.exclude(
        version_memberships__version=version,
    ).filter(source=NormativeParticipant.Source.REAL).count()


def get_normative_participant_counts():
    active_version = get_active_normative_version()
    return {
        "total": get_total_normative_participant_count(),
        "active_version": (
            active_version.participant_count if active_version is not None else 0
        ),
        "not_in_active_version": get_unversioned_normative_participant_count(
            active_version
        ),
    }


@transaction.atomic
def create_normative_version(
    name,
    environment=NormativeDatasetVersion.Environment.PRODUCTION,
    baseline_version=None,
):
    """Create an unprepared draft with a point-in-time participant snapshot."""
    if not isinstance(name, str):
        raise NormativeVersionError("A versão normativa requer um nome.")
    name = name.strip()
    if not name:
        raise NormativeVersionError("A versão normativa requer um nome.")

    if environment == NormativeDatasetVersion.Environment.PRODUCTION:
        if baseline_version is not None:
            raise NormativeVersionError("Uma versão de produção não aceita baseline.")
        participants = NormativeParticipant.objects.filter(
            source=NormativeParticipant.Source.REAL
        )
    elif environment == NormativeDatasetVersion.Environment.TEST:
        if baseline_version is None or baseline_version.environment not in {
            NormativeDatasetVersion.Environment.PRODUCTION,
            NormativeDatasetVersion.Environment.TEST,
        }:
            raise NormativeVersionError(
                "Uma versão de teste requer um baseline de produção ou de teste."
            )
        baseline_version = NormativeDatasetVersion.objects.select_for_update().get(
            pk=baseline_version.pk,
        )
        baseline_ids = baseline_version.memberships.values_list("participant_id", flat=True)
        participants = NormativeParticipant.objects.filter(
            Q(pk__in=baseline_ids) | Q(source=NormativeParticipant.Source.SYNTHETIC)
        )
    else:
        raise NormativeVersionError("Ambiente normativo inválido.")
    participant_ids = list(participants.order_by("pk").values_list("pk", flat=True))
    version = NormativeDatasetVersion.objects.create(
        name=name, environment=environment, baseline_version=baseline_version,
    )
    NormativeDatasetMembership.objects.bulk_create(
        [
            NormativeDatasetMembership(
                version=version,
                participant_id=participant_id,
            )
            for participant_id in participant_ids
        ]
    )
    return version


@transaction.atomic
def prepare_normative_version(version):
    """Calculate a draft using only the participants in its fixed snapshot."""
    version = NormativeDatasetVersion.objects.select_for_update().get(pk=version.pk)
    if version.status != NormativeDatasetVersion.Status.DRAFT:
        raise NormativeVersionError(
            "Apenas uma versão draft pode ser preparada ou recalculada."
        )
    if (
        version.environment == NormativeDatasetVersion.Environment.PRODUCTION
        and version.participants.filter(source=NormativeParticipant.Source.SYNTHETIC).exists()
    ):
        raise NormativeVersionError(
            "Uma versão de produção não pode conter participantes sintéticos."
        )

    participant_ids = list(
        version.memberships.select_for_update()
        .order_by("participant_id")
        .values_list("participant_id", flat=True)
    )

    # Re-preparing a draft replaces its own scores atomically. No other version
    # is touched and a failure restores the prior draft data.
    NormativeScaleScore.objects.filter(version=version).delete()
    NormativeSpectrumScore.objects.filter(version=version).delete()

    scale_score_rows = []
    spectrum_score_rows = []
    for participant_id in participant_ids:
        answers = list(
            NormativeAnswer.objects.filter(participant_id=participant_id)
            .select_related("question__scale__subfactor__spectra")
        )
        scale_scores = calculate_scale_scores_from_answers(answers)
        spectrum_scores = calculate_spectrum_scores(scale_scores)

        scale_score_rows.extend(
            NormativeScaleScore(
                version=version,
                participant_id=participant_id,
                scale=scale,
                raw_score=data["score"],
            )
            for scale, data in scale_scores.items()
            if data["score"] is not None
        )
        spectrum_score_rows.extend(
            NormativeSpectrumScore(
                version=version,
                participant_id=participant_id,
                spectrum=spectrum,
                raw_score=data["score"],
            )
            for spectrum, data in spectrum_scores.items()
            if data["score"] is not None
        )

    NormativeScaleScore.objects.bulk_create(scale_score_rows)
    NormativeSpectrumScore.objects.bulk_create(spectrum_score_rows)
    prepared_at = timezone.now()
    NormativeDatasetVersion.objects.filter(pk=version.pk).update(
        prepared_at=prepared_at,
    )
    version.prepared_at = prepared_at

    return NormativePreparationResult(
        version_id=version.pk,
        participant_count=len(participant_ids),
        scale_score_count=len(scale_score_rows),
        spectrum_score_count=len(spectrum_score_rows),
    )


@transaction.atomic
def activate_normative_version(version):
    """Activate one prepared draft and retire the previous active version."""
    # Always lock lifecycle rows in the same order. Concurrent activation calls
    # therefore serialize without locking different target rows first.
    locked_versions = list(
        NormativeDatasetVersion.objects.select_for_update().order_by("pk")
    )
    version = next((item for item in locked_versions if item.pk == version.pk), None)
    if version is None:
        raise NormativeDatasetVersion.DoesNotExist
    if version.status == NormativeDatasetVersion.Status.ACTIVE:
        return version
    if version.status != NormativeDatasetVersion.Status.DRAFT:
        raise NormativeVersionError("Apenas uma versão draft pode ser ativada.")
    if version.prepared_at is None:
        raise NormativeVersionError("A versão deve ser preparada antes da ativação.")

    # The partial unique constraint remains the final database-level guarantee
    # that two active versions can never be committed.
    active_ids = [
        item.pk
        for item in locked_versions
        if item.status == NormativeDatasetVersion.Status.ACTIVE
        and item.environment == version.environment
        and item.pk != version.pk
    ]
    if active_ids:
        NormativeDatasetVersion.objects.filter(pk__in=active_ids).update(
            status=NormativeDatasetVersion.Status.RETIRED,
        )

    activated_at = timezone.now()
    NormativeDatasetVersion.objects.filter(pk=version.pk).update(
        status=NormativeDatasetVersion.Status.ACTIVE,
        activated_at=activated_at,
    )
    version.status = NormativeDatasetVersion.Status.ACTIVE
    version.activated_at = activated_at
    return version


@transaction.atomic
def get_or_assign_report_normative_version(submission):
    """Pin a submission once, retaining the existing pin on later calls."""
    locked_submission = QuestionnaireSubmission.objects.select_for_update().get(
        pk=submission.pk
    )
    if locked_submission.report_normative_version_id is not None:
        version = locked_submission.report_normative_version
        is_test_submission = (
            locked_submission.is_test_data or locked_submission.simulation_mode != "normal"
        )
        if not is_test_submission and version.environment != NormativeDatasetVersion.Environment.PRODUCTION:
            raise NormativeVersionError("A versão fixada não pertence ao ambiente da submissão.")
    else:
        environment = (
            NormativeDatasetVersion.Environment.TEST
            if locked_submission.is_test_data or locked_submission.simulation_mode != "normal"
            else NormativeDatasetVersion.Environment.PRODUCTION
        )
        version = (
            NormativeDatasetVersion.objects.select_for_update()
            .filter(status=NormativeDatasetVersion.Status.ACTIVE, environment=environment)
            .first()
        )
        if version is None and environment == NormativeDatasetVersion.Environment.TEST:
            version = (
                NormativeDatasetVersion.objects.select_for_update()
                .filter(status=NormativeDatasetVersion.Status.ACTIVE,
                        environment=NormativeDatasetVersion.Environment.PRODUCTION)
                .first()
            )
        if version is not None:
            locked_submission.report_normative_version = version
            locked_submission.save(update_fields=["report_normative_version"])

    submission.report_normative_version = version
    submission.report_normative_version_id = version.pk if version is not None else None
    return version
