#!/usr/bin/env python3
"""Immutable decision/outcome receipts and small off-policy estimators.

This module is deliberately standard-library-only.  It is intended as the
audit boundary around an NDU/Merton router: a decision receipt records the
complete action set and behavior propensity at the moment of routing, while
an outcome receipt can arrive later or correct an earlier outcome.  Missing
outcomes are excluded from an estimate and reported; they are never silently
converted to a reward of zero.

The estimators use the usual finite-sample definitions:

* IPS: ``mean((target(a|x)/behavior(a|x)) * reward)``;
* SNIPS: self-normalized IPS;
* DR: ``mean(sum_a target(a|x) q(a|x) + ratio*(reward-q(a|x)))``;
* ESS: ``sum(ratio)^2 / sum(ratio^2)``.

For a target policy to be evaluable, every action with positive target mass
must have positive behavior support.  A support violation yields an invalid
estimate (or raises ``SupportFailure`` in strict convenience functions).
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple, Union


EPSILON = 1e-8
Distribution = Mapping[str, float]
TargetPolicy = Union[Distribution, Mapping[str, Distribution], Callable[["DecisionReceipt"], Distribution]]
Baseline = Union[Distribution, Mapping[str, Distribution], Callable[["DecisionReceipt", str], float]]


class ReceiptError(ValueError):
    """Base class for invalid or incomplete receipt data."""


class SupportFailure(ReceiptError):
    """The target policy assigns mass outside behavior-policy support."""


class MissingOutcomeError(ReceiptError):
    """No observed outcome is available at the requested watermark."""


def _finite(value: object, label: str) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ReceiptError(f"{label} must be a finite number") from error
    if not math.isfinite(number):
        raise ReceiptError(f"{label} must be a finite number")
    return number


def _as_pairs(value: Union[Mapping[str, float], Iterable[Tuple[str, float]]]) -> Tuple[Tuple[str, float], ...]:
    if isinstance(value, Mapping):
        items = tuple(value.items())
    else:
        items = tuple(value)
    return tuple((str(name), _finite(probability, f"propensity[{name}]")) for name, probability in items)


@dataclass(frozen=True)
class DecisionReceipt:
    """An immutable, replayable record of one behavior-policy decision.

    ``propensity`` stores one entry for every candidate.  Zero probability is
    allowed for an unsupported candidate, but the selected action must have
    positive behavior probability.  ``support`` is explicit in the receipt so
    an evaluator never has to reconstruct support from a lossy log.
    """

    decision_id: str
    candidates: Tuple[str, ...]
    propensity: Union[Mapping[str, float], Tuple[Tuple[str, float], ...]]
    seed: int
    budget: float
    support: Tuple[str, ...] = field(default_factory=tuple)
    selected_action: str = ""

    def __post_init__(self) -> None:
        candidates = tuple(str(candidate) for candidate in self.candidates)
        object.__setattr__(self, "candidates", candidates)
        pairs = _as_pairs(self.propensity)
        object.__setattr__(self, "propensity", pairs)
        support = tuple(str(action) for action in self.support)
        if not support:
            support = tuple(name for name, probability in pairs if probability > 0.0)
        object.__setattr__(self, "support", support)
        object.__setattr__(self, "budget", _finite(self.budget, "budget"))
        self.validate()

    @classmethod
    def from_mapping(
        cls,
        decision_id: str,
        candidates: Sequence[str],
        propensity: Mapping[str, float],
        seed: int,
        budget: float,
        selected_action: str,
        support: Optional[Sequence[str]] = None,
    ) -> "DecisionReceipt":
        return cls(
            decision_id=decision_id,
            candidates=tuple(candidates),
            propensity=tuple(propensity.items()),
            seed=seed,
            budget=budget,
            support=tuple(support or ()),
            selected_action=selected_action,
        )

    @property
    def propensity_map(self) -> Mapping[str, float]:
        return MappingProxyType(dict(self.propensity))

    def validate(self) -> "DecisionReceipt":
        if not self.decision_id:
            raise ReceiptError("decision_id must be non-empty")
        if not self.candidates or len(set(self.candidates)) != len(self.candidates):
            raise ReceiptError("candidates must be non-empty and unique")
        if not self.selected_action:
            raise ReceiptError("selected_action must be non-empty")
        if self.selected_action not in self.candidates:
            raise ReceiptError("selected_action must belong to candidates")
        if self.budget < 0.0:
            raise ReceiptError("budget must be non-negative")
        if not isinstance(self.seed, int):
            raise ReceiptError("seed must be an integer")
        propensity = dict(self.propensity)
        if set(propensity) != set(self.candidates) or len(propensity) != len(self.candidates):
            raise ReceiptError("propensity must contain exactly the complete candidate set")
        if any(probability < 0.0 for probability in propensity.values()):
            raise ReceiptError("propensity probabilities must be non-negative")
        if abs(sum(propensity.values()) - 1.0) > EPSILON:
            raise ReceiptError("propensity probabilities must sum to one")
        if propensity[self.selected_action] <= 0.0:
            raise ReceiptError("selected action must have positive propensity")
        if not set(self.support).issubset(self.candidates):
            raise ReceiptError("support must be a subset of candidates")
        expected_support = {name for name, probability in propensity.items() if probability > 0.0}
        if set(self.support) != expected_support:
            raise ReceiptError("support must equal the positive-propensity actions")
        if self.selected_action not in self.support:
            raise ReceiptError("selected action must be in support")
        return self


@dataclass(frozen=True)
class OutcomeReceipt:
    """An immutable delayed outcome or correction for a decision receipt.

    ``outcome=None`` is a pending receipt.  It remains visible in the ledger
    for audit purposes, but is excluded from all estimators until a later
    observed receipt supplies a value.  ``watermark`` is the logical time at
    which the receipt becomes usable.  A correction points to a previous
    ``outcome_id`` and replaces it for later watermarks.
    """

    outcome_id: str
    decision_id: str
    outcome: Optional[float]
    watermark: int
    correction_of: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.outcome_id:
            raise ReceiptError("outcome_id must be non-empty")
        if not self.decision_id:
            raise ReceiptError("decision_id must be non-empty")
        if not isinstance(self.watermark, int) or self.watermark < 0:
            raise ReceiptError("watermark must be a non-negative integer")
        if self.correction_of == self.outcome_id:
            raise ReceiptError("an outcome cannot correct itself")
        if self.outcome is not None:
            object.__setattr__(self, "outcome", _finite(self.outcome, "outcome"))

    @property
    def observed(self) -> bool:
        return self.outcome is not None


@dataclass(frozen=True)
class OPEEstimate:
    method: str
    value: Optional[float]
    n: int
    ess: float
    valid: bool
    watermark: Optional[int]
    missing_outcomes: int = 0
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "method": self.method,
            "value": self.value,
            "n": self.n,
            "ess": self.ess,
            "valid": self.valid,
            "watermark": self.watermark,
            "missing_outcomes": self.missing_outcomes,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class _Sample:
    decision: DecisionReceipt
    outcome: float
    behavior_probability: float
    target_probability: float
    importance_ratio: float


class ReceiptLedger:
    """Mutable index of immutable receipts with watermark-aware evaluation."""

    def __init__(self) -> None:
        self._decisions: Dict[str, DecisionReceipt] = {}
        self._outcomes: Dict[str, OutcomeReceipt] = {}
        self._watermark: Optional[int] = None

    @property
    def watermark(self) -> Optional[int]:
        return self._watermark

    @property
    def decisions(self) -> Mapping[str, DecisionReceipt]:
        return MappingProxyType(self._decisions)

    @property
    def outcomes(self) -> Mapping[str, OutcomeReceipt]:
        return MappingProxyType(self._outcomes)

    def add_decision(self, receipt: DecisionReceipt) -> None:
        receipt.validate()
        if receipt.decision_id in self._decisions:
            raise ReceiptError(f"duplicate decision_id: {receipt.decision_id}")
        self._decisions[receipt.decision_id] = receipt

    def add_outcome(self, receipt: OutcomeReceipt) -> None:
        if receipt.outcome_id in self._outcomes:
            raise ReceiptError(f"duplicate outcome_id: {receipt.outcome_id}")
        decision = self._decisions.get(receipt.decision_id)
        if decision is None:
            raise ReceiptError(f"unknown decision_id: {receipt.decision_id}")
        if receipt.correction_of is not None:
            parent = self._outcomes.get(receipt.correction_of)
            if parent is None:
                raise ReceiptError(f"unknown correction target: {receipt.correction_of}")
            if parent.decision_id != receipt.decision_id:
                raise ReceiptError("correction target belongs to another decision")
            if receipt.watermark < parent.watermark:
                raise ReceiptError("correction watermark cannot precede target watermark")
        self._outcomes[receipt.outcome_id] = receipt

    def advance_watermark(self, watermark: int) -> None:
        if not isinstance(watermark, int) or watermark < 0:
            raise ReceiptError("watermark must be a non-negative integer")
        if self._watermark is not None and watermark < self._watermark:
            raise ReceiptError("watermark must be monotone")
        self._watermark = watermark

    def _effective_outcomes(self, as_of: Optional[int]) -> Dict[str, OutcomeReceipt]:
        cutoff = self._watermark if as_of is None else as_of
        if cutoff is None:
            cutoff = math.inf
        visible = [
            receipt
            for receipt in self._outcomes.values()
            if receipt.observed and receipt.watermark <= cutoff
        ]
        effective: Dict[str, OutcomeReceipt] = {}
        # A correction is itself an observed receipt and therefore wins over
        # its target once its watermark is visible.  Stable sorting makes ties
        # deterministic even when receipts were inserted in another order.
        for receipt in sorted(visible, key=lambda item: (item.watermark, item.outcome_id)):
            previous = effective.get(receipt.decision_id)
            if previous is None or receipt.correction_of == previous.outcome_id:
                effective[receipt.decision_id] = receipt
            elif receipt.correction_of is None and receipt.watermark >= previous.watermark:
                effective[receipt.decision_id] = receipt
            elif receipt.correction_of is not None:
                # A correction chain can target a receipt that is not the
                # currently selected root only if that root is itself a prior
                # correction.  Follow the chain to determine whether it is an
                # ancestor of the current receipt.
                ancestor = receipt.correction_of
                while ancestor is not None and ancestor in self._outcomes:
                    if ancestor == previous.outcome_id:
                        effective[receipt.decision_id] = receipt
                        break
                    ancestor = self._outcomes[ancestor].correction_of
        return effective

    def _samples(self, target_policy: TargetPolicy, as_of: Optional[int]) -> Tuple[Tuple[_Sample, ...], int, Optional[int]]:
        effective = self._effective_outcomes(as_of)
        samples = []
        missing = 0
        for decision_id, decision in self._decisions.items():
            outcome = effective.get(decision_id)
            if outcome is None:
                missing += 1
                continue
            target = _resolve_policy(target_policy, decision)
            _validate_distribution(target, decision.candidates, "target policy")
            behavior = dict(decision.propensity)
            selected = decision.selected_action
            behavior_probability = behavior[selected]
            target_probability = float(target.get(selected, 0.0))
            if behavior_probability <= 0.0 and target_probability > 0.0:
                raise SupportFailure(
                    f"selected action {selected!r} has zero behavior propensity"
                )
            for action, target_probability_for_action in target.items():
                if target_probability_for_action > 0.0 and behavior.get(action, 0.0) <= 0.0:
                    raise SupportFailure(
                        f"target action {action!r} is outside behavior support for {decision_id!r}"
                    )
            ratio = target_probability / behavior_probability if behavior_probability > 0.0 else 0.0
            samples.append(_Sample(decision, float(outcome.outcome), behavior_probability, target_probability, ratio))
        watermark = self._watermark if as_of is None else as_of
        return tuple(samples), missing, watermark

    def evaluate(
        self,
        method: str,
        target_policy: TargetPolicy,
        baseline: Optional[Baseline] = None,
        as_of: Optional[int] = None,
        strict: bool = False,
    ) -> OPEEstimate:
        method = method.lower()
        try:
            samples, missing, watermark = self._samples(target_policy, as_of)
            if not samples:
                raise MissingOutcomeError("no observed outcome is available at this watermark")
            ratios = [sample.importance_ratio for sample in samples]
            ess = effective_sample_size(ratios)
            if method == "ips":
                value = sum(sample.importance_ratio * sample.outcome for sample in samples) / len(samples)
            elif method == "snips":
                denominator = sum(ratios)
                if denominator <= 0.0:
                    raise SupportFailure("SNIPS denominator is zero")
                value = sum(sample.importance_ratio * sample.outcome for sample in samples) / denominator
            elif method in {"dr", "doubly_robust"}:
                if baseline is None:
                    raise ReceiptError("baseline is required for doubly robust estimation")
                values = []
                for sample in samples:
                    target = _resolve_policy(target_policy, sample.decision)
                    q_selected = _resolve_baseline(baseline, sample.decision, sample.decision.selected_action)
                    target_q = sum(
                        probability * _resolve_baseline(baseline, sample.decision, action)
                        for action, probability in target.items()
                    )
                    values.append(target_q + sample.importance_ratio * (sample.outcome - q_selected))
                value = sum(values) / len(values)
            else:
                raise ReceiptError(f"unknown OPE method: {method}")
            return OPEEstimate(method, value, len(samples), ess, True, watermark, missing, None)
        except (SupportFailure, MissingOutcomeError, ReceiptError) as error:
            if strict:
                raise
            return OPEEstimate(method, None, 0, 0.0, False, as_of, 0, str(error))

    def ips(self, target_policy: TargetPolicy, as_of: Optional[int] = None) -> float:
        estimate = self.evaluate("ips", target_policy, as_of=as_of, strict=True)
        assert estimate.value is not None
        return estimate.value

    def snips(self, target_policy: TargetPolicy, as_of: Optional[int] = None) -> float:
        estimate = self.evaluate("snips", target_policy, as_of=as_of, strict=True)
        assert estimate.value is not None
        return estimate.value

    def doubly_robust(
        self,
        target_policy: TargetPolicy,
        baseline: Baseline,
        as_of: Optional[int] = None,
    ) -> float:
        estimate = self.evaluate("dr", target_policy, baseline=baseline, as_of=as_of, strict=True)
        assert estimate.value is not None
        return estimate.value

    def effective_sample_size(self, target_policy: TargetPolicy, as_of: Optional[int] = None) -> float:
        samples, _, _ = self._samples(target_policy, as_of)
        return effective_sample_size([sample.importance_ratio for sample in samples])

    def ess(self, target_policy: TargetPolicy, as_of: Optional[int] = None) -> float:
        """Short alias for :meth:`effective_sample_size`."""

        return self.effective_sample_size(target_policy, as_of=as_of)


def _validate_distribution(distribution: Distribution, candidates: Sequence[str], label: str) -> None:
    if set(distribution) - set(candidates):
        raise ReceiptError(f"{label} contains an unknown action")
    values = {candidate: _finite(distribution.get(candidate, 0.0), f"{label}[{candidate}]") for candidate in candidates}
    if any(value < 0.0 for value in values.values()):
        raise ReceiptError(f"{label} probabilities must be non-negative")
    if abs(sum(values.values()) - 1.0) > EPSILON:
        raise ReceiptError(f"{label} probabilities must sum to one")


def _resolve_policy(policy: TargetPolicy, decision: DecisionReceipt) -> Distribution:
    if callable(policy):
        result = policy(decision)
    elif decision.decision_id in policy and isinstance(policy[decision.decision_id], Mapping):  # type: ignore[index]
        result = policy[decision.decision_id]  # type: ignore[index]
    else:
        result = policy  # type: ignore[assignment]
    return {str(action): float(probability) for action, probability in result.items()}


def _resolve_baseline(baseline: Baseline, decision: DecisionReceipt, action: str) -> float:
    if callable(baseline):
        return _finite(baseline(decision, action), "baseline")
    if decision.decision_id in baseline and isinstance(baseline[decision.decision_id], Mapping):  # type: ignore[index]
        value = baseline[decision.decision_id].get(action, 0.0)  # type: ignore[index]
    else:
        value = baseline.get(action, 0.0)  # type: ignore[union-attr]
    return _finite(value, f"baseline[{action}]")


def effective_sample_size(weights: Sequence[float]) -> float:
    """Return Kish ESS, or zero when no positive importance mass exists."""

    clean = [_finite(weight, "importance weight") for weight in weights]
    denominator = sum(weight * weight for weight in clean)
    numerator = sum(clean) ** 2
    return numerator / denominator if denominator > 0.0 else 0.0


def ess(weights: Sequence[float]) -> float:
    """Short alias for :func:`effective_sample_size`."""

    return effective_sample_size(weights)


def ips(ledger: ReceiptLedger, target_policy: TargetPolicy, as_of: Optional[int] = None) -> float:
    return ledger.ips(target_policy, as_of=as_of)


def snips(ledger: ReceiptLedger, target_policy: TargetPolicy, as_of: Optional[int] = None) -> float:
    return ledger.snips(target_policy, as_of=as_of)


def doubly_robust(
    ledger: ReceiptLedger,
    target_policy: TargetPolicy,
    baseline: Baseline,
    as_of: Optional[int] = None,
) -> float:
    return ledger.doubly_robust(target_policy, baseline, as_of=as_of)


def _demo() -> Dict[str, object]:
    ledger = ReceiptLedger()
    ledger.add_decision(DecisionReceipt.from_mapping(
        "d1", ("a", "b"), {"a": 0.5, "b": 0.5}, 17, 4.0, "a"
    ))
    ledger.add_decision(DecisionReceipt.from_mapping(
        "d2", ("a", "b"), {"a": 0.25, "b": 0.75}, 18, 3.0, "b"
    ))
    ledger.add_outcome(OutcomeReceipt("o1", "d1", 2.0, 1))
    ledger.add_outcome(OutcomeReceipt("o2", "d2", 1.0, 1))
    target = {"a": 0.75, "b": 0.25}
    return {
        "ips": ips(ledger, target),
        "snips": snips(ledger, target),
        "dr": doubly_robust(ledger, target, {"a": 1.0, "b": 1.0}),
        "ess": ledger.effective_sample_size(target),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    if args.demo:
        print(json.dumps(_demo(), indent=2, sort_keys=True))
    else:
        print(json.dumps({"module": "ndu_ledger_ope", "status": "ready"}, sort_keys=True))


if __name__ == "__main__":
    main()
