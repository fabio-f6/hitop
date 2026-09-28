"""Independent mathematical oracle. No Django or production-engine imports.

The repository import key is a provenance source, NOT an official scientific key.
Reverse transforms are opt-in hypothetical cases until an official key is supplied.
"""
import ast
import bisect
import statistics
from collections import defaultdict
from fractions import Fraction


def read_key(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in {"NEVER", "RARELY", "SOMETIMES", "ALWAYS", "DONT_KNOW"}:
                constants[name] = ast.literal_eval(node.value)
    class Resolve(ast.NodeTransformer):
        def visit_Name(self, node):
            return ast.Constant(constants[node.id]) if node.id in constants else node
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in {"questions_data", "scale_list", "subfactor_list"}:
                values[name] = ast.literal_eval(Resolve().visit(node.value))
    sf = {s["name"]: s["spectra"] for s in values["subfactor_list"]}
    scales = {s["name"]: s["subfactor"] for s in values["scale_list"]}
    return [dict(q, subfactor=scales[q["scale"]], spectrum=sf[scales[q["scale"]]])
            for q in values["questions_data"]]


def scale(values, reverse_indices=()):
    """Configured-item denominator; absent/blank/5 are missing, other tokens fail."""
    scored = []
    for i, value in enumerate(values):
        if value in (None, "", "5", 5):
            continue
        if str(value) not in {"1", "2", "3", "4"}:
            raise ValueError("Invalid response token")
        number = int(value)
        scored.append(5 - number if i in reverse_indices else number)
    n = len(values)
    missing = n - len(scored)
    valid = n > 0 and 4 * missing < n
    return dict(score=float(Fraction(sum(scored), len(scored))) if valid else None,
                is_valid=valid, total_items=n, missing_answers=missing,
                missing_percentage=100 * missing / n if n else 0,
                scored=scored, numerator=sum(scored), denominator=len(scored))


def scores(answers, key, *, present_only=False):
    groups = defaultdict(list)
    spectra = {}
    for q in key:
        if q.get("is_attention_check", False):
            continue
        if present_only and q["item_code"] not in answers:
            continue
        groups[q["scale"]].append(answers.get(q["item_code"]))
        spectra[q["scale"]] = q["spectrum"]
    scales = {name: scale(values) for name, values in groups.items()}
    buckets = defaultdict(list)
    for name, data in scales.items():
        buckets[spectra[name]].append(data)
    return scales, {name: spectrum(items) for name, items in buckets.items()}


def spectrum(scales):
    total = sum(s["total_items"] for s in scales)
    missing = sum(s["missing_answers"] for s in scales)
    valid = total > 0 and 4 * missing < total
    values = [s["score"] for s in scales if s["is_valid"] and s["score"] is not None]
    return dict(score=statistics.mean(values) if valid and values else None,
                is_valid=valid, total_items=total, missing_answers=missing,
                missing_percentage=100 * missing / total if total else 0)


def percentile(distribution, value):
    if value is None or not distribution:
        return None
    ordered = sorted(distribution)
    # Binary search instead of production's linear comparison count.
    return round(100 * bisect.bisect_right(ordered, value) / len(ordered))


def conventions(distribution, value):
    ordered = sorted(distribution)
    n = len(ordered)
    below = bisect.bisect_left(ordered, value)
    at = bisect.bisect_right(ordered, value)
    return dict(below=below, equal=at-below, n=n, strict=100*below/n,
                weak=100*at/n, midrank=50*(below+at)/n,
                average_rank=50*(below+at+(at>below))/n,
                production=percentile(ordered, value))


def quantile(values, p):
    ordered = sorted(values)
    pos = (len(ordered)-1)*p
    lo = int(pos)
    hi = min(lo+1, len(ordered)-1)
    return ordered[lo] + (ordered[hi]-ordered[lo])*(pos-lo)


def describe(values):
    return dict(n=len(values), mean=statistics.mean(values), median=statistics.median(values),
                sd=statistics.stdev(values) if len(values)>1 else 0,
                min=min(values), max=max(values),
                **{f"p{p}": quantile(values,p/100) for p in (5,10,25,50,75,90,95,99)})
