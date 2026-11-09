"""Observed execution and stop-relative value heads for bounded research control.

Only public state enters prediction. References and execution receipts enter
offline labels after an episode ends. Receipt hashes pin supplied evidence;
independent verification remains the collector's responsibility. Missing labels
stay unknown. Net-value targets include failed actions and are never multiplied
by predicted execution probability a second time.
"""

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import time

import numpy as np

from .controllers import ACTIONS

MODES = ("point", "unconditional", "conditional")
CONTINUATIONS = tuple(action for action in ACTIONS if action != "STOP")
MAX_PARAMETER_ABS = 1e12
MIN_SCALE = 1e-8


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _sha(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class PublicControlState:
    features: tuple
    context_belief: tuple
    pending_evidence: bool
    freshness_seconds: float
    legal_actions: tuple
    remaining_budget: float

    def __post_init__(self):
        if (
            not isinstance(self.features, tuple)
            or not 1 <= len(self.features) <= 128
            or not all(_finite(x) and abs(x) <= 1e6 for x in self.features)
        ):
            raise ValueError("Public features must be 1..128 bounded finite numbers")
        if (
            not isinstance(self.context_belief, tuple)
            or not 1 <= len(self.context_belief) <= 8
            or not all(_finite(x) and 0 <= x <= 1 for x in self.context_belief)
            or not math.isclose(sum(self.context_belief), 1, abs_tol=1e-9)
        ):
            raise ValueError("Context belief must be an observed probability simplex")
        if (
            type(self.pending_evidence) is not bool
            or not _finite(self.freshness_seconds)
            or self.freshness_seconds < 0
            or not _finite(self.remaining_budget)
            or self.remaining_budget < 0
        ):
            raise ValueError("Invalid pending evidence, freshness or remaining budget")
        if (
            not isinstance(self.legal_actions, tuple)
            or "STOP" not in self.legal_actions
            or len(set(self.legal_actions)) != len(self.legal_actions)
            or set(self.legal_actions) - set(ACTIONS)
        ):
            raise ValueError("Legal actions must belong to the installed runtime")

    @classmethod
    def from_wire(cls, value):
        if set(value) != set(cls.__dataclass_fields__):
            raise ValueError("Unknown public state field, target or future input")
        return cls(
            **{
                **value,
                "features": tuple(value["features"]),
                "context_belief": tuple(value["context_belief"]),
                "legal_actions": tuple(value["legal_actions"]),
            }
        )


@dataclass(frozen=True)
class ObservedContinuation:
    source_group: str
    decision_id: str
    state: PublicControlState
    action: str
    stop_quality: float
    continuation_quality: float
    incremental_cost: float | None
    full_cost_observed: bool
    selected_used: bool | None = None
    effect_occurred: bool | None = None
    identity_receipt_sha256: str | None = None
    effect_receipt_sha256: str | None = None

    def __post_init__(self):
        if not all(
            isinstance(x, str) and 0 < len(x) <= 512
            for x in (self.source_group, self.decision_id)
        ):
            raise ValueError("Every paired label needs source and decision identities")
        if (
            not isinstance(self.state, PublicControlState)
            or self.action == "STOP"
            or self.action not in self.state.legal_actions
        ):
            raise ValueError("Train only legal continuation comparisons against STOP")
        if not all(
            _finite(x) and 0 <= x <= 1
            for x in (self.stop_quality, self.continuation_quality)
        ):
            raise ValueError("Paired independent quality scores must lie in [0,1]")
        if self.incremental_cost is not None and (
            not _finite(self.incremental_cost) or not 0 <= self.incremental_cost <= 1e6
        ):
            raise ValueError(
                "Incremental continuation cost must be nonnegative or unknown"
            )
        if type(self.full_cost_observed) is not bool or (
            self.full_cost_observed and self.incremental_cost is None
        ):
            raise ValueError("Unknown cost cannot be a complete-cost observation")
        for label, receipt in (
            (self.selected_used, self.identity_receipt_sha256),
            (self.effect_occurred, self.effect_receipt_sha256),
        ):
            if label is not None and (type(label) is not bool or not _sha(receipt)):
                raise ValueError(
                    "Execution/effect labels require their own pinned receipts"
                )
            if receipt is not None and not _sha(receipt):
                raise ValueError("Invalid evidence digest")

    @property
    def net_gain(self):
        return (
            None
            if self.incremental_cost is None
            else (self.continuation_quality - self.stop_quality - self.incremental_cost)
        )


def _base(state):
    return np.asarray(
        (
            *state.features,
            *state.context_belief,
            float(state.pending_evidence),
            math.log1p(state.freshness_seconds),
            math.log1p(state.remaining_budget),
        ),
        dtype=float,
    )


def _cell(state, action):
    # Public, predeclared cells; no outcome-dependent grouping.
    return (
        action,
        state.pending_evidence,
        state.freshness_seconds > 1,
        int(np.argmax(state.context_belief)),
    )


def _records(records):
    rows = tuple(records)
    if (
        not rows
        or len(rows) > 100000
        or any(not isinstance(row, ObservedContinuation) for row in rows)
    ):
        raise ValueError("Expected a nonempty bounded observation collection")
    if len({row.decision_id for row in rows}) != len(rows):
        raise ValueError("Repeated decision IDs would duplicate one observation")
    return rows


def _source_weights(groups):
    counts = Counter(groups)
    return np.asarray([len(groups) / (len(counts) * counts[group]) for group in groups])


def _probability_head(x, labels, actions, groups, ridge):
    mask = np.asarray([label is not None for label in labels])
    y = np.asarray([float(label) for label in labels if label is not None])
    result = {
        "labelled": len(y),
        "positive": int(y.sum()),
        "weights": None,
        "constant": None,
        "status": "unobserved",
        "supported_actions": sorted(
            {action for action, label in zip(actions, labels) if label is not None}
        ),
    }
    if not len(y):
        return result
    label_groups = [group for group, present in zip(groups, mask) if present]
    group_count = len(set(label_groups))
    weights_by_source = _source_weights(label_groups)
    result["labelled_source_groups"] = group_count
    if len(set(y)) == 1:
        result.update(
            constant=float((float(y[0]) * group_count + 1) / (group_count + 2)),
            status="single_class_smoothed_base_rate",
        )
        return result
    z, weights = x[mask], np.zeros(x.shape[1])
    step = 1 / (0.25 * float(np.square(z).sum(axis=1).max()) + ridge)
    for _ in range(1200):
        p = 1 / (1 + np.exp(-np.clip(z @ weights, -40, 40)))
        gradient = z.T @ (weights_by_source * (p - y)) / len(y) + ridge * weights
        weights -= step * gradient
        if float(np.max(np.abs(gradient))) < 1e-7:
            break
    result.update(weights=weights.tolist(), status="two_class_logistic")
    return result


def _probability(head, x):
    if head["weights"] is None:
        constant = head["constant"]
        if constant is not None and (not _finite(constant) or not 0 <= constant <= 1):
            raise ValueError("Nonfinite or invalid execution probability")
        return constant
    with np.errstate(over="ignore", invalid="ignore"):
        logit = float(np.dot(x, head["weights"]))
    if not _finite(logit):
        raise ValueError("Nonfinite derived execution logit")
    return 1 / (1 + math.exp(-max(-40, min(40, logit))))


class MetacontrolHeads:
    """Observed-value critic and separate execution/effect diagnostics.

    Residual quantiles group independent sources. Conditional cells are finite
    public-state strata, not a conditional coverage theorem. The caller supplies
    a legal, already-accounted light fallback. This grants no native admission,
    production update or complete-cost certification.
    """

    def _vector(self, state, action):
        if (len(state.features), len(state.context_belief)) != self.shape:
            raise ValueError("Public feature or context profile differs from training")
        if action not in CONTINUATIONS or action not in state.legal_actions:
            raise ValueError("Unsupported or illegal continuation")
        value = _base(state)
        if np.any(value < self.minimum - 1e-9) or np.any(value > self.maximum + 1e-9):
            raise ValueError("Public state outside observed training envelope")
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            base = np.r_[1, (value - self.mean) / self.scale]
            vector = np.outer(
                np.eye(len(CONTINUATIONS))[CONTINUATIONS.index(action)], base
            ).ravel()
        if not bool(np.isfinite(vector).all()):
            raise ValueError("Nonfinite derived public-state vector")
        return vector

    def predict(self, state, action):
        if action not in self.supported_actions:
            raise ValueError("No observed-cost value labels for this action")
        x = self._vector(state, action)
        with np.errstate(over="ignore", invalid="ignore"):
            net_gain = float(x @ self.value_weights)
        if not _finite(net_gain):
            raise ValueError("Nonfinite derived continuation value")
        return {
            "net_gain": net_gain,
            "selected_used_probability": _probability(self.identity_head, x)
            if action in self.identity_head["supported_actions"]
            else None,
            "effect_occurred_probability": _probability(self.effect_head, x)
            if action in self.effect_head["supported_actions"]
            else None,
            "full_cost_observed": self.receipt["full_cost_observed"],
            "full_cost_scope": "training_labels_only",
            "probability_is_semantic_correctness": False,
        }

    def calibrate(self, records, *, alpha=0.1):
        if self.calibration is not None:
            raise ValueError(
                "Calibration is frozen; fit a new candidate to recalibrate"
            )
        rows = _records(records)
        groups = {row.source_group for row in rows}
        if groups & self.training_groups or not _finite(alpha) or not 0 < alpha < 0.5:
            raise ValueError("Calibration needs disjoint sources and valid alpha")
        grouped, conditional, unsupported = {}, {}, 0
        for row in rows:
            if row.net_gain is None:
                continue
            try:
                residual = (
                    row.net_gain - self.predict(row.state, row.action)["net_gain"]
                )
            except ValueError:
                unsupported += 1
                continue
            grouped.setdefault(row.source_group, []).append(residual)
            conditional.setdefault(_cell(row.state, row.action), {}).setdefault(
                row.source_group, []
            ).append(residual)

        def quantile(values):
            minima = sorted(min(errors) for errors in values.values())
            rank = math.floor((len(minima) + 1) * alpha)
            return {
                "groups": len(minima),
                "rank": rank,
                "lower_residual": minima[rank - 1] if rank >= 1 else None,
            }

        self.calibration_groups = groups
        self.calibration = {
            "alpha": alpha,
            "records_sha256": _digest([asdict(row) for row in rows]),
            "rows": len(rows),
            "known_cost_rows": sum(row.net_gain is not None for row in rows),
            "full_cost_observed": all(row.full_cost_observed for row in rows),
            "unconditional": quantile(grouped),
            "conditional": {key: quantile(value) for key, value in conditional.items()},
        }
        return {
            "groups": len(groups),
            "known_cost_rows": sum(r.net_gain is not None for r in rows),
            "conditional_cells": len(conditional),
            "unsupported_rows": unsupported,
            "conditional_coverage_guarantee": False,
            "records_sha256": self.calibration["records_sha256"],
            "training_full_cost_observed": self.receipt["full_cost_observed"],
            "calibration_full_cost_observed": self.calibration["full_cost_observed"],
            "unconditional": self.calibration["unconditional"],
        }

    def choose(
        self,
        state,
        *,
        mode="point",
        light_action="STOP",
        margin=0.0,
        action_cost_bounds=None,
        finalization_reserve=0.0,
    ):
        started = time.perf_counter()
        if mode not in MODES or light_action not in state.legal_actions:
            raise ValueError("Unknown mode or illegal light fallback")
        if (
            not _finite(margin)
            or margin < 0
            or not _finite(finalization_reserve)
            or finalization_reserve < 0
        ):
            raise ValueError(
                "Nonnegative finite gain margin and terminal reserve required"
            )
        bounds = {} if action_cost_bounds is None else dict(action_cost_bounds)
        if set(bounds) - set(CONTINUATIONS) or any(
            not _finite(value) or value <= 0 for value in bounds.values()
        ):
            raise ValueError(
                "Cost ceilings must be positive, predeclared owner budget units"
            )
        affordable = {
            action
            for action, cost in bounds.items()
            if cost + finalization_reserve <= state.remaining_budget
            and state.remaining_budget > 0
        }
        if light_action != "STOP" and light_action not in affordable:
            light_action = "STOP"
        scores, unavailable = {"STOP": 0.0}, {}
        for action in state.legal_actions:
            if action == "STOP":
                continue
            if action not in affordable:
                unavailable[action] = (
                    "Missing cost ceiling or insufficient reserved budget"
                )
                continue
            try:
                score = self.predict(state, action)["net_gain"]
                if mode != "point":
                    if self.calibration is None:
                        raise ValueError("No frozen source-disjoint calibration")
                    cell = (
                        self.calibration["unconditional"]
                        if mode == "unconditional"
                        else self.calibration["conditional"].get(_cell(state, action))
                    )
                    if cell is None or cell["lower_residual"] is None:
                        raise ValueError("Insufficient calibration source groups")
                    score += cell["lower_residual"]
                score -= margin
                if not _finite(score):
                    raise ValueError("Nonfinite corrected continuation value")
                scores[action] = score
            except ValueError as error:
                unavailable[action] = str(error)
        fallback = bool(unavailable) or len(scores) == 1
        selected = light_action if fallback else max(scores, key=scores.get)
        calibration_costs = (
            None if self.calibration is None else self.calibration["full_cost_observed"]
        )
        input_costs_complete = (
            not fallback
            and self.receipt["full_cost_observed"]
            and (mode == "point" or calibration_costs is True)
        )
        return selected, {
            "scores_relative_to_stop": scores,
            "unsupported": unavailable,
            "fallback": fallback,
            "mode": mode,
            "training_full_cost_observed": self.receipt["full_cost_observed"],
            "calibration_full_cost_observed": calibration_costs,
            "full_cost_observed": input_costs_complete,
            "full_cost_scope": "labels for the model-selected action; current owner costs still pending",
            "cost_disposition": "INPUT_COSTS_COMPLETE"
            if input_costs_complete
            else "HOLD",
            "controller_seconds": time.perf_counter() - started,
            "controller_cost_requires_caller_accounting": True,
            "action_cost_bounds": bounds,
            "finalization_reserve": finalization_reserve,
            "owner_predispatch_budget_check_required": True,
            "production_update": "no-update",
        }

    def diagnostics(self, records):
        if self.calibration is None:
            raise ValueError("Freeze calibration before accessing future diagnostics")
        rows = _records(records)
        if {r.source_group for r in rows} & (
            self.training_groups | self.calibration_groups
        ):
            raise ValueError("Future diagnostic sources overlap fit or calibration")
        predictions, unsupported = [], 0
        for row in rows:
            try:
                predictions.append((row, self.predict(row.state, row.action)))
            except ValueError:
                unsupported += 1
        result = {
            "source_groups": len({r.source_group for r in rows}),
            "rows": len(rows),
            "unsupported_rows": unsupported,
            "full_cost_observed": all(r.full_cost_observed for r in rows),
            "conditional_coverage_guarantee": False,
            "production_update": "no-update",
        }
        for label, key in (
            ("selected_used", "selected_used_probability"),
            ("effect_occurred", "effect_occurred_probability"),
        ):
            labelled = [
                (row.source_group, float(getattr(row, label)), prediction[key])
                for row, prediction in predictions
                if getattr(row, label) is not None and prediction[key] is not None
            ]
            pairs = [(y, p) for _, y, p in labelled]
            source_weights = _source_weights([group for group, _, _ in labelled])
            ece, bins = 0.0, []
            source_ece = 0.0
            for index in range(10):
                bucket = [(y, p) for y, p in pairs if min(int(p * 10), 9) == index]
                if bucket:
                    accuracy = float(np.mean([y for y, _ in bucket]))
                    confidence = float(np.mean([p for _, p in bucket]))
                    ece += len(bucket) * abs(accuracy - confidence) / len(pairs)
                    bins.append(
                        {
                            "bin": index,
                            "n": len(bucket),
                            "observed": accuracy,
                            "predicted": confidence,
                        }
                    )
                    weighted = [
                        (y, p, w)
                        for (y, p), w in zip(pairs, source_weights)
                        if min(int(p * 10), 9) == index
                    ]
                    source_ece += abs(sum(w * (y - p) for y, p, w in weighted)) / len(
                        pairs
                    )
            result[label] = {
                "labelled": len(pairs),
                "missing_labels": sum(getattr(r, label) is None for r in rows),
                "bins": bins,
                "brier": float(np.mean([(p - y) ** 2 for y, p in pairs]))
                if pairs
                else None,
                "ece": ece if pairs else None,
                "row_metrics_weighting": "each supported labelled row equally",
                "labelled_source_groups": len({group for group, _, _ in labelled}),
                "source_balanced_brier": float(
                    np.average([(p - y) ** 2 for y, p in pairs], weights=source_weights)
                )
                if pairs
                else None,
                "source_balanced_ece": source_ece if pairs else None,
                "observed_classes": sorted({int(y) for y, _ in pairs}),
            }
        errors = [
            (prediction["net_gain"] - row.net_gain) ** 2
            for row, prediction in predictions
            if row.net_gain is not None
        ]
        result["net_gain_mse"] = float(np.mean(errors)) if errors else None
        value_groups = [
            row.source_group for row, _ in predictions if row.net_gain is not None
        ]
        result["source_balanced_net_gain_mse"] = (
            float(np.average(errors, weights=_source_weights(value_groups)))
            if errors
            else None
        )
        return result

    def snapshot(self):
        calibration = (
            None
            if self.calibration is None
            else {
                **self.calibration,
                "conditional": [
                    [list(key), value]
                    for key, value in sorted(self.calibration["conditional"].items())
                ],
            }
        )
        return {
            "receipt": self.receipt,
            "value": self.value_weights.tolist(),
            "identity": self.identity_head,
            "effect": self.effect_head,
            "mean": self.mean.tolist(),
            "scale": self.scale.tolist(),
            "minimum": self.minimum.tolist(),
            "maximum": self.maximum.tolist(),
            "shape": list(self.shape),
            "supported_actions": sorted(self.supported_actions),
            "training_groups": sorted(self.training_groups),
            "calibration_groups": sorted(self.calibration_groups),
            "calibration": calibration,
        }

    def identity(self):
        return _digest(self.snapshot())


def fit_heads(records, *, ridge=0.001):
    """Fit identical point critic for all residual modes; no DP or future calls."""
    started = time.perf_counter()
    rows = _records(records)
    if not _finite(ridge) or not 0 < ridge <= 1:
        raise ValueError("Ridge penalty must be positive and bounded")
    if len({(len(r.state.features), len(r.state.context_belief)) for r in rows}) != 1:
        raise ValueError("Training mixes incompatible public-state profiles")
    known = np.asarray([r.net_gain is not None for r in rows])
    if (
        int(known.sum()) < 4
        or len({r.source_group for r in rows if r.net_gain is not None}) < 2
    ):
        raise ValueError(
            "Need at least four observed comparisons from two source groups"
        )
    candidate = MetacontrolHeads()
    candidate.shape = (len(rows[0].state.features), len(rows[0].state.context_belief))
    raw = np.asarray([_base(r.state) for r in rows])
    candidate.minimum, candidate.maximum = raw.min(axis=0), raw.max(axis=0)
    source_weights = _source_weights([r.source_group for r in rows])
    candidate.mean = np.average(raw, axis=0, weights=source_weights)
    candidate.scale = np.sqrt(
        np.average((raw - candidate.mean) ** 2, axis=0, weights=source_weights)
    )
    candidate.scale[candidate.scale < MIN_SCALE] = 1.0
    x = np.asarray([candidate._vector(r.state, r.action) for r in rows])
    target = np.asarray([r.net_gain for r in rows if r.net_gain is not None])
    z = x[known]
    weights = _source_weights([r.source_group for r in rows if r.net_gain is not None])
    candidate.value_weights = np.linalg.solve(
        z.T @ (weights[:, None] * z) + ridge * len(z) * np.eye(z.shape[1]),
        z.T @ (weights * target),
    )
    if not bool(np.isfinite(candidate.value_weights).all()) or np.any(
        np.abs(candidate.value_weights) > MAX_PARAMETER_ABS
    ):
        raise ValueError("Fitted continuation weights exceed the numeric profile")
    actions = [r.action for r in rows]
    groups = [r.source_group for r in rows]
    candidate.identity_head = _probability_head(
        x, [r.selected_used for r in rows], actions, groups, ridge
    )
    candidate.effect_head = _probability_head(
        x, [r.effect_occurred for r in rows], actions, groups, ridge
    )
    candidate.training_groups = {r.source_group for r in rows}
    candidate.calibration_groups, candidate.calibration = set(), None
    candidate.supported_actions = {r.action for r in rows if r.net_gain is not None}
    candidate.receipt = {
        "schema": "ndu.real.metacontrol-fit.v1",
        "rows": len(rows),
        "training_groups": sorted(candidate.training_groups),
        "known_cost_rows": int(known.sum()),
        "terminal_targets": 0,
        "teacher": "observed_paired_stop_and_continuation",
        "value_fit": "source_balanced_deterministic_linear_ridge_exact_solve",
        "source_balanced_training_mse": float(
            np.average((z @ candidate.value_weights - target) ** 2, weights=weights)
        ),
        "numeric_support": "coordinatewise_observed_envelope_only",
        "semantic_ood_guarantee": False,
        "ridge": ridge,
        "training_seconds": time.perf_counter() - started,
        "training_records_sha256": _digest([asdict(r) for r in rows]),
        "full_cost_observed": all(r.full_cost_observed for r in rows),
        "production_update": "no-update",
    }
    return candidate
