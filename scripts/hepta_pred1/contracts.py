"""PRED-1 evidence contracts; structural checks do not authenticate receipts.

Effect times are elapsed durations, while observed_at is the arrival timestamp.
Coarsened likelihood needs a known/ignorable observation mechanism; this module
does not turn informative missingness into valid supervision automatically.
"""

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from itertools import product
import json
import math
from numbers import Integral, Real

import numpy as np


class EvidenceSource(str, Enum):
    REAL = "real"
    SIMULATOR = "simulator"
    IMAGINED = "imagined"


class ObservationStatus(str, Enum):
    TERMINAL = "terminal"
    VERIFIED_ONGOING = "verified_ongoing"
    RECEIPT_MISSING = "receipt_missing"
    AWAITING = "awaiting"
    CANCEL_REQUESTED = "cancel_requested"


class EffectTimeKind(str, Enum):
    EXACT = "exact"
    INTERVAL = "interval"
    RIGHT_CENSORED = "right_censored"
    UNOBSERVED = "unobserved"


OUTCOMES = (0, 1)
TIMES = (1, 2, 4, 8)
COSTS = (1, 2, 4, 8)
JOINT_SUPPORT = np.asarray(list(product(OUTCOMES, TIMES, COSTS)), dtype=float)
JOINT_SUPPORT.setflags(write=False)


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _nonnegative(value, name):
    value = _finite(value, name)
    if value < 0:
        raise ValueError(f"{name} cannot be negative")
    return value


def _outcome(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, Integral)
        or value not in OUTCOMES
    ):
        raise ValueError("outcome must be integer 0 or 1")
    return int(value)


def _reference(value, name):
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValueError(f"{name} must be a nonempty reference")
    return value


@dataclass(frozen=True)
class Evidence:
    source: EvidenceSource = EvidenceSource.REAL
    observation_status: ObservationStatus = ObservationStatus.AWAITING
    outcome: int | None = None
    time_kind: EffectTimeKind = EffectTimeKind.UNOBSERVED
    time_lower: float | None = None
    time_upper: float | None = None
    observed_at: float = 0.0
    confirmed_cost_lower_bound: float = 0.0
    final_cost: float | None = None
    receipt_ref: str | None = None
    nonoccurrence_witness: str | None = None

    def __post_init__(self):
        for name, kind in (
            ("source", EvidenceSource),
            ("observation_status", ObservationStatus),
            ("time_kind", EffectTimeKind),
        ):
            object.__setattr__(self, name, kind(getattr(self, name)))
        for name in ("observed_at", "confirmed_cost_lower_bound"):
            object.__setattr__(self, name, _nonnegative(getattr(self, name), name))
        for name in ("final_cost", "time_lower", "time_upper"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _nonnegative(value, name))
        if self.outcome is not None:
            object.__setattr__(self, "outcome", _outcome(self.outcome))
        for name in ("receipt_ref", "nonoccurrence_witness"):
            _reference(getattr(self, name), name)
        if (
            self.final_cost is not None
            and self.final_cost < self.confirmed_cost_lower_bound
        ):
            raise ValueError("final cost cannot be below confirmed cost")
        if self.time_kind == EffectTimeKind.EXACT and self.time_upper is None:
            object.__setattr__(self, "time_upper", self.time_lower)
        lo, hi = self.time_lower, self.time_upper
        if self.time_kind == EffectTimeKind.UNOBSERVED:
            if lo is not None or hi is not None:
                raise ValueError("unobserved time cannot carry bounds")
        elif self.time_kind == EffectTimeKind.EXACT:
            if lo is None or lo != hi:
                raise ValueError("exact time requires equal finite bounds")
        elif self.time_kind == EffectTimeKind.INTERVAL:
            if lo is None or hi is None or lo >= hi:
                raise ValueError(
                    "interval requires 0 <= lower < upper; semantics are (lower, upper]"
                )
        elif lo is None or hi is not None:
            raise ValueError(
                "right censoring requires a lower bound and no upper bound"
            )
        if self.observation_status == ObservationStatus.TERMINAL:
            if self.outcome is None or self.receipt_ref is None:
                raise ValueError(
                    "terminal outcome requires a real readback or simulator receipt"
                )
            if self.time_kind == EffectTimeKind.RIGHT_CENSORED:
                raise ValueError(
                    "terminal evidence cannot assert ongoing right censoring"
                )
        else:
            if self.outcome is not None or self.final_cost is not None:
                raise ValueError(
                    "nonterminal evidence cannot settle outcome or final cost"
                )
            if self.observation_status == ObservationStatus.VERIFIED_ONGOING:
                if (
                    self.time_kind != EffectTimeKind.RIGHT_CENSORED
                    or self.nonoccurrence_witness is None
                ):
                    raise ValueError(
                        "verified ongoing needs a nonoccurrence witness and cutoff"
                    )
            elif (
                self.time_kind != EffectTimeKind.UNOBSERVED
                or self.nonoccurrence_witness is not None
            ):
                raise ValueError(
                    "missing ACK, awaiting, or cancel request is not nonoccurrence evidence"
                )


def allowed_mask(evidence: Evidence) -> np.ndarray:
    """Admit factual labels, using (lower, upper] intervals and T > cutoff.

    Unknown receipts constrain only confirmed cost, never outcome/effect time.
    Empty support is an error: extend the grid instead of clipping the evidence.
    """
    if not isinstance(evidence, Evidence) or evidence.source == EvidenceSource.IMAGINED:
        raise ValueError("factual label admission requires real or simulator Evidence")
    y, t, c = JOINT_SUPPORT.T
    mask = c >= evidence.confirmed_cost_lower_bound
    if evidence.outcome is not None:
        mask &= y == evidence.outcome
    if evidence.final_cost is not None:
        mask &= c == evidence.final_cost
    if evidence.time_kind == EffectTimeKind.EXACT:
        mask &= t == evidence.time_lower
    elif evidence.time_kind == EffectTimeKind.INTERVAL:
        mask &= (t > evidence.time_lower) & (t <= evidence.time_upper)
    elif evidence.time_kind == EffectTimeKind.RIGHT_CENSORED:
        mask &= t > evidence.time_lower
    if not mask.any():
        raise ValueError("evidence has no compatible atom in the finite joint support")
    return mask


def _probabilities(probabilities):
    p = np.asarray(probabilities, dtype=float)
    if p.ndim != 1 or not p.size or not np.isfinite(p).all() or (p < 0).any():
        raise ValueError("probabilities must be a finite nonnegative vector")
    total = float(p.sum())
    if not math.isclose(total, 1.0, rel_tol=1e-7, abs_tol=1e-10):
        raise ValueError("probabilities must sum to one")
    return p / total


def coarsened_nll(probabilities, mask) -> float:
    """-log P(compatible evidence); zero model mass yields infinity, not clipping."""
    p, mask = _probabilities(probabilities), np.asarray(mask)
    if mask.dtype != np.bool_ or mask.shape != p.shape or not mask.any():
        raise ValueError("mask must be a nonempty boolean event matching probabilities")
    mass = float(p[mask].sum())
    return -math.log(mass) if mass else math.inf


def brier_score(outcome_probability, outcome) -> float:
    """Binary convention: (P(Y=1)-Y)^2, without a redundant class factor of two."""
    p = _finite(outcome_probability, "outcome probability")
    if not 0 <= p <= 1:
        raise ValueError("outcome probability must lie in [0, 1]")
    return (p - _outcome(outcome)) ** 2


def crps_score(values, probabilities, observed) -> float:
    """Exact finite-distribution CRPS, including the full pairwise expectation."""
    x, p = np.asarray(values, dtype=float), _probabilities(probabilities)
    if x.shape != p.shape or not np.isfinite(x).all():
        raise ValueError("support must be a matching finite vector")
    y = _finite(observed, "observed value")
    return float(
        p @ np.abs(x - y) - 0.5 * (p[:, None] * p * np.abs(x[:, None] - x)).sum()
    )


def score_exact(probabilities, outcome, time, cost) -> dict:
    """Oracle/evaluator-only scores for a fully observed grid-valued target."""
    p = _probabilities(probabilities)
    target = (_outcome(outcome), _nonnegative(time, "time"), _nonnegative(cost, "cost"))
    if p.shape != (len(JOINT_SUPPORT),):
        raise ValueError("joint probabilities must match JOINT_SUPPORT")
    exact = np.all(JOINT_SUPPORT == target, axis=1)
    if not exact.any():
        raise ValueError("exact target lies outside finite joint support")
    joint = p.reshape(len(OUTCOMES), len(TIMES), len(COSTS))
    return {
        "outcome_brier": brier_score(joint[1].sum(), outcome),
        "time_crps": crps_score(TIMES, joint.sum(axis=(0, 2)), time),
        "cost_crps": crps_score(COSTS, joint.sum(axis=(0, 1)), cost),
        "joint_nll": coarsened_nll(p, exact),
    }


@dataclass(frozen=True, init=False)
class FrozenObservation:
    """A copied JSON payload with its actual availability time, not effect time."""

    observed_at: float
    evidence_ref: str
    _payload_json: str

    def __init__(self, observed_at, payload, evidence_ref):
        object.__setattr__(
            self, "observed_at", _nonnegative(observed_at, "observed_at")
        )
        if _reference(evidence_ref, "evidence_ref") is None:
            raise ValueError("history observation requires an evidence reference")

        def check_keys(value):
            if isinstance(value, dict):
                if any(not isinstance(key, str) for key in value):
                    raise ValueError("JSON object keys must be strings")
                for item in value.values():
                    check_keys(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    check_keys(item)

        try:
            check_keys(payload)
            encoded = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError(
                "payload must be finite JSON with string object keys"
            ) from exc
        object.__setattr__(self, "evidence_ref", evidence_ref)
        object.__setattr__(self, "_payload_json", encoded)

    @property
    def payload(self):
        return json.loads(self._payload_json)


def history_at(observations, decision_at) -> tuple:
    """Preserve arrival order; later labels never backfill an earlier prefix."""
    cutoff = _nonnegative(decision_at, "decision_at")
    observations = tuple(observations)
    if any(not isinstance(item, FrozenObservation) for item in observations):
        raise ValueError("history must contain only FrozenObservation objects")
    return tuple(item for item in observations if item.observed_at <= cutoff)


def history_hash(observations, decision_at) -> str:
    prefix = history_at(observations, decision_at)
    body = {
        "schema": "pred1-history-v1",
        "decision_at": float(decision_at),
        "observations": [[o.observed_at, o.evidence_ref, o.payload] for o in prefix],
    }
    return sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    ).hexdigest()
