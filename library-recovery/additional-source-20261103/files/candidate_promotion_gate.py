#!/usr/bin/env python3
"""Fail-closed candidate promotion gate for NDU/Cell shadow evidence.

This module is the qualification boundary after the portfolio, tree, Cell,
ledger/OPE and typed-memory reference components.  It deliberately separates
three concepts:

* ``gates_passed``: all empirical/contract checks passed;
* ``eligible_for_external_acceptance``: the evidence may be submitted for an
  external/manual review; and
* ``promotion_allowed``: a runtime authority may activate the artifact.

The current protocol is ``SHADOW_ONLY``/``DENY_ALL``.  Therefore even a fully
passing synthetic evidence record can only become eligible for external
acceptance.  It can never activate a candidate from this reference module.
Missing, non-finite, malformed or contradictory evidence always fails closed.
No provider, model, filesystem or network call is performed by the gate.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from ndu_system2_orchestrator import run as orchestrator_run


MODE = "SHADOW_ONLY"
AUTHORITY = "DENY_ALL"
Q32_TOLERANCE = 2.0 ** -32
ZERO_DIGEST = "0" * 64


class PromotionGateError(ValueError):
    """Raised only for invalid API arguments; evidence itself fails closed."""


@dataclass(frozen=True)
class GateResult:
    """One deterministic gate result suitable for an audit receipt."""

    name: str
    passed: bool
    observed: Any
    threshold: Any
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "observed": self.observed,
            "threshold": self.threshold,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PromotionDecision:
    """The complete fail-closed promotion decision."""

    status: str
    mode: str
    authority: str
    gates_passed: bool
    eligible_for_external_acceptance: bool
    promotion_allowed: bool
    gates: Tuple[GateResult, ...]
    evidence_digest: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "mode": self.mode,
            "authority": self.authority,
            "gates_passed": self.gates_passed,
            "eligible_for_external_acceptance": self.eligible_for_external_acceptance,
            "promotion_allowed": self.promotion_allowed,
            "gates": [gate.to_dict() for gate in self.gates],
            "evidence_digest": self.evidence_digest,
            "reason": self.reason,
            "protocol": {
                "mode": MODE,
                "authority": AUTHORITY,
                "provider_dispatch": False,
                "real_model_call": False,
                "artifact_selection": False,
                "learned_fbsde": False,
                "production_activation": False,
            },
        }


def _finite(value: Any) -> Optional[float]:
    # Accept JSON numeric values only.  Coercing strings would allow malformed
    # receipts to pass a qualification gate accidentally.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or not number.is_integer():
        return None
    return int(number)


def _bool(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def _text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _digest(mapping: Mapping[str, Any]) -> str:
    """Stable evidence digest without importing a non-standard package."""

    encoded = json.dumps(mapping, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    import hashlib

    return hashlib.sha256(encoded).hexdigest()


def _gate(name: str, passed: bool, observed: Any, threshold: Any, reason: Optional[str] = None) -> GateResult:
    return GateResult(name=name, passed=bool(passed), observed=observed, threshold=threshold, reason=reason)


def _require_bool(evidence: Mapping[str, Any], key: str, *, label: Optional[str] = None) -> GateResult:
    observed = _bool(evidence.get(key))
    return _gate(
        label or key,
        observed is True,
        observed,
        True,
        None if observed is True else f"missing or false {key}",
    )


def _require_count(evidence: Mapping[str, Any], key: str, minimum: int, *, label: Optional[str] = None) -> GateResult:
    observed = _int(evidence.get(key))
    passed = observed is not None and observed >= minimum
    return _gate(
        label or key,
        passed,
        observed,
        {"min": minimum},
        None if passed else f"{key} must be an integer >= {minimum}",
    )


def _require_ratio_at_most(evidence: Mapping[str, Any], key: str, maximum: float, *, label: Optional[str] = None) -> GateResult:
    observed = _finite(evidence.get(key))
    passed = observed is not None and 0.0 <= observed <= maximum
    return _gate(
        label or key,
        passed,
        observed,
        {"max": maximum},
        None if passed else f"{key} must be finite and <= {maximum}",
    )


def _require_numeric(evidence: Mapping[str, Any], key: str, *, label: Optional[str] = None) -> GateResult:
    observed = _finite(evidence.get(key))
    passed = observed is not None
    return _gate(
        label or key,
        passed,
        observed,
        "finite",
        None if passed else f"missing or non-finite {key}",
    )


def _evidence_from_orchestrator(event: Mapping[str, Any], memory: Mapping[str, Any]) -> Dict[str, Any]:
    """Map current shadow receipts into the gate schema.

    The orchestrator intentionally does not claim future/OOD/calibration
    evidence.  Those fields are represented as missing/zero, which makes the
    resulting decision reject rather than silently treating a training proxy
    as qualification evidence.
    """

    portfolio = event.get("portfolio", {})
    tree = event.get("tree", {})
    cell = event.get("cell", {})
    lineage = cell.get("lineage", {}) if isinstance(cell, Mapping) else {}
    ope = event.get("ope", {})
    ips = ope.get("ips", {}) if isinstance(ope, Mapping) else {}
    protocol = event.get("protocol", {})
    memory_protocol = memory.get("protocol", {})
    return {
        "mode": protocol.get("mode"),
        "authority": protocol.get("authority"),
        "chosen_propensity": (portfolio.get("propensity", {}) or {}).get(portfolio.get("selected_action")),
        "propensity_sum": portfolio.get("propensity_sum"),
        "ope_valid": ips.get("valid"),
        "ope_ess": ope.get("ess"),
        "ope_support_complete": portfolio.get("support_complete"),
        "global_gap_detected": tree.get("global_gap_detected"),
        "local_composition_gap": tree.get("local_composition_gap"),
        "future_windows": 0,
        "independent_snapshots": 1,
        "candidate_lcb": None,
        "baseline_ucb": None,
        "old_task_degradation": None,
        "ood_false_acceptance": None,
        "calibration_error": None,
        "deletion_non_resurrection_violations": 0 if memory.get("non_resurrection") is True else None,
        "safety_gate": False,
        "privacy_gate": False,
        "support_gate": portfolio.get("support_complete"),
        "retention_gate": memory_protocol.get("retrieval_fail_closed"),
        "lineage_gate": lineage.get("candidate_predecessor_matches_initial"),
        "rollback_gate": bool(lineage.get("candidate_predecessor_matches_initial")),
        "provider_dispatch": protocol.get("provider_dispatch"),
        "real_model_call": protocol.get("real_model_call"),
        "artifact_selection": protocol.get("artifact_selection"),
        "learned_fbsde": protocol.get("learned_fbsde"),
        "production_caller": False,
        "candidate_snapshot_digest": lineage.get("candidate_snapshot_digest"),
    }


def evaluate(evidence: Mapping[str, Any], *, min_ess: float = 2.0, max_composition_gap: float = 1.0e-3, max_calibration_error: float = 0.05) -> PromotionDecision:
    """Evaluate all qualification gates and return a fail-closed decision.

    ``evidence`` is treated as untrusted input.  A malformed field produces a
    failed gate with a reason; it never raises and never gets coerced into a
    passing default.  Thresholds are explicit in each gate receipt.
    """

    if not isinstance(evidence, Mapping):
        raise PromotionGateError("evidence must be a mapping")
    evidence_copy = dict(evidence)
    gates = []

    mode = evidence_copy.get("mode")
    authority = evidence_copy.get("authority")
    gates.append(_gate("protocol_mode", mode == MODE, mode, MODE, None if mode == MODE else "mode must remain SHADOW_ONLY"))
    gates.append(_gate("protocol_authority", authority == AUTHORITY, authority, AUTHORITY, None if authority == AUTHORITY else "authority must remain DENY_ALL"))

    gates.append(_require_numeric(evidence_copy, "chosen_propensity", label="chosen_propensity_positive"))
    propensity = _finite(evidence_copy.get("chosen_propensity"))
    gates[-1] = _gate("chosen_propensity_positive", propensity is not None and propensity > 0.0, propensity, {"min_exclusive": 0.0}, None if propensity is not None and propensity > 0.0 else "chosen propensity must be positive")

    propensity_sum = _finite(evidence_copy.get("propensity_sum"))
    sum_error = None if propensity_sum is None else abs(propensity_sum - 1.0)
    gates.append(_gate("propensity_sum_q32", sum_error is not None and sum_error <= Q32_TOLERANCE, sum_error, {"max_abs_error": Q32_TOLERANCE}, None if sum_error is not None and sum_error <= Q32_TOLERANCE else "propensity sum missing or outside Q32 tolerance"))

    gates.append(_gate("ope_valid", _bool(evidence_copy.get("ope_valid")) is True, evidence_copy.get("ope_valid"), True, None if evidence_copy.get("ope_valid") is True else "OPE estimate invalid or missing"))
    ess = _finite(evidence_copy.get("ope_ess"))
    gates.append(_gate("ope_ess", ess is not None and ess >= min_ess, ess, {"min": min_ess}, None if ess is not None and ess >= min_ess else f"effective sample size must be >= {min_ess}"))
    gates.append(_require_bool(evidence_copy, "ope_support_complete", label="ope_support"))

    snapshot_digest = evidence_copy.get("candidate_snapshot_digest")
    digest_ok = isinstance(snapshot_digest, str) and len(snapshot_digest) == 64 and all(char in "0123456789abcdef" for char in snapshot_digest)
    gates.append(_gate("candidate_snapshot_digest", digest_ok, snapshot_digest, {"length": 64, "hex": True}, None if digest_ok else "candidate snapshot digest must be a 64-character lowercase hex digest"))

    global_gap = _bool(evidence_copy.get("global_gap_detected"))
    local_gap = _finite(evidence_copy.get("local_composition_gap"))
    gates.append(_gate("global_local_gap", global_gap is False and local_gap is not None and local_gap <= max_composition_gap, {"global_gap_detected": global_gap, "local_composition_gap": local_gap}, {"global_gap_detected": False, "max_local_composition_gap": max_composition_gap}, None if global_gap is False and local_gap is not None and local_gap <= max_composition_gap else "global/local value gap is unresolved"))

    gates.append(_require_count(evidence_copy, "future_windows", 2))
    gates.append(_require_count(evidence_copy, "independent_snapshots", 3))
    candidate_lcb = _finite(evidence_copy.get("candidate_lcb"))
    baseline_ucb = _finite(evidence_copy.get("baseline_ucb"))
    gates.append(_gate("candidate_lcb_above_baseline_ucb", candidate_lcb is not None and baseline_ucb is not None and candidate_lcb > baseline_ucb, {"candidate_lcb": candidate_lcb, "baseline_ucb": baseline_ucb}, {"strict": "candidate_lcb > baseline_ucb"}, None if candidate_lcb is not None and baseline_ucb is not None and candidate_lcb > baseline_ucb else "candidate lower confidence bound does not beat baseline upper confidence bound"))

    gates.append(_require_ratio_at_most(evidence_copy, "old_task_degradation", 0.02))
    gates.append(_require_ratio_at_most(evidence_copy, "ood_false_acceptance", 0.005))
    gates.append(_require_ratio_at_most(evidence_copy, "calibration_error", max_calibration_error))

    deletion_violations = _int(evidence_copy.get("deletion_non_resurrection_violations"))
    gates.append(_gate("deletion_non_resurrection", deletion_violations == 0, deletion_violations, {"max": 0}, None if deletion_violations == 0 else "deletion/non-resurrection violations must equal zero"))
    for key in ("safety_gate", "privacy_gate", "support_gate", "retention_gate", "lineage_gate", "rollback_gate"):
        gates.append(_require_bool(evidence_copy, key))

    for key in ("provider_dispatch", "real_model_call", "artifact_selection", "learned_fbsde", "production_caller"):
        observed = _bool(evidence_copy.get(key))
        gates.append(_gate(f"no_{key}", observed is False, observed, False, None if observed is False else f"{key} must be explicitly false"))

    digest_input = {key: evidence_copy[key] for key in sorted(evidence_copy)}
    evidence_digest = _digest(digest_input)
    all_passed = all(gate.passed for gate in gates)
    eligible = all_passed
    # This reference gate never activates a runtime artifact.  The protocol
    # boundary is explicit even if a complete evidence record passes.
    promotion_allowed = False
    if all_passed:
        status = "ELIGIBLE_FOR_EXTERNAL_ACCEPTANCE"
        reason = "all qualification gates passed; external/manual acceptance is still required"
    else:
        status = "REJECTED_FAIL_CLOSED"
        failed = [gate.name for gate in gates if not gate.passed]
        reason = "failed gates: " + ", ".join(failed)
    return PromotionDecision(
        status=status,
        mode=MODE,
        authority=AUTHORITY,
        gates_passed=all_passed,
        eligible_for_external_acceptance=eligible,
        promotion_allowed=promotion_allowed,
        gates=tuple(gates),
        evidence_digest=evidence_digest,
        reason=reason,
    )


def passing_evidence() -> Dict[str, Any]:
    """Return a complete, synthetic evidence record for contract tests only."""

    return {
        "mode": MODE,
        "authority": AUTHORITY,
        "chosen_propensity": 0.25,
        "propensity_sum": 1.0,
        "ope_valid": True,
        "ope_ess": 4.0,
        "ope_support_complete": True,
        "global_gap_detected": False,
        "local_composition_gap": 0.0001,
        "future_windows": 2,
        "independent_snapshots": 3,
        "candidate_lcb": 0.80,
        "baseline_ucb": 0.70,
        "old_task_degradation": 0.01,
        "ood_false_acceptance": 0.004,
        "calibration_error": 0.03,
        "deletion_non_resurrection_violations": 0,
        "safety_gate": True,
        "privacy_gate": True,
        "support_gate": True,
        "retention_gate": True,
        "lineage_gate": True,
        "rollback_gate": True,
        "provider_dispatch": False,
        "real_model_call": False,
        "artifact_selection": False,
        "learned_fbsde": False,
        "production_caller": False,
        "candidate_snapshot_digest": "a" * 64,
    }


def run(seed: int = 17) -> Dict[str, Any]:
    """Evaluate the current orchestrator fixture and show why it remains shadow."""

    event = orchestrator_run(seed)
    memory = _load_memory_fixture(seed)
    evidence = _evidence_from_orchestrator(event, memory)
    decision = evaluate(evidence)
    return {
        "seed": int(seed),
        "status": decision.status,
        "evidence": evidence,
        "decision": decision.to_dict(),
        "protocol": {
            "mode": MODE,
            "authority": AUTHORITY,
            "provider_dispatch": False,
            "real_model_call": False,
            "artifact_selection": False,
            "learned_fbsde": False,
            "production_activation": False,
        },
        "note": "Current orchestrator is a shadow fixture; missing future/OOD/calibration evidence is intentionally rejected.",
    }


def evaluate_file(path: str | Path) -> Dict[str, Any]:
    """Evaluate an externally supplied JSON evidence envelope.

    The file is treated as untrusted evidence.  A non-object JSON value or a
    malformed record is converted into a rejected fail-closed report rather
    than being treated as an activation signal.
    """

    target = Path(path)
    try:
        evidence = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return {
            "status": "REJECTED_FAIL_CLOSED",
            "evidence": None,
            "decision": {
                "status": "REJECTED_FAIL_CLOSED",
                "mode": MODE,
                "authority": AUTHORITY,
                "gates_passed": False,
                "eligible_for_external_acceptance": False,
                "promotion_allowed": False,
                "gates": [],
                "evidence_digest": None,
                "reason": f"evidence file unreadable: {type(error).__name__}",
            },
            "protocol": {
                "mode": MODE,
                "authority": AUTHORITY,
                "provider_dispatch": False,
                "real_model_call": False,
                "artifact_selection": False,
                "learned_fbsde": False,
                "production_activation": False,
            },
        }
    if not isinstance(evidence, Mapping):
        return {
            "status": "REJECTED_FAIL_CLOSED",
            "evidence": evidence,
            "decision": {
                "status": "REJECTED_FAIL_CLOSED",
                "mode": MODE,
                "authority": AUTHORITY,
                "gates_passed": False,
                "eligible_for_external_acceptance": False,
                "promotion_allowed": False,
                "gates": [],
                "evidence_digest": None,
                "reason": "evidence root must be a JSON object",
            },
            "protocol": {
                "mode": MODE,
                "authority": AUTHORITY,
                "provider_dispatch": False,
                "real_model_call": False,
                "artifact_selection": False,
                "learned_fbsde": False,
                "production_activation": False,
            },
        }
    decision = evaluate(evidence)
    return {
        "status": decision.status,
        "evidence": dict(evidence),
        "decision": decision.to_dict(),
        "protocol": {
            "mode": MODE,
            "authority": AUTHORITY,
            "provider_dispatch": False,
            "real_model_call": False,
            "artifact_selection": False,
            "learned_fbsde": False,
            "production_activation": False,
        },
    }


def _load_memory_fixture(seed: int) -> Mapping[str, Any]:
    """Read the deterministic local memory output without changing authority."""

    try:
        from typed_memory_cell_contract import run as memory_run

        return memory_run(seed)
    except Exception as error:  # pragma: no cover - defensive fail-closed path
        return {"protocol": {}, "non_resurrection": False, "error": type(error).__name__}


def main() -> None:
    parser = argparse.ArgumentParser(description="NDU candidate promotion gate (fail-closed shadow reference)")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--evidence", type=Path, help="evaluate an external JSON evidence envelope")
    parser.add_argument("--output", type=Path, help="write the report JSON to this path")
    args = parser.parse_args()
    report = evaluate_file(args.evidence) if args.evidence else run(args.seed)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
