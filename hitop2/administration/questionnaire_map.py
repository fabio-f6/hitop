from collections import defaultdict

from polls.models import Question, Scale, Spectra, Subfactor

from .health_checks import evaluate_scientific_structure


TYPE_LABELS = {
    "spectrum": "Spectrum",
    "subfactor": "Subfactor",
    "scale": "Scale",
    "question": "Question",
}


def _node_id(node_type, pk):
    return f"{node_type}-{pk}"


def build_questionnaire_structure():
    """Return a normalized, read-only representation of the questionnaire."""
    spectra_rows = list(Spectra.objects.order_by("name", "id").values("id", "name"))
    subfactor_rows = list(
        Subfactor.objects.order_by("name", "id").values("id", "name", "spectra_id")
    )
    scale_rows = list(
        Scale.objects.order_by("name", "id").values("id", "name", "subfactor_id")
    )
    question_rows = list(
        Question.objects.order_by("item_code", "id").values(
            "id",
            "scale_id",
            "item_code",
            "question_text",
            "is_attention_check",
            "expected_answer",
        )
    )

    health = evaluate_scientific_structure(
        spectra_rows, subfactor_rows, scale_rows, question_rows
    )
    issues = health["entity_issues"]

    # Attention checks retain their database hierarchy for compatibility, but
    # that hierarchy is internal infrastructure rather than scientific HiTOP.
    scientific_question_rows = [
        row for row in question_rows if not row["is_attention_check"]
    ]
    attention_scale_ids = {
        row["scale_id"] for row in question_rows if row["is_attention_check"]
    }
    scientific_scale_ids = {row["scale_id"] for row in scientific_question_rows}
    attention_only_scale_ids = attention_scale_ids - scientific_scale_ids
    visible_scale_rows = [
        row for row in scale_rows if row["id"] not in attention_only_scale_ids
    ]
    visible_subfactor_ids = {row["subfactor_id"] for row in visible_scale_rows}
    subfactors_with_scales = {row["subfactor_id"] for row in scale_rows}
    visible_subfactor_rows = [
        row
        for row in subfactor_rows
        if row["id"] in visible_subfactor_ids
        or row["id"] not in subfactors_with_scales
    ]
    visible_spectrum_ids = {row["spectra_id"] for row in visible_subfactor_rows}
    spectra_with_subfactors = {row["spectra_id"] for row in subfactor_rows}
    visible_spectra_rows = [
        row
        for row in spectra_rows
        if row["id"] in visible_spectrum_ids
        or row["id"] not in spectra_with_subfactors
    ]
    questions_by_scale = defaultdict(list)
    scales_by_subfactor = defaultdict(list)
    subfactors_by_spectrum = defaultdict(list)

    def make_node(node_type, row, name, children=None, details=None):
        node = {
            "id": _node_id(node_type, row["id"]),
            "database_id": row["id"],
            "type": node_type,
            "type_label": TYPE_LABELS[node_type],
            "name": name or "Sem nome",
            "label": name or "Sem nome",
            "question_count": 1 if node_type == "question" else 0,
            "issues": issues.get((node_type, row["id"]), []),
            "children": children or [],
            "details": details or {},
        }
        return node

    for row in scientific_question_rows:
        question = make_node(
            "question",
            row,
            row["item_code"],
            details={
                "question_text": row["question_text"],
                "item_code": row["item_code"],
                "is_attention_check": row["is_attention_check"],
                "expected_answer": row["expected_answer"] if row["is_attention_check"] else "",
            },
        )
        questions_by_scale[row["scale_id"]].append(question)

    for row in visible_scale_rows:
        children = questions_by_scale[row["id"]]
        scale = make_node("scale", row, row["name"], children=children)
        scale["question_count"] = len(children)
        scales_by_subfactor[row["subfactor_id"]].append(scale)

    for row in visible_subfactor_rows:
        children = scales_by_subfactor[row["id"]]
        subfactor = make_node("subfactor", row, row["name"], children=children)
        subfactor["question_count"] = sum(child["question_count"] for child in children)
        subfactors_by_spectrum[row["spectra_id"]].append(subfactor)

    roots = []
    for row in visible_spectra_rows:
        children = subfactors_by_spectrum[row["id"]]
        spectrum = make_node("spectrum", row, row["name"], children=children)
        spectrum["question_count"] = sum(child["question_count"] for child in children)
        roots.append(spectrum)

    def add_paths(node, ancestors):
        path = [*ancestors, {"id": node["id"], "name": node["name"], "type": node["type"]}]
        node["path"] = path
        node["path_text"] = " → ".join(part["name"] for part in path)
        node["has_problem_in_branch"] = bool(node["issues"])
        for child in node["children"]:
            add_paths(child, path)
            node["has_problem_in_branch"] |= child["has_problem_in_branch"]

    for root in roots:
        add_paths(root, [])

    return {
        "roots": roots,
        "totals": {
            "spectra_count": len(visible_spectra_rows),
            "subfactor_count": len(visible_subfactor_rows),
            "scale_count": len(visible_scale_rows),
            "question_count": len(scientific_question_rows),
        },
        "unmapped_problems": [
            problem
            for problem in health["problems"]
            if problem["code"].startswith("scientific_structure_missing_")
        ],
    }
