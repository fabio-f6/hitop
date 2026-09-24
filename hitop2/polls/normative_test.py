from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q

from .models import (
    NormativeAnswer,
    NormativeDatasetMembership,
    NormativeDatasetVersion,
    NormativeParticipant,
    NormativeScaleScore,
    NormativeSpectrumScore,
    QuestionnaireSubmission,
    normative_test_cleanup_boundary,
)


@dataclass(frozen=True)
class NormativeTestCleanupResult:
    versions: int
    participants: int
    submissions_reset: int


def _production_snapshot():
    production_versions = NormativeDatasetVersion.objects.filter(
        environment=NormativeDatasetVersion.Environment.PRODUCTION
    )
    return {
        "versions": production_versions.count(),
        "memberships": NormativeDatasetMembership.objects.filter(
            version__environment=NormativeDatasetVersion.Environment.PRODUCTION
        ).count(),
        "participants": NormativeParticipant.objects.filter(
            source=NormativeParticipant.Source.REAL
        ).count(),
        "answers": NormativeAnswer.objects.filter(
            participant__source=NormativeParticipant.Source.REAL
        ).count(),
        "scale_scores": NormativeScaleScore.objects.filter(
            version__environment=NormativeDatasetVersion.Environment.PRODUCTION
        ).count(),
        "spectrum_scores": NormativeSpectrumScore.objects.filter(
            version__environment=NormativeDatasetVersion.Environment.PRODUCTION
        ).count(),
    }


def _validate_cleanup_result(expected_production):
    if NormativeDatasetVersion.objects.filter(
        environment=NormativeDatasetVersion.Environment.TEST
    ).exists():
        raise RuntimeError("Permanecem versões normativas de teste.")
    if NormativeScaleScore.objects.filter(
        version__environment=NormativeDatasetVersion.Environment.TEST
    ).exists() or NormativeSpectrumScore.objects.filter(
        version__environment=NormativeDatasetVersion.Environment.TEST
    ).exists():
        raise RuntimeError("Permanecem scores normativos de teste.")
    if NormativeParticipant.objects.filter(
        source=NormativeParticipant.Source.SYNTHETIC
    ).exists():
        raise RuntimeError("Permanecem participantes normativos sintéticos.")
    if QuestionnaireSubmission.objects.filter(
        report_normative_version__environment=NormativeDatasetVersion.Environment.TEST
    ).exists():
        raise RuntimeError("Permanecem pins para versões normativas de teste.")
    if NormativeDatasetMembership.objects.filter(
        version__environment=NormativeDatasetVersion.Environment.TEST
    ).exists():
        raise RuntimeError("Permanecem memberships normativas de teste.")
    if _production_snapshot() != expected_production:
        raise RuntimeError("Os dados normativos de produção foram alterados.")


@transaction.atomic
def clear_normative_test_environment():
    """Remove only test versions and synthetic participants, including history."""
    real_submission_pins = QuestionnaireSubmission.objects.filter(
        is_test_data=False,
        simulation_mode="normal",
        report_normative_version__environment=NormativeDatasetVersion.Environment.TEST,
    )
    if list(real_submission_pins.select_for_update().values_list("pk", flat=True)):
        raise RuntimeError(
            "Uma submissão clínica real está associada a uma versão normativa de teste."
        )

    # Report generation locks submission first, then its selected version. Keep
    # the same order here to avoid a reset/report deadlock.
    test_submissions = QuestionnaireSubmission.objects.select_for_update().filter(
        Q(is_test_data=True) | ~Q(simulation_mode="normal")
    ).order_by("pk")
    list(test_submissions.values_list("pk", flat=True))
    locked_versions = list(
        NormativeDatasetVersion.objects.select_for_update().order_by("pk")
    )
    test_versions = [
        version for version in locked_versions
        if version.environment == NormativeDatasetVersion.Environment.TEST
    ]
    test_version_ids = [version.pk for version in test_versions]
    version_count = len(test_version_ids)
    synthetic = list(
        NormativeParticipant.objects.select_for_update().filter(
            source=NormativeParticipant.Source.SYNTHETIC
        ).order_by("pk")
    )
    synthetic_ids = [participant.pk for participant in synthetic]
    participant_count = len(synthetic_ids)
    source_submission_ids = [
        participant.source_submission_id
        for participant in synthetic
        if participant.source_submission_id is not None
    ]

    synthetic_in_production = (
        NormativeDatasetMembership.objects.filter(
            participant_id__in=synthetic_ids,
            version__environment=NormativeDatasetVersion.Environment.PRODUCTION,
        ).exists()
        or NormativeScaleScore.objects.filter(
            participant_id__in=synthetic_ids,
            version__environment=NormativeDatasetVersion.Environment.PRODUCTION,
        ).exists()
        or NormativeSpectrumScore.objects.filter(
            participant_id__in=synthetic_ids,
            version__environment=NormativeDatasetVersion.Environment.PRODUCTION,
        ).exists()
    )
    if synthetic_in_production:
        raise RuntimeError(
            "Um participante sintético está associado a uma versão de produção."
        )

    real_synthetic_source = QuestionnaireSubmission.objects.filter(
        pk__in=source_submission_ids,
        is_test_data=False,
        simulation_mode="normal",
    )
    if real_synthetic_source.exists():
        raise RuntimeError(
            "Um participante sintético está associado a uma submissão clínica real."
        )

    production_snapshot = _production_snapshot()
    pinned_test_submissions = QuestionnaireSubmission.objects.select_for_update().filter(
        report_normative_version_id__in=test_version_ids,
    )
    # Only TEST/simulated records can refer to TEST versions. The guard above
    # aborts if a clinical submission violates that invariant.
    pinned_test_submissions.update(report_normative_version=None)

    submissions_to_reset = QuestionnaireSubmission.objects.filter(
        Q(is_test_data=True) | ~Q(simulation_mode="normal"),
    ).filter(
        Q(normative_status=QuestionnaireSubmission.NormativeStatus.EXPORTED)
        | Q(normative_exported_at__isnull=False)
    )
    submissions_reset = submissions_to_reset.count()
    submissions_to_reset.update(
        normative_status=QuestionnaireSubmission.NormativeStatus.PENDING,
        normative_exported_at=None,
    )

    with normative_test_cleanup_boundary():
        NormativeScaleScore.objects.filter(version_id__in=test_version_ids).delete()
        NormativeSpectrumScore.objects.filter(version_id__in=test_version_ids).delete()
        NormativeDatasetMembership.objects.filter(
            version_id__in=test_version_ids
        ).delete()
        NormativeDatasetVersion.objects.filter(pk__in=test_version_ids).delete()
        NormativeAnswer.objects.filter(participant_id__in=synthetic_ids).delete()
        NormativeParticipant.objects.filter(pk__in=synthetic_ids).delete()

    _validate_cleanup_result(production_snapshot)
    return NormativeTestCleanupResult(
        version_count,
        participant_count,
        submissions_reset,
    )
