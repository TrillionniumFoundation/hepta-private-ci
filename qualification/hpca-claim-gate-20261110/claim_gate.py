#!/usr/bin/env python3
"""Fail-closed read-only HPCA-MICRO-V1 claim audit.

This deliberately cannot issue scientific or production GO. The input artifact
is not independently authenticated by this parser; external artifact custody,
physical training, and owner attestation require separate verification.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path

SCHEMA = "HEPTA-HPCA-MICRO-V1"
HOLD = "HOLD_NO_GO"
SOURCE_MANIFEST = "3305e052434eee355d6230785e19e3bd41b7e7ee59691f78a89211e7c79fb63d"
FAMILIES = ("PERC", "PRED", "CTRL", "ACT")
CREDIT_ARMS = ("routed", "context_gradient", "random", "shuffled", "broadcast")
REPLAY_ARMS = ("exact_key", "recent", "uniform", "stratified", "error_priority")
SEEDS = tuple(range(11001, 11017))
CALIBRATION = tuple(range(9001, 9007))
MAX_INPUT_BYTES = 262144
EPSILON = Decimal("0.00000001")


class EvidenceError(ValueError):
    """Invalid, incomplete, drifted or forged research-result declaration."""


def _no_duplicate_fields(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise EvidenceError("duplicate JSON field: " + key)
        obj[key] = value
    return obj


def _no_nonfinite(value):
    raise EvidenceError("NaN and Infinity are not valid JSON evidence")


def _number(value, *, minimum=None, maximum=None, field="metric"):
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise EvidenceError("non-numeric " + field)
    try:
        number = Decimal(value)
        if not number.is_finite():
            raise EvidenceError("non-finite " + field)
        if minimum is not None and number < Decimal(str(minimum)):
            raise EvidenceError("out-of-range " + field)
        if maximum is not None and number > Decimal(str(maximum)):
            raise EvidenceError("out-of-range " + field)
    except (InvalidOperation, OverflowError, ValueError) as exc:
        raise EvidenceError("invalid " + field) from exc
    return number


def _mapping(mapping, *, keys, field, minimum=None, maximum=None):
    if not isinstance(mapping, dict) or set(mapping) != set(keys):
        raise EvidenceError("missing or extra arms in " + field)
    return {k: _number(mapping[k], minimum=minimum, maximum=maximum,
                       field=field + "." + k) for k in keys}


def _as_exact_int(value, expected, field):
    if type(value) is not int or value != expected:
        raise EvidenceError("unexpected " + field)


def _digest(value, field):
    if not isinstance(value, str) or len(value) != 64 or any(
        ch not in "0123456789abcdef" for ch in value
    ):
        raise EvidenceError("invalid " + field)
    return value


def _required_dict(parent, field, keys):
    d = parent.get(field)
    if not isinstance(d, dict) or not set(keys) <= set(d):
        raise EvidenceError("missing structured fields in " + field)
    return d


def inspect_report(raw: bytes, *, expected_manifest=SOURCE_MANIFEST) -> dict:
    if not 1 <= len(raw) <= MAX_INPUT_BYTES:
        raise EvidenceError("report byte limit")
    try:
        result = json.loads(raw.decode("utf-8"), parse_float=Decimal,
                            parse_int=int, parse_constant=_no_nonfinite,
                            object_pairs_hook=_no_duplicate_fields)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise EvidenceError("invalid JSON encoding") from exc
    if not isinstance(result, dict) or result.get("schema") != SCHEMA:
        raise EvidenceError("wrong study schema")
    if (result.get("authority") != "QUALIFICATION_ONLY_NOT_REAL_MODEL_EVIDENCE"
            or result.get("decision") != HOLD):
        raise EvidenceError("source is not immutable research-only HOLD evidence")
    _digest(expected_manifest, "expected manifest")
    if _digest(result.get("source_manifest_sha256"), "source manifest") != expected_manifest:
        raise EvidenceError("unregistered source or input manifest drift")
    if result.get("calibration_seeds") != list(CALIBRATION):
        raise EvidenceError("calibration seed roster differs")
    if result.get("heldout_test_seeds") != list(SEEDS):
        raise EvidenceError("heldout seed roster incomplete or contaminated")
    open_gates = result.get("open_gates")
    if not isinstance(open_gates, list) or len(open_gates) < 1 or any(
        not isinstance(x, str) or not x.strip() for x in open_gates
    ):
        raise EvidenceError("scientific blockers must remain explicit")

    schedule = _required_dict(result, "schedule",
                              ("per_arm_update_budget", "mean_mse", "family_mean_mse"))
    _as_exact_int(schedule["per_arm_update_budget"], 256, "schedule update budget")
    aggregate = _mapping(schedule["mean_mse"], keys=("uniform", "heterogeneous"),
                         field="schedule.mean_mse", minimum=0)
    family_metrics = {}
    if not isinstance(schedule["family_mean_mse"], dict) or (
        set(schedule["family_mean_mse"]) != {"uniform", "heterogeneous"}
    ):
        raise EvidenceError("missing or extra schedule family arms")
    for arm in ("uniform", "heterogeneous"):
        family_metrics[arm] = _mapping(
            schedule["family_mean_mse"].get(arm), keys=FAMILIES,
            field="schedule.family." + arm, minimum=0)
        recomputed = sum(family_metrics[arm].values()) / len(FAMILIES)
        if abs(recomputed - aggregate[arm]) > EPSILON:
            raise EvidenceError("aggregate and per-family MSE do not reconcile")
    regressions = {
        f: str(family_metrics["heterogeneous"][f] - family_metrics["uniform"][f])
        for f in FAMILIES
        if family_metrics["heterogeneous"][f] > family_metrics["uniform"][f] + EPSILON
    }

    credit = _required_dict(result, "credit",
                            ("heldout_accuracy", "mean_parameter_updates"))
    credits = _mapping(credit["heldout_accuracy"], keys=CREDIT_ARMS,
                       field="credit.heldout_accuracy", minimum=0, maximum=1)
    updates = _mapping(credit["mean_parameter_updates"], keys=CREDIT_ARMS,
                       field="credit.parameter_updates", minimum=0)
    equivalent = abs(credits["routed"] - credits["context_gradient"]) <= EPSILON
    if updates["routed"] != updates["context_gradient"]:
        raise EvidenceError("credit strong baseline cost mismatch")
    broadcast_extra = updates["broadcast"] > updates["routed"]

    delay = _required_dict(result, "delay",
                           ("d0_density1_event_id", "d0_density1_latest",
                            "d8_density1_event_id", "d8_density1_latest",
                            "d8_density0.15_event_id", "d8_density0.15_latest"))
    delay_scores = {}
    feedback_by_arm = {}
    for k in (
        "d0_density1_event_id", "d0_density1_latest",
        "d8_density1_event_id", "d8_density1_latest",
        "d8_density0.15_event_id", "d8_density0.15_latest",
    ):
        datum = _required_dict(delay, k, ("mean_accuracy", "mean_observed_feedback"))
        delay_scores[k] = _number(datum["mean_accuracy"], minimum=0, maximum=1,
                                  field=k + ".mean_accuracy")
        feedback_by_arm[k] = _number(
            datum["mean_observed_feedback"], minimum=0,
            field=k + ".mean_observed_feedback")
    for prefix in ("d0_density1", "d8_density1", "d8_density0.15"):
        if (feedback_by_arm[prefix + "_event_id"] !=
                feedback_by_arm[prefix + "_latest"]):
            raise EvidenceError("event/latest feedback denominator mismatch")
    if abs(delay_scores["d0_density1_event_id"] -
           delay_scores["d0_density1_latest"]) > EPSILON:
        raise EvidenceError("immediate-feedback trace parity violated")
    # A latest-trace negative control is deliberately misspecified; an advantage
    # against it cannot establish a novel neuromodulator or downstream utility.

    replay = _required_dict(result, "replay",
                            ("old_task_retention", "new_task_accuracy",
                             "mean_parameter_updates", "mean_selection_reads"))
    old = _mapping(replay["old_task_retention"], keys=REPLAY_ARMS,
                   field="replay.old", minimum=0, maximum=1)
    new = _mapping(replay["new_task_accuracy"], keys=REPLAY_ARMS,
                   field="replay.new", minimum=0, maximum=1)
    replay_updates = _mapping(replay["mean_parameter_updates"], keys=REPLAY_ARMS,
                              field="replay.updates", minimum=0)
    replay_reads = _mapping(replay["mean_selection_reads"], keys=REPLAY_ARMS,
                            field="replay.reads", minimum=0)
    if any(replay_updates[k] != replay_updates["uniform"] for k in
           ("recent", "stratified", "error_priority")):
        raise EvidenceError("neural replay update budgets differ")
    if replay_updates["exact_key"] != 0:
        raise EvidenceError("exact-key reference is not a neural update arm")
    tradeoffs = [k for k in ("stratified", "error_priority") if
                 old[k] > old["uniform"] + EPSILON
                 and new[k] < new["uniform"] - EPSILON]
    exact_beats_neural = all(
        old["exact_key"] >= old[k] and new["exact_key"] >= new[k]
        for k in REPLAY_ARMS if k != "exact_key"
    )

    # No independent evaluator credentials, real task/effect receipts, true
    # costs, model artifacts or future-time confirmation exist in this schema.
    blockers = [
        "synthetic input cannot establish independent real-task utility",
        "no original owner-signed actions, effect receipts or time-legal labels",
        "no full physical/label/optimizer/inference/retrieval cost envelope",
        "no independent confirmatory repetitions, retention/OOD or next-task cold recovery",
    ]
    if regressions:
        blockers.append("heterogeneous clock regresses at least one lineage")
    if equivalent:
        blockers.append("routed credit is equivalent to contextual gradient")
    if broadcast_extra:
        blockers.append("broadcast control spends more parameter writes")
    if tradeoffs:
        blockers.append("replay trades new-task accuracy for old retention")
    if exact_beats_neural:
        blockers.append("exact-key retrieval matches/exceeds all compared accuracies")
    return {
        "schema": "hepta.hpca.micro.claim-gate.v1",
        "source_report_sha256": sha256(raw).hexdigest(),
        "expected_source_manifest_sha256": expected_manifest,
        "historical_execution_head": "f07f41f9a396f7096211b9cc984543b773ce719b",
        "seed_count": len(SEEDS),
        "heterogeneous_minus_uniform_aggregate_mse": str(
            aggregate["heterogeneous"] - aggregate["uniform"]),
        "heterogeneous_regressions": regressions,
        "credit_equal_contextual_gradient": equivalent,
        "broadcast_cost_not_matched": broadcast_extra,
        "zero_delay_parity": True,
        "retention_new_task_tradeoffs": tradeoffs,
        "exact_key_accuracy_not_worse": exact_beats_neural,
        "selection_reads_by_replay_arm": {k: str(v) for k, v in replay_reads.items()},
        "blockers": blockers,
        "scientific_qualification": HOLD,
        "production_qualification": HOLD,
        "original_owner_attestation_verified": False,
        "external_artifact_attestation_verified": False,
        "independent_real_task_confirmations": 0,
        "authority": "DENY_ALL",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True,
                        help="original HPCA-MICRO-V1 report JSON, downloaded separately")
    parser.add_argument("--output", type=Path, required=True,
                        help="new absent output file; never overwrite or alter the original")
    parser.add_argument("--expected-manifest", default=SOURCE_MANIFEST,
                        help="exact registered source-manifest SHA256")
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("output must be a separate path")
    report = inspect_report(args.input.read_bytes(), expected_manifest=args.expected_manifest)
    payload = json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n"
    # No mkdir or overwrite. File existence means a different prior review;
    # do not mutate/replace it during attempted recovery.
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(payload)
    print("HPCA claim review: HOLD_NO_GO; research input only; output", args.output)


if __name__ == "__main__":
    main()
