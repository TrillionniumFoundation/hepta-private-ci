"""Research shadow heads on complete observed cases; no production integration.

Receipt validation and estimands are defined in control_observations. Calibrated
residuals are descriptive; they do not prove conditional or all-attempt coverage.
"""

from dataclasses import dataclass, replace
import math

from .control_observations import (
    ACTIONS as ACTIONS,
    COSTS as COSTS,
    PublicState as PublicState,
    state_digest as state_digest,
    implementation_label as implementation_label,
    continuation_label as continuation_label,
    _implementation_row_label,
)


def _features(state):
    if type(state) is not PublicState:
        raise ValueError("Inference accepts PublicState only, never label records")
    return (
        1.0,
        state.belief,
        float(state.pending_evidence),
        state.freshness / (1 + state.freshness),
        state.budget / (1 + state.budget),
        *(float(state.action == a) for a in ACTIONS),
    )


def _context(state):
    return state.context, state.action, tuple(sorted(state.legal_actions))


def _dot(weights, features):
    return math.fsum(w * x for w, x in zip(weights, features, strict=True))


def _point(weights, state, probability):
    if weights is None:
        return None
    value = _dot(weights, _features(state))
    return 1 / (1 + math.exp(-max(-40, min(40, value)))) if probability else value


@dataclass(frozen=True)
class Heads:
    probability: tuple | None
    value: tuple | None
    support: tuple
    training_sources: tuple
    feature_bounds: tuple
    calibration_sources: tuple = ()
    residuals: tuple = ()
    unknown_training_labels: tuple = ()


def _rows(rows, split, excluded=()):
    rows = list(rows)
    if len(rows) > 4096:
        raise ValueError("Research row cap exceeded")
    seen = set()
    for row in rows:
        if (
            row.get("split") != split
            or type(row.get("source_id")) is not str
            or not row["source_id"]
            or row["source_id"] in excluded
            or type(row.get("observation_id")) is not str
            or not row["observation_id"]
            or row["observation_id"] in seen
        ):
            raise ValueError(
                "Wrong partition, overlapping source or duplicate observation"
            )
        seen.add(row["observation_id"])
        _features(row["state"])
    return rows


def fit_heads(training_rows):
    """Small regularized logistic/linear heads; equal total weight per source.

    Fixed training schedule; caller freezes these weights before calibration or
    future evaluation. Input provenance must be independently authenticated outside
    this module; flags and hashes alone cannot prove observations are real.
    """
    rows = _rows(training_rows, "train")
    weights, supports, bounds, unknown = [], [], [], []
    for name, label in (
        ("implementation", _implementation_row_label),
        ("value", continuation_label),
    ):
        labelled = [(r, label(r)) for r in rows]
        admitted = [(r, y) for r, y in labelled if y is not None]
        unknown.append(sum(y is None for _, y in labelled))
        counts = {
            r["source_id"]: sum(x["source_id"] == r["source_id"] for x, _ in admitted)
            for r, _ in admitted
        }
        w = [0.0] * 9
        for _ in range(400 if admitted else 0):
            gradient = [0.0] * len(w)
            for row, target in admitted:
                x = _features(row["state"])
                predicted = _point(tuple(w), row["state"], name == "implementation")
                scale = (predicted - target) / (counts[row["source_id"]] * len(counts))
                for i, feature in enumerate(x):
                    gradient[i] += scale * feature
            w = [v - 0.1 * (g + 0.01 * v) for v, g in zip(w, gradient, strict=True)]
        weights.append(tuple(w) if admitted else None)
        supports.append(tuple(sorted({_context(r["state"]) for r, _ in admitted})))
        cells = []
        for key in supports[-1]:
            vectors = [
                _features(r["state"])
                for r, _ in admitted
                if _context(r["state"]) == key
            ]
            cells.append(
                (key, tuple((min(x), max(x)) for x in zip(*vectors, strict=True)))
            )
        bounds.append(tuple(cells))
    return Heads(
        *weights,
        tuple(supports),
        tuple(sorted({r["source_id"] for r in rows})),
        tuple(bounds),
        unknown_training_labels=tuple(unknown),
    )


def _supported(heads, index, state):
    domain = dict(heads.feature_bounds[index]).get(_context(state))
    return domain is not None and all(
        low - 1e-12 <= x <= high + 1e-12
        for x, (low, high) in zip(_features(state), domain, strict=True)
    )


def calibrate_heads(heads, calibration_rows, *, alpha=0.1):
    """Freeze group-max absolute residuals on disjoint calibration sources."""
    if not 0 < alpha < 1 or heads.calibration_sources:
        raise ValueError("Valid alpha and one fresh calibration partition required")
    rows = _rows(calibration_rows, "calibration", heads.training_sources)
    summaries = []
    for index, (name, label) in enumerate(
        (("implementation", _implementation_row_label), ("value", continuation_label))
    ):
        groups = {}
        for row in rows:
            key, target = _context(row["state"]), label(row)
            point = _point(
                getattr(heads, "probability" if index == 0 else "value"),
                row["state"],
                index == 0,
            )
            if (
                target is None
                or point is None
                or not _supported(heads, index, row["state"])
            ):
                continue
            for context in (None, key):
                cell = groups.setdefault(context, {})
                cell[row["source_id"]] = max(
                    cell.get(row["source_id"], 0), abs(point - target)
                )
        for context, by_source in groups.items():
            values = sorted(by_source.values())
            rank = math.ceil((len(values) + 1) * (1 - alpha))
            summaries.append(
                (
                    name,
                    context,
                    len(values),
                    values[rank - 1] if rank <= len(values) else None,
                )
            )
    return replace(
        heads,
        calibration_sources=tuple(sorted({r["source_id"] for r in rows})),
        residuals=tuple(summaries),
    )


def predict(heads, state):
    """Shadow inference has no reference, outcome, receipt or future-label input."""
    _features(state)
    output = {
        "shadow_only": True,
        "production_admitted": False,
        "conditional_coverage_proved": False,
        "estimand_scope": "complete_observed_cases",
    }
    key = _context(state)
    for index, (name, weights) in enumerate(
        (("implementation", heads.probability), ("value", heads.value))
    ):
        point = (
            _point(weights, state, index == 0)
            if _supported(heads, index, state)
            else None
        )
        residuals = {
            context: (count, radius)
            for head, context, count, radius in heads.residuals
            if head == name
        }
        output[name] = {
            "point": point,
            "supported": point is not None,
            "unconditional_residual": residuals.get(None),
            "conditional_residual": residuals.get(key),
        }
    return output
