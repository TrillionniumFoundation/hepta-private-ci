"""Validate actual per-batch Encoder/Head work before consuming any labels.

Source-bound, research-only physical-work census. This is *not* independent
hardware attestation, an energy meter, total FLOPs, or model promotion.
"""
from __future__ import annotations

from experiments.shared_stem_cell.wire import InputError

SCHEMA = "hepta.sequential-physical-work.v1"
ARMS = {"bank", "shared", "residual_corrected", "linear_distilled"}


def _integer(value, low, high, field):
    if type(value) is not int or not low <= value <= high:
        raise InputError("invalid sequential work " + field)
    return value


def _sha(value):
    if (not isinstance(value, str) or len(value) != 64 or
            any(c not in "0123456789abcdef" for c in value)):
        raise InputError("invalid sequential work digest")
    return value


def _calls(arm, rows):
    ordered = []
    for cell in (0, 1):
        indices = [i for i, row in enumerate(rows) if row["cell"] == cell]
        if indices:
            ordered.append((cell, indices))
    if arm == "shared":
        return [{"component": "shared", "rows": list(range(len(rows)))}]
    if arm == "residual_corrected":
        return ([{"component": "shared", "rows": list(range(len(rows)))}]
                + [{"component": "residual-" + str(cell), "rows": indices}
                   for cell, indices in ordered])
    return [{"component": arm + "-" + str(cell), "rows": indices}
            for cell, indices in ordered]


def validate_batch(part, raw, lock):
    """Reconcile one completed invocation with the exact loaded model profile.

    The producer runs the physical callbacks; this validates its retained work
    record and rejects incomplete or invented-zero costs. Hashes don't attest
    that a malicious backend truly ran, so producer/host trust stays separate.
    """
    if (type(part) is not list or not 1 <= len(part) <= 512 or
            any(type(r) is not dict or type(r.get("cell")) is not int
                or r["cell"] not in (0, 1) for r in part) or
            type(raw) is not dict or type(lock) is not dict or
            lock.get("physical_work_profile") != SCHEMA or
            type(lock.get("source_simulated_encoder")) is not bool or
            type(lock.get("profile")) is not dict):
        raise InputError("unqualified sequential physical-work contract")
    n = len(part)
    width = _integer(lock["profile"].get("width"), 1, 8192, "Stem width")
    expected_stem = _sha(lock.get("expected_stem_sha256"))
    if raw.get("selected") != lock.get("selected"):
        raise InputError("Head selection differs from frozen candidate")
    feature = _sha(raw.get("feature_sha256"))
    enc = raw.get("encoding")
    costs = raw.get("inference_costs")
    if not isinstance(enc, dict) or type(costs) is not dict or set(costs) != ARMS:
        raise InputError("incomplete Encoder/Head physical-work records")
    if (enc.get("simulated_encoder") is not lock["source_simulated_encoder"] or
            enc.get("model_digest") != expected_stem or
            enc.get("cache_object_overhead_measured") is not False):
        raise InputError("Encoder identity or resource completeness drift")
    forwards = _integer(enc.get("encoder_forward_calls"), 1, n, "Encoder forwards")
    reuses = _integer(enc.get("cache_reuses"), 0, n, "Encoder cache reuses")
    if (_integer(enc.get("requests"), n, n, "Encoder request count") != n or
            _integer(enc.get("retained_result_tensor_bytes"),
                     n * width * 4, n * width * 4, "materialized feature bytes") != n * width * 4 or
            _integer(enc.get("cache_retained_tensor_bytes"), 0, 512 * 1024**2,
                     "cache bytes") < 0 or
            forwards + reuses > n):
        raise InputError("Encoder request/physical-work accounting mismatch")
    timed = {}
    for arm in sorted(ARMS):
        item = costs[arm]
        expected = _calls(arm, part)
        if (not isinstance(item, dict) or item.get("calls") != expected or
                item.get("encoder_calls") != 0 or
                item.get("active_flops") is not None or
                item.get("energy_joules") is not None):
            raise InputError("wrong routed Head census or fabricated resource meter: " + arm)
        invocations = _integer(item.get("head_forward_calls"),
                               len(expected), len(expected), arm + " invocations")
        requested = sum(len(v["rows"]) for v in expected)
        _integer(item.get("head_rows_processed"), requested, requested, arm + " row work")
        _integer(item.get("wall_ns"), 0, 10**18, arm + " wall time")
        _integer(item.get("process_cpu_ns"), 0, 10**18, arm + " CPU time")
        timed[arm] = {"head_forward_calls": invocations, "head_rows_processed": requested,
                      "reported_wall_ns": item["wall_ns"],
                      "reported_process_cpu_ns": item["process_cpu_ns"]}
    return {"schema": SCHEMA, "rows": n, "scope": lock.get("scope"),
            "feature_sha256": feature, "model_digest": expected_stem,
            "encoder_forward_calls": forwards, "encoder_cache_reuses": reuses,
            "head_work": timed, "total_head_row_executions": sum(
                v["head_rows_processed"] for v in timed.values()),
            "all_model_calls_independently_attested": False,
            "source_meter_fully_covers_flops": False,
            "process_peak_memory_measured": False, "energy_measured": False,
            "independent_evaluation": False, "production_accepted": False}


def aggregate(receipts):
    """Sum actual *reported* work once; no synthetic cost for unused Cells."""
    if type(receipts) is not list or not receipts or any(
            type(r) is not dict or r.get("schema") != SCHEMA for r in receipts):
        raise InputError("complete physically reconciled sequence required")
    expected_model = receipts[0]["model_digest"]
    expected_scope = receipts[0]["scope"]
    if any(r["model_digest"] != expected_model or r["scope"] != expected_scope
           or set(r["head_work"]) != ARMS for r in receipts):
        raise InputError("mixed sequential model/Scope physical costs")
    return {"schema": "hepta.sequential-physical-work-total.v1",
            "batches": len(receipts),
            "scope": expected_scope, "model_digest": expected_model,
            "work_semantics": "whole_logical_stream_including_replayed_prefix",
            "counter_scope": "all_four_comparator_arms_not_single_deployed_policy",
            "encoder_input_rows": sum(r["rows"] for r in receipts),
            "encoder_forward_calls": sum(r["encoder_forward_calls"] for r in receipts),
            "per_arm_head_forward_calls": {arm: sum(r["head_work"][arm]["head_forward_calls"]
                for r in receipts) for arm in sorted(ARMS)},
            "per_arm_head_rows_processed": {arm: sum(r["head_work"][arm]["head_rows_processed"]
                for r in receipts) for arm in sorted(ARMS)},
            "energy_joules": None, "active_flops": None,
            "independent_resource_attestation": False,
            "production_accepted": False}
