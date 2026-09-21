from polls.models import (
    NormativeScaleScore,
    NormativeSpectrumScore,
)
from polls.normative_versions import get_active_normative_version


_USE_ACTIVE_VERSION = object()


def _calculate_percentile(normative_scores, raw_score):

    if raw_score is None:
        return None

    total = len(normative_scores)

    if total == 0:
        return None

    count = sum(
        score <= raw_score
        for score in normative_scores
    )

    percentile = round(
        (count / total) * 100
    )

    return percentile


def calculate_percentile(scale, raw_score, *, version=_USE_ACTIVE_VERSION):

    if version is _USE_ACTIVE_VERSION:
        version = get_active_normative_version()
    if version is None:
        return None

    normative_scores = (
        NormativeScaleScore.objects
        .filter(version=version, scale=scale)
        .values_list("raw_score", flat=True)
    )

    return _calculate_percentile(
        normative_scores,
        raw_score,
    )


def calculate_spectrum_percentile(
    spectrum,
    raw_score,
    *,
    version=_USE_ACTIVE_VERSION,
):

    if version is _USE_ACTIVE_VERSION:
        version = get_active_normative_version()
    if version is None:
        return None

    normative_scores = (
        NormativeSpectrumScore.objects
        .filter(version=version, spectrum=spectrum)
        .values_list("raw_score", flat=True)
    )

    return _calculate_percentile(
        normative_scores,
        raw_score,
    )
