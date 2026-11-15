"""Offline comparability audit for V2 matrix runs, never an evidence issuer.

Inputs must come from admitted execution/observer owners. Digests bind bytes;
this module does NOT authenticate a profiler, device, pretrained model or outcome.
No pair accepted here is thereby qualified, statistically superior or promoted.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from next_round_matrix import WORK_POOLS, _digest, validate_plan

PHASES = ("train", "search", "evaluation", "inference", "migration")
COMPONENTS = ("encoder", "head", "router", "critic", "verifier", "failed_work")


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"invalid {name}")
    return value


def _sha(value, name, length=64):
    if not isinstance(value, str) or len(value) != length or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"invalid {name}")


def freeze_contract(plan, *, source_sha, workload_sha256, task_ids, device_id,
                    observer_id, train_cutoff_ns, eval_start_ns, eval_end_ns,
                    flops_caps, tolerance_ppm=10_000, max_peak_trainable_params=None):
    """Freeze caps and pairing BEFORE execution; no model-dependent defaults."""
    validate_plan(plan)
    _sha(source_sha, "source SHA", 40)
    _sha(workload_sha256, "workload digest")
    if (not isinstance(task_ids, list) or not 1 <= len(task_ids) <= 4096
            or any(not isinstance(t, str) or not t for t in task_ids)
            or len(set(task_ids)) != len(task_ids)):
        raise ValueError("bounded unique task inventory required")
    if any(not isinstance(x, str) or not x for x in (device_id, observer_id)):
        raise ValueError("named device and independent observer required")
    for value in (train_cutoff_ns, eval_start_ns, eval_end_ns):
        _integer(value, "time", 1)
    if not train_cutoff_ns < eval_start_ns < eval_end_ns:
        raise ValueError("future evaluation must follow frozen training cutoff")
    _integer(tolerance_ppm, "tolerance")
    if tolerance_ppm > 50_000:
        raise ValueError("compute-match tolerance exceeds five percent")
    if not isinstance(flops_caps, dict) or set(flops_caps) != set(PHASES):
        raise ValueError("separate caps for every physical-work phase required")
    for phase, value in flops_caps.items():
        _integer(value, phase, 1 if phase == "inference" else 0)
    body = dict(schema="hepta.stem.execution-contract.v1", plan_id=plan["plan_id"],
                source_sha=source_sha, workload_sha256=workload_sha256,
                task_ids=list(task_ids), device_id=device_id, observer_id=observer_id,
                train_cutoff_ns=train_cutoff_ns, eval_start_ns=eval_start_ns,
                eval_end_ns=eval_end_ns, flops_caps=dict(flops_caps),
                tolerance_ppm=tolerance_ppm)
    if max_peak_trainable_params is not None:
        _integer(max_peak_trainable_params, "common live trainable parameter cap", 1)
        body.update(schema="hepta.stem.execution-contract.v2",
                    max_peak_trainable_params=max_peak_trainable_params)
    return {**body, "contract_id": _digest(body)}


def validate_contract(plan, contract):
    if not isinstance(contract, dict):
        raise ValueError("execution contract required")
    try:
        names = ("source_sha", "workload_sha256", "task_ids", "device_id", "observer_id",
                 "train_cutoff_ns", "eval_start_ns", "eval_end_ns", "flops_caps", "tolerance_ppm")
        if contract.get("schema") == "hepta.stem.execution-contract.v2":
            names += ("max_peak_trainable_params",)
        expected = freeze_contract(plan, **{k: contract[k] for k in names})
        if _digest(contract) != _digest(expected):
            raise ValueError("execution contract changed")
    except (KeyError, TypeError) as exc:
        raise ValueError("incomplete execution contract") from exc


def _percentile(samples, fraction):
    # Nearest-rank, all completed AND failed/censored request latencies retained.
    return sorted(samples)[max(0, math.ceil(fraction * len(samples)) - 1)]


def audit_pair(plan, contract, contrast_id, baseline, candidate):
    """Check full denominators, measured work and chronological comparability.

    Receipts are a normalized export, not a replacement for native run receipts.
    A structurally comparable result still requires independent source validation,
    preregistered statistical analysis and the existing selection owner.
    """
    validate_plan(plan)
    validate_contract(plan, contract)
    contrasts = {c["contrast_id"]: c for c in plan["contrasts"]}
    if contrast_id not in contrasts:
        raise ValueError("unknown preregistered contrast")
    contrast = contrasts[contrast_id]
    profiles = {a["arm_id"]: a for a in plan["arms"]}
    blockers, summaries = [], []
    receipt_fields = {"schema", "contract_id", "arm_id", "source_sha", "device_id",
                      "workload_sha256", "head_params", "trainable_params",
                      "peak_trainable_params", "unique_weight_bytes", "phase_flops",
                      "flop_profile", "flop_components", "execution_kind",
                      "weight_receipt_sha256", "observer_receipt_sha256", "requests"}
    request_fields = {"task_id", "status", "latency_ns", "energy_joules",
                      "peak_memory_bytes", "outcome", "observed_at_ns", "observer_id"}
    for role, receipt in (("baseline", baseline), ("candidate", candidate)):
        allowed_fields = receipt_fields | ({"training_protocol_sha256"} if isinstance(receipt, dict) and receipt.get("schema") in ("hepta.stem.paired-run-export.v2", "hepta.stem.paired-run-export.v3") else set())
        if isinstance(receipt, dict) and receipt.get("schema") == "hepta.stem.paired-run-export.v3":
            allowed_fields |= {"output_profile", "precursor_trainable_params"}
        if not isinstance(receipt, dict) or set(receipt) != allowed_fields:
            raise ValueError("incomplete or unknown run receipt fields")
        if receipt["schema"] not in ("hepta.stem.paired-run-export.v1", "hepta.stem.paired-run-export.v2", "hepta.stem.paired-run-export.v3"):
            raise ValueError("unsupported run export schema")
        if receipt["schema"] in ("hepta.stem.paired-run-export.v2", "hepta.stem.paired-run-export.v3"):
            _sha(receipt["training_protocol_sha256"], "training protocol digest")
        if receipt["arm_id"] != contrast[role]:
            raise ValueError("wrong arm or reversed comparison")
        for key in ("contract_id", "source_sha", "device_id", "workload_sha256"):
            if receipt[key] != contract[key]:
                raise ValueError(f"run does not match frozen {key}")
        for key in ("head_params", "trainable_params", "peak_trainable_params", "unique_weight_bytes"):
            _integer(receipt[key], key, 1)
        if not receipt["head_params"] <= receipt["trainable_params"] <= receipt["peak_trainable_params"]:
            raise ValueError("inconsistent measured parameter inventory")
        if receipt["schema"] == "hepta.stem.paired-run-export.v3":
            _integer(receipt["precursor_trainable_params"], "precursor parameters", 1)
            if (receipt["output_profile"] != "consolidated_parent16_mlp.v1"
                    or receipt["precursor_trainable_params"] != 2 * receipt["trainable_params"]
                    or receipt["peak_trainable_params"] < receipt["precursor_trainable_params"] + receipt["trainable_params"]):
                raise ValueError("invalid consolidated output stage")
        if receipt["head_params"] > profiles[receipt["arm_id"]]["total_head_budget_params"]:
            blockers.append(f"{role}:head_budget_exceeded")
        for key in ("weight_receipt_sha256", "observer_receipt_sha256"):
            if receipt[key] is None:
                blockers.append(f"{role}:missing_{key}")
            else:
                _sha(receipt[key], key)
        if receipt["execution_kind"] != "pretrained_local_weights":
            blockers.append(f"{role}:not_pretrained_model_execution")
        if not isinstance(receipt["flop_profile"], str) or not receipt["flop_profile"]:
            raise ValueError("named profiler/operation-count convention required")
        if receipt["flop_components"] != list(COMPONENTS):
            blockers.append(f"{role}:incomplete_flop_coverage")
        if not isinstance(receipt["phase_flops"], dict) or set(receipt["phase_flops"]) != set(PHASES):
            raise ValueError("all work phases must be explicitly reported")
        for phase, value in receipt["phase_flops"].items():
            if value is None:
                blockers.append(f"{role}:missing_{phase}_flops")
            else:
                _integer(value, f"{phase} FLOPs", 1 if phase == "inference" else 0)
                if value > contract["flops_caps"][phase]:
                    blockers.append(f"{role}:{phase}_budget_exceeded")
        rows = receipt["requests"]
        if not isinstance(rows, list) or len(rows) != len(contract["task_ids"]):
            raise ValueError("complete request denominator required, including failures")
        if any(not isinstance(r, dict) or set(r) != request_fields for r in rows):
            raise ValueError("invalid request projection")
        if [r["task_id"] for r in rows] != contract["task_ids"]:
            raise ValueError("paired workload changed, reordered or duplicated")
        latencies, energy, memory, outcomes = [], [], [], []
        for row in rows:
            if row["status"] not in ("completed", "failed", "timed_out", "unknown"):
                raise ValueError("unknown execution outcome")
            latencies.append(_integer(row["latency_ns"], "latency", 1) / 1_000_000)
            if row["observer_id"] != contract["observer_id"]:
                raise ValueError("independent outcome observer changed")
            timestamp = _integer(row["observed_at_ns"], "observation time", 1)
            if not contract["eval_start_ns"] <= timestamp < contract["eval_end_ns"]:
                raise ValueError("outcome not in the frozen future window")
            for key, output in (("energy_joules", energy), ("peak_memory_bytes", memory), ("outcome", outcomes)):
                value = row[key]
                if value is None:
                    blockers.append(f"{role}:missing_{key}")
                elif type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"invalid observed {key}")
                else:
                    if key == "outcome" and value > 1:
                        raise ValueError("normalized outcome outside [0,1]")
                    if key == "peak_memory_bytes":
                        _integer(value, "memory bytes", 1)
                    output.append(value)
        count = len(rows)
        summaries.append({"arm_id": receipt["arm_id"], "requests": count,
                          "noncompleted": sum(r["status"] != "completed" for r in rows),
                          "p50_latency_ms": _percentile(latencies, .50),
                          "p95_latency_ms": _percentile(latencies, .95),
                          "p99_latency_ms": _percentile(latencies, .99),
                          "energy_joules": sum(energy) if len(energy) == count else None,
                          "peak_memory_bytes": max(memory) if len(memory) == count else None,
                          "mean_outcome": sum(outcomes) / count if len(outcomes) == count else None})
    # V2 fixes final capacity but permits unequal transient storage under ONE
    # preregistered ceiling. Requiring identical transients would reward dummy
    # allocation in no-split controls. V1 retains its original stricter semantics.
    if "max_peak_trainable_params" in contract:
        if any(r["schema"] not in ("hepta.stem.paired-run-export.v2", "hepta.stem.paired-run-export.v3") for r in (baseline, candidate)):
            blockers.append("missing_bound_training_protocol")
        elif baseline["training_protocol_sha256"] != candidate["training_protocol_sha256"]:
            blockers.append("unmatched_training_protocol")
        for role, receipt in (("baseline", baseline), ("candidate", candidate)):
            if receipt["peak_trainable_params"] > contract["max_peak_trainable_params"]:
                blockers.append(f"{role}:peak_trainable_budget_exceeded")
    if baseline.get("output_profile") != candidate.get("output_profile"):
        blockers.append("unmatched_output_stage")
    if contrast["match_total_head_budget"]:
        # Gate/critic capacity may be traded against Head capacity under the
        # same total trainable ceiling. Equal actual Head counts as well would
        # prohibit that fair trade and accidentally require dummy parameters.
        matched = ("trainable_params",) if "max_peak_trainable_params" in contract else ("trainable_params", "peak_trainable_params")
        for field in matched:
            if baseline[field] != candidate[field]:
                blockers.append(f"unmatched_actual_{field}")
    if baseline["flop_profile"] != candidate["flop_profile"]:
        blockers.append("incompatible_flop_profiles")
    # Preserve every per-phase counter/cap, but compare useful work pools.
    # Forcing migration or search separately equal would reward padding the
    # no-split/no-NDU controls with dummy work. Offline work cannot offset an
    # online compute excess. The pool partition is bound into the plan ID.
    for pool, phases in WORK_POOLS.items():
        left_values = [baseline["phase_flops"][p] for p in phases]
        right_values = [candidate["phase_flops"][p] for p in phases]
        if all(v is not None for v in left_values + right_values):
            left, right = sum(left_values), sum(right_values)
            if abs(left - right) * 1_000_000 > max(left, right) * contract["tolerance_ppm"]:
                blockers.append(f"unmatched_measured_{pool}_flops")
    return {"schema": "hepta.stem.pair-audit.v1", "contract_id": contract["contract_id"],
            "contrast_id": contrast_id, "receipt_digests": [_digest(baseline), _digest(candidate)],
            "status": "blocked" if blockers else "structurally_comparable_unattested",
            "blockers": sorted(set(blockers)), "summaries": summaries,
            "statistical_superiority_established": False, "production_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "contract", "baseline", "candidate", "contrast", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    inputs = []
    for path in (args.plan, args.contract, args.baseline, args.candidate):
        source = Path(path)
        if source.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("audit input too large")
        inputs.append(json.loads(source.read_text(encoding="utf-8")))
    result = audit_pair(inputs[0], inputs[1], args.contrast, inputs[2], inputs[3])
    with Path(args.output).open("x", encoding="utf-8") as handle:
        json.dump(result, handle, allow_nan=False, indent=2)
        handle.write("\n")
    print(result["status"])
    return 2 if result["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
