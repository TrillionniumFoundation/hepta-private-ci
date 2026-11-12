"""Frozen research controls for complete STOP and READ macros.

Training labels are independently admitted terminal macro returns. Public inputs
contain no references. Pins establish byte consistency, not receipt authority;
source-minimum residuals do not establish conditional coverage or policy benefit.
"""

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from .critic_context import (
    CriticContext,
    CriticContextError,
    context_digest,
    require_context,
)
from .metacontrol import _finite, _probability, _probability_head, _sha, _source_weights
from .metacontrol_macro_contract import SEQUENCES, digest

SCHEMA = "ndu.ctrl.frozen-macro-policy.v1"
METHODS = ("STOP", "light", "tuned-fixed", "point", "unconditional", "conditional")
LABELS = ("acquired", "selected_used", "effect_occurred")
ACTION_SHA256 = digest(
    {"schema": "ndu.ctrl.complete-macro-actions.v1", "sequences": SEQUENCES}
)


def source_sha256():
    root = Path(__file__).parent
    names = (
        "macro_policy.py",
        "macro_policy_checkpoint.py",
        "macro_public_state.py",
        "metacontrol.py",
        "critic_context.py",
        "metacontrol_macro_contract.py",
        "controllers.py",
        "objective.py",
    )
    return digest(
        {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    )


def _state(state):
    if type(state) is not dict or set(state) != {
        "features",
        "context_belief",
        "pending_evidence",
        "freshness_seconds",
        "remaining_seconds",
        "legal_macros",
    }:
        raise ValueError("Only the frozen current public macro fields are admitted")
    features, belief, legal = (
        state["features"],
        state["context_belief"],
        state["legal_macros"],
    )
    if (
        not isinstance(features, (list, tuple))
        or not 1 <= len(features) <= 128
        or any(not _finite(x) or abs(x) > 1e6 for x in features)
        or not isinstance(belief, (list, tuple))
        or not 1 <= len(belief) <= 8
        or any(not _finite(x) or not 0 <= x <= 1 for x in belief)
        or not math.isclose(sum(belief), 1, abs_tol=1e-9)
        or type(state["pending_evidence"]) is not bool
        or any(
            not _finite(state[k]) or not 0 <= state[k] <= 1e6
            for k in ("freshness_seconds", "remaining_seconds")
        )
        or not isinstance(legal, (list, tuple))
        or "STOP" not in legal
        or len(legal) != len(set(legal))
        or set(legal) - set(SEQUENCES)
    ):
        raise ValueError("Invalid bounded public macro state")
    raw = np.asarray(
        [
            *features,
            *belief,
            float(state["pending_evidence"]),
            math.log1p(state["freshness_seconds"]),
            math.log1p(state["remaining_seconds"]),
        ]
    )
    cell = json.dumps(
        [
            state["pending_evidence"],
            state["freshness_seconds"] > 1,
            int(np.argmax(belief)),
        ],
        separators=(",", ":"),
    )
    return raw, cell, [len(features), len(belief)]


def _pairs(rows, context):
    if not isinstance(rows, (list, tuple)) or not 1 <= len(rows) <= 10000:
        raise ValueError("A bounded nonempty macro pair inventory is required")
    for row in rows:
        if (
            type(row) is not dict
            or set(row)
            != {
                "schema",
                "source_id",
                "source_sha256",
                "decision_id",
                "context_sha256",
                "state",
                "branches",
                "labels",
                "label_receipts",
            }
            or row["schema"] != "ndu.ctrl.macro-pair.v1"
        ):
            raise ValueError("Primitive observations are not complete macro pairs")
        if not _sha(row["source_sha256"]):
            raise ValueError("Original registered source byte identity is required")
        if row["context_sha256"] != context_digest(context):
            raise CriticContextError("recalibration_required: pair context changed")
        if any(
            not isinstance(row[k], str) or not 0 < len(row[k]) <= 512
            for k in ("source_id", "decision_id")
        ):
            raise ValueError("Source and original decision identities are required")
        _state(row["state"])
        if set(row["state"]["legal_macros"]) != set(SEQUENCES):
            raise ValueError("Matched macro fitting requires both actions to be legal")
        if set(row["branches"]) != set(SEQUENCES):
            raise ValueError("Both complete macro meanings must be explicit")
        for macro, branch in row["branches"].items():
            if type(branch) is not dict or set(branch) != {
                "status",
                "quality",
                "cost",
                "full_cost_observed",
                "evidence_sha256",
                "initial_public_state_sha256",
                "public_state_sha256",
                "actions",
            }:
                raise ValueError("Incomplete macro evidence declaration")
            status, actions = branch["status"], branch["actions"]
            if (
                status
                not in {"COMPLETED", "FAILED", "CANCELLED", "UNKNOWN", "NOT_STARTED"}
                or type(actions) is not list
                or actions != SEQUENCES[macro][: len(actions)]
                or status == "COMPLETED"
                and actions != SEQUENCES[macro]
                or status == "NOT_STARTED"
                and (
                    actions
                    or branch["quality"] is not None
                    or branch["cost"] is not None
                    or branch["full_cost_observed"]
                )
                or type(branch["full_cost_observed"]) is not bool
                or not _sha(branch["initial_public_state_sha256"])
                or branch["public_state_sha256"] != digest(row["state"])
            ):
                raise ValueError(
                    "Macro terminal status, actions or state identity differs"
                )
            for key, bound in (("quality", 1), ("cost", 1e6)):
                value = branch[key]
                if value is not None and (
                    not _finite(value) or not 0 <= value <= bound
                ):
                    raise ValueError("Nonfinite, negative or unbounded outcome")
            evidence = branch["evidence_sha256"]
            if evidence is not None and not _sha(evidence):
                raise ValueError("Invalid original macro evidence digest")
            if any(branch[k] is not None for k in ("quality", "cost")) and not _sha(
                evidence
            ):
                raise ValueError("Observed outcomes require retained evidence")
            if branch["full_cost_observed"] and branch["cost"] is None:
                raise ValueError("Unknown cost cannot be complete")
        if (
            len({b["initial_public_state_sha256"] for b in row["branches"].values()})
            != 1
        ):
            raise ValueError("STOP and READ did not start at the same observed state")
        if set(row["labels"]) != set(LABELS) or set(row["label_receipts"]) != set(
            LABELS
        ):
            raise ValueError("Explicit known/unknown stage labels are required")
        for name in LABELS:
            value, pin = row["labels"][name], row["label_receipts"][name]
            if value is not None and (type(value) is not bool or not _sha(pin)):
                raise ValueError("Stage labels require their own original witness")
            if pin is not None and not _sha(pin):
                raise ValueError("Invalid stage witness digest")
    return rows


def _gain(row):
    branches = row["branches"]
    if any(
        b["status"] not in {"COMPLETED", "FAILED", "CANCELLED"}
        or b["quality"] is None
        or b["cost"] is None
        for b in branches.values()
    ):
        return None
    return (branches["READ"]["quality"] - branches["READ"]["cost"]) - (
        branches["STOP"]["quality"] - branches["STOP"]["cost"]
    )


def _mean(rows):
    groups = defaultdict(list)
    for source, value in rows:
        groups[source].append(value)
    return None if not groups else float(np.mean([np.mean(v) for v in groups.values()]))


def _lower(rows, alpha):
    groups = defaultdict(list)
    for source, residual in rows:
        groups[source].append(residual)
    minima = sorted(min(values) for values in groups.values())
    rank = math.floor((len(minima) + 1) * alpha)
    return {
        "source_groups": len(minima),
        "rank": rank,
        "lower_residual": minima[rank - 1] if rank >= 1 else None,
    }


def fit(train, calibration, *, context, expected_source_sha256, alpha=0.1, ridge=0.001):
    require_context(context)
    if context.action_sha256 != ACTION_SHA256:
        raise CriticContextError("Complete macro action identity is required")
    if expected_source_sha256 != source_sha256():
        raise ValueError("Fitting source differs from frozen implementation")
    if (
        not _finite(alpha)
        or not 0 < alpha <= 0.5
        or not _finite(ridge)
        or not 0 < ridge <= 1
    ):
        raise ValueError("Invalid fixed calibration or ridge parameter")
    train, calibration = _pairs(train, context), _pairs(calibration, context)
    all_rows = [*train, *calibration]
    identities = {(r["source_id"], r["source_sha256"]) for r in all_rows}
    if len(identities) != len({name for name, _ in identities}) or len(
        identities
    ) != len({pin for _, pin in identities}):
        raise ValueError("Source aliases or changed registered source bytes")
    sources = [{r["source_id"] for r in rows} for rows in (train, calibration)]
    if sources[0] & sources[1] or min(map(len, sources)) < 2:
        raise ValueError("Fit and calibration require disjoint source groups")
    ids = [r["decision_id"] for r in all_rows]
    pins = [
        b["evidence_sha256"]
        for r in all_rows
        for b in r["branches"].values()
        if b["evidence_sha256"] is not None
    ]
    if len(ids) != len(set(ids)) or len(pins) != len(set(pins)):
        raise ValueError("Repeated decisions or reused physical branch evidence")
    shape_pairs = {tuple(_state(r["state"])[2]) for r in all_rows}
    if len(shape_pairs) != 1:
        raise ValueError("Public feature schemas changed between partitions")
    known = [r for r in train if _gain(r) is not None]
    if len(known) < 4 or len({r["source_id"] for r in known}) < 2:
        raise ValueError("Need four observed comparisons from two training sources")
    raw = np.asarray([_state(r["state"])[0] for r in train])
    mask = np.asarray([_gain(r) is not None for r in train])
    observed = raw[mask]
    weights = _source_weights([r["source_id"] for r in known])
    minimum, maximum = observed.min(axis=0), observed.max(axis=0)
    # Positive-weight means lie in this envelope; remove floating-point overshoot.
    center = np.clip(np.average(observed, axis=0, weights=weights), minimum, maximum)
    scale = np.sqrt(np.average((observed - center) ** 2, axis=0, weights=weights))
    scale[scale < 1e-8] = 1
    x = np.column_stack([np.ones(len(train)), (raw - center) / scale])
    z, target = x[mask], np.asarray([_gain(r) for r in known])
    w = _source_weights([r["source_id"] for r in known])
    value = np.linalg.solve(
        z.T @ (w[:, None] * z) + ridge * len(z) * np.eye(z.shape[1]), z.T @ (w * target)
    )
    if not np.isfinite(value).all() or (np.abs(value) > 1e12).any():
        raise ValueError("Fitted weights exceed the finite numerical profile")
    light, residuals, conditional = defaultdict(list), [], defaultdict(list)
    for row in known:
        light[_state(row["state"])[1]].append((row["source_id"], _gain(row)))
    for row in calibration:
        v, cell, _ = _state(row["state"])
        gain = _gain(row)
        if gain is not None and np.all(v >= minimum) and np.all(v <= maximum):
            residual = gain - float(np.r_[1, (v - center) / scale] @ value)
            residuals.append((row["source_id"], residual))
            conditional[cell].append((row["source_id"], residual))
    cal_values = [
        (r["source_id"], _gain(r)) for r in calibration if _gain(r) is not None
    ]
    data = {
        "schema": SCHEMA,
        "context": context.to_wire(),
        "action_sha256": ACTION_SHA256,
        "source_sha256": expected_source_sha256,
        "shape": list(next(iter(shape_pairs))),
        "center": center.tolist(),
        "scale": scale.tolist(),
        "minimum": minimum.tolist(),
        "maximum": maximum.tolist(),
        "value": value.tolist(),
        "probability_heads": {
            name: _probability_head(
                x,
                [r["labels"][name] for r in train],
                ["READ"] * len(train),
                [r["source_id"] for r in train],
                ridge,
            )
            for name in LABELS
        },
        "light": {cell: _mean(rows) for cell, rows in light.items()},
        "tuned_fixed": "READ"
        if len(cal_values) == len(calibration) and _mean(cal_values) > 0
        else "STOP",
        "calibration": {
            "alpha": alpha,
            "unconditional": _lower(residuals, alpha),
            "conditional": {
                cell: _lower(rows, alpha) for cell, rows in conditional.items()
            },
            "complete": len(residuals) == len(calibration),
        },
        "fit_sources": sorted(sources[0]),
        "calibration_sources": sorted(sources[1]),
        "source_bindings": dict(sorted(identities)),
        "input_sha256": {"fit": digest(train), "calibration": digest(calibration)},
        "counts": {
            "fit": len(train),
            "fit_known_value": len(known),
            "calibration": len(calibration),
            "calibration_known_value": len(cal_values),
        },
        "full_cost_observed": all(
            _gain(r) is not None
            and all(b["full_cost_observed"] for b in r["branches"].values())
            for r in all_rows
        ),
        "production_update": "no-update",
    }
    raw_model = (
        json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()
    return load(raw_model, hashlib.sha256(raw_model).hexdigest(), context=context)


class MacroPolicy:
    def __init__(self, raw, data):
        self._raw, self.data = raw, data
        self.sha256 = hashlib.sha256(raw).hexdigest()
        self._data_sha256 = digest(data)

    def to_bytes(self):
        return self._raw

    def choose(
        self, state, policy, *, context, read_seconds_bound, finalizer_seconds_reserve
    ):
        raw, cell, shape = _state(state)
        if policy not in METHODS:
            raise ValueError("Unknown frozen macro policy")
        if any(
            not _finite(v) or v <= 0
            for v in (read_seconds_bound, finalizer_seconds_reserve)
        ):
            raise ValueError(
                "Positive action and finalization time reserves are required"
            )
        if state["remaining_seconds"] < finalizer_seconds_reserve:
            raise ValueError("No legal macro has the reserved finalizer budget")
        if (
            digest(self.data) != self._data_sha256
            or self.data["source_sha256"] != source_sha256()
        ):
            raise ValueError("Frozen policy or implementation changed")
        detail = {
            "macro": "STOP",
            "reason": "nonpositive_value",
            "score": None,
            "probabilities": {name: None for name in LABELS},
            "full_cost_observed": self.data["full_cost_observed"],
            "full_cost_scope": "fit_and_calibration_labels_only",
            "current_execution_cost_observed": False,
            "probabilities_calibrated": False,
            "conditional_coverage_guarantee": False,
            "policy_efficacy_evaluated": False,
            "production_update": "no-update",
        }
        try:
            require_context(context, CriticContext.from_wire(self.data["context"]))
        except CriticContextError:
            return "STOP", {
                **detail,
                "reason": "recalibration_required",
                "full_cost_observed": False,
            }
        if policy == "STOP":
            return "STOP", {**detail, "reason": "baseline"}
        if (
            "READ" not in state["legal_macros"]
            or read_seconds_bound + finalizer_seconds_reserve
            > state["remaining_seconds"]
        ):
            return "STOP", {**detail, "reason": "unavailable_or_insufficient_budget"}
        if shape != self.data["shape"]:
            return "STOP", {**detail, "reason": "public_shape_changed"}
        if policy == "tuned-fixed":
            macro = self.data["tuned_fixed"]
            return macro, {**detail, "macro": macro, "reason": "calibration_fixed"}
        if policy == "light":
            score = self.data["light"].get(cell)
        else:
            if np.any(raw < self.data["minimum"]) or np.any(raw > self.data["maximum"]):
                return "STOP", {**detail, "reason": "outside_observed_feature_envelope"}
            x = np.r_[1, (raw - self.data["center"]) / self.data["scale"]]
            detail["probabilities"] = {
                name: _probability(head, x)
                for name, head in self.data["probability_heads"].items()
            }
            score = float(x @ self.data["value"])
        if policy in {"unconditional", "conditional"}:
            cal = self.data["calibration"]
            correction = (
                cal["unconditional"]
                if policy == "unconditional"
                else cal["conditional"].get(cell)
            )
            if (
                not cal["complete"]
                or correction is None
                or correction["lower_residual"] is None
            ):
                return "STOP", {**detail, "reason": "insufficient_calibration"}
            score += correction["lower_residual"]
        if score is None:
            return "STOP", {**detail, "reason": "unobserved_public_cell"}
        if not _finite(score):
            raise ValueError("Nonfinite macro value")
        macro = "READ" if score > 0 else "STOP"
        return macro, {
            **detail,
            "macro": macro,
            "score": score,
            "reason": "positive_value" if score > 0 else "nonpositive_value",
        }


def load(raw, expected_sha256, *, context):
    from .macro_policy_checkpoint import read_checkpoint

    data = read_checkpoint(
        raw,
        expected_sha256,
        context=context,
        expected_action_sha256=ACTION_SHA256,
        expected_source_sha256=source_sha256(),
    )
    return MacroPolicy(raw, data)
