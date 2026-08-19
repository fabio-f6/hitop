from collections import defaultdict

from .scoring import calculate_average


def calculate_spectrum_scores(scale_scores):

    grouped_scores = defaultdict(list)

    for scale, scale_data in scale_scores.items():

        spectrum = scale.subfactor.spectra

        grouped_scores[spectrum].append(scale_data)

    spectrum_scores = {}

    for spectrum, scales in grouped_scores.items():

        valid_scores = [
            scale["score"]
            for scale in scales
            if scale["is_valid"]
        ]

        missing_answers = sum(
            scale["missing_answers"]
            for scale in scales
        )

        total_items = sum(
            scale["total_items"]
            for scale in scales
        )

        missing_percentage = (
            (missing_answers / total_items) * 100
            if total_items else 0
        )

        is_valid = missing_percentage < 25

        spectrum_scores[spectrum] = {

            "score":
                calculate_average(valid_scores)
                if is_valid else None,

            "missing_answers":
                missing_answers,

            "missing_percentage":
                missing_percentage,

            "total_items":
                total_items,

            "is_valid":
                is_valid,

        }

    return spectrum_scores