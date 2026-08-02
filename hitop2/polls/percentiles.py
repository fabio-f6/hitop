from polls.models import NormativeScaleScore

def calculate_percentile(scale, raw_score):

    if raw_score is None:
        return None

    normative_scores = (
        NormativeScaleScore.objects
        .filter(scale=scale)
        .values_list("raw_score", flat=True)
    )

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