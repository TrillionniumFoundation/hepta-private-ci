#!/usr/bin/env python3
"""Matched CPU controls for structural differentiation; no runtime authority."""

import argparse
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import platform
import os
import sys
import time
import traceback

import numpy as np

try:
    import resource
except ImportError:
    resource = None

from study_data import ARMS as LEGACY_ARMS
from study_data import FrozenRun, Plan, SOURCE_FILES, canonical_bytes, digest, make_data
from study_model import LinearModel, Model, charge, diagnose, evaluate, features, fit, summarize
from study_cost import total_cost

ARMS = ("demand_split", "fixed_selective", "unsplit_selective")
SEEDS = (101, 211, 307, 401, 503)
SOURCES = SOURCE_FILES + ("strong_control.py", "strong_control_audit.py")


@dataclass(frozen=True)
class StrongPlan(Plan):
    seeds: tuple = SEEDS
    arms: tuple = ARMS

    def validate(self):
        if self.arms != ARMS:
            raise ValueError("all three matched arms are required")
        Plan.validate(replace(self, arms=LEGACY_ARMS))


def sources():
    root = Path(__file__).resolve().parent
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCES}


def protocol():
    plan = StrongPlan()
    return {
        "schema_version": 1, "plan": asdict(plan), "arms": list(ARMS),
        "source_files": sources(),
        "common_initial_system": "same independent per-seed parent; every arm gets its exact FP64 bytes",
        "capacity": "12 retained FP64 coefficients per arm; demand arm reserves a second six-coefficient slot",
        "update_policy": "parent slot frozen; update new-task six coefficients iff common training/monitor demand fires",
        "diagnosis": "one shared diagnostic execution; its full cost is included once in every comparison arm",
        "unsplit": "one fixed 12-coefficient tensor with two task-gated six-feature blocks; no topology change",
        "training_budget": "same actual common pretrain + one-step probe + selective updates and row presentations",
        "selection": "one candidate per arm; no tuning, retries, restarts, seed dropping or post-test choices",
        "minimum_mse_gain": plan.policy.minimum_mse_gain,
        "maximum_old_task_mse_increase": plan.policy.maximum_old_task_mse_increase,
        "scope": "synthetic CPU FP64 control experiment, not ordinary Cell service or general neural architecture",
        "production_authority": False, "rsi_proven": False,
        "p4_qualified": False, "p5_qualified": False,
        "energy_joules": None, "physical_cost": "energy, network and actual billing not measured",
    }


def verify_protocol(value):
    if canonical_bytes(value) != canonical_bytes(protocol()):
        raise ValueError("frozen protocol/source changed")
    return StrongPlan()


def write_new(path, value):
    with path.open("xb") as stream:
        stream.write(canonical_bytes(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def prepare(path):
    value = protocol()
    write_new(path, value)
    return digest(value)


def fit_unsplit(parent, train, frozen, plan, ledger, enabled):
    """Independently train the selected block in one fixed 12-coordinate model."""
    start = time.perf_counter_ns()
    frozen.verify(plan)
    frozen.authorize_training(train)
    weights = np.concatenate((parent.weights, parent.weights))
    if enabled:
        rows = train.task == 1
        phi = features(train, "shared", rows)
        y = train.y[rows]
        for _ in range(plan.training_steps):
            residual = phi @ weights[6:] - y
            gradient = phi.T @ residual / len(y) + plan.ridge * weights[6:]
            weights[6:] -= plan.learning_rate * gradient
        n, d = phi.shape
        charge(ledger, "train", "new_slot_fit", start, requests=n,
               float_ops=plan.training_steps * (4 * n * d + n + 5 * d),
               parameter_bytes=weights.nbytes, hash_bytes=train.manifest()["data_bytes"])
    else:
        charge(ledger, "train", "no_update", start, parameter_bytes=weights.nbytes)
    if weights[:6].tobytes() != parent.weights.tobytes():
        raise ValueError("unsplit training changed the frozen old-task block")
    return weights


def observe_unsplit(batch, weights, ledger, stage):
    start = time.perf_counter_ns()
    base = features(batch, "shared")
    gate = batch.task[:, None]
    phi = np.column_stack((base * (1 - gate), base * gate))
    values = phi @ weights
    losses = (values - batch.y) ** 2
    records = []
    for ident, task, target, predicted, loss in zip(batch.ids, batch.task, batch.y, values, losses, strict=True):
        valid = bool(np.isfinite(predicted) and np.isfinite(loss))
        records.append({"id": ident, "task": int(task), "target": float(target),
                        "prediction": float(predicted) if valid else None,
                        "squared_error": float(loss) if valid else None,
                        "status": "completed" if valid else "failed",
                        "reason": None if valid else "nonfinite prediction or loss"})
    n = len(batch.ids)
    charge(ledger, "eval", stage, start, requests=n, float_ops=2 * n * 12 + 12 * n + 2 * n,
           route_decisions=n, complete=all(r["status"] == "completed" for r in records),
           note="dense task-gated linear model: both six-feature blocks materialized; costs retained")
    return {"split": batch.split, "summary": summarize(records),
            "old_task": summarize([r for r in records if r["task"] == 0]),
            "new_task": summarize([r for r in records if r["task"] == 1]), "records": records}


def budget(plan, enabled):
    steps = plan.training_steps
    return {"gradient_updates": steps + 1 + (steps if enabled else 0),
            "training_presentations": plan.pretrain_per_task * steps + plan.train_per_task
            + (plan.train_per_task * steps if enabled else 0),
            "retained_coefficients": 12, "retained_parameter_bytes": 96,
            "updated_coordinates_per_step": 6, "old_slot_updates_after_parent": 0,
            "candidate_searches": 1, "retries": 0}


def run_trial(plan, seed, scenario, source_digest):
    began = time.perf_counter_ns()
    shared = []
    data = make_data(plan, seed, scenario)
    frozen = FrozenRun.freeze(plan, data, source_digest)
    charge(shared, "setup", "dataset_and_freeze", began,
           requests=sum(len(batch.ids) for batch in data.values()))
    parent = fit(data["pretrain"], np.ones(len(data["pretrain"].ids), dtype=bool),
                 LinearModel("shared", np.zeros(6)), frozen, plan, shared, "parent_pretrain")
    parent_bytes = parent.weights.tobytes()
    demand = diagnose(parent, data, frozen, plan, shared)
    enabled = demand["propose_child"]
    arms = {}
    for name in ARMS:
        ledger = []
        start = time.perf_counter_ns()
        if name == "unsplit_selective":
            weights = fit_unsplit(parent, data["train"], frozen, plan, ledger, enabled)
            model = None
            payload = {"mode": "single_tensor", "weights": weights.tolist()}
        else:
            # Two independent fits; candidate output is never reused by a comparator.
            child = fit(data["train"], data["train"].task == 1, parent, frozen, plan, ledger,
                        "new_slot_fit") if enabled else LinearModel("shared", parent.weights.copy())
            if not enabled:
                charge(ledger, "train", "no_update", start, parameter_bytes=96)
            model = Model("task", (parent, child))
            weights = np.concatenate([expert.weights for expert in model.experts])
            payload = model.payload()
        observe = (lambda batch, stage: observe_unsplit(batch, weights, ledger, stage)) if model is None else (
            lambda batch, stage: evaluate(batch, model, ledger, stage))
        observations = {split: observe(data[split], split) for split in ("validation", "test")}
        start = time.perf_counter_ns()
        wire = canonical_bytes(payload)
        restored = json.loads(wire)
        if model is None:
            restored_weights = np.array(restored["weights"], dtype=np.float64)
        else:
            restored_model = Model.restore(restored)
            restored_weights = np.concatenate([expert.weights for expert in restored_model.experts])
        charge(ledger, "storage", "snapshot_and_decode", start, parameter_bytes=weights.nbytes,
               serialized_bytes=len(wire), hash_bytes=len(wire),
               note="in-process serialization only; not product cold start or owner migration")
        if model is None:
            replay = observe_unsplit(data["validation"], restored_weights, ledger, "cold_decode_validation")
        else:
            replay = evaluate(data["validation"], restored_model, ledger, "cold_decode_validation")
        arms[name] = {"model": payload, "parameter_digest": hashlib.sha256(weights.tobytes()).hexdigest(),
                      "initial_parent_digest": hashlib.sha256(parent_bytes).hexdigest(),
                      "parameter_bytes": weights.nbytes, "budget": budget(plan, enabled),
                      "observations": observations, "ledger": ledger, "cost": total_cost(shared + ledger),
                      "roundtrip_exact": restored_weights.tobytes() == weights.tobytes()
                      and replay["records"] == observations["validation"]["records"]}
    if parent.weights.tobytes() != parent_bytes:
        raise ValueError("common parent modified")
    result = {"seed": seed, "scenario": scenario, "status": "completed", "data": json.loads(frozen.manifest_json),
              "preregistration_digest": frozen.commitment, "demand": demand, "shared_ledger": shared,
              "arms": arms, "elapsed_wall_time_ns": time.perf_counter_ns() - began}
    result["decision"] = adjudicate(result, plan)
    return result


def verify_training_cost(run, arm, plan):
    enabled = run["demand"]["propose_child"]
    events = [e for e in run["shared_ledger"] + arm["ledger"] if e["phase"] == "train"]
    expected = [
        ("parent_pretrain", plan.pretrain_per_task,
         plan.training_steps * (4 * plan.pretrain_per_task * 6 + plan.pretrain_per_task + 5 * 6)),
        ("negative_transfer_one_step_probe", plan.train_per_task,
         4 * plan.train_per_task * 6 + plan.train_per_task + 3 * 6),
        ("new_slot_fit", plan.train_per_task,
         plan.training_steps * (4 * plan.train_per_task * 6 + plan.train_per_task + 5 * 6))
        if enabled else ("no_update", 0, 0),
    ]
    actual = [(e["stage"], e["requests"], e["estimated_float_ops"]) for e in events]
    return actual == expected and all(e["complete"] for e in events)


def adjudicate(run, plan):
    if run.get("status") != "completed":
        return {"decision": "HOLD", "reasons": ["trial_failed_or_incomplete"], "gains": {}}
    arms = run["arms"]
    reasons = []
    if set(arms) != set(ARMS):
        return {"decision": "HOLD", "reasons": ["arm_denominator_changed"], "gains": {}}
    if len({a["initial_parent_digest"] for a in arms.values()}) != 1:
        reasons.append("initial_parent_mismatch")
    expected_budget = budget(plan, run["demand"]["propose_child"])
    for name in ARMS:
        arm = arms[name]
        if (arm["budget"] != expected_budget or arm["parameter_bytes"] != 96
                or not verify_training_cost(run, arm, plan)):
            reasons.append("unmatched_budget:" + name)
        if not arm["cost"]["complete"] or not arm["roundtrip_exact"]:
            reasons.append("incomplete_evidence:" + name)
        for split, per_task in (("test", plan.test_per_task), ("validation", plan.validation_per_task)):
            summary = arm["observations"][split]["summary"]
            if summary["requested"] != 2 * per_task or summary["completed"] != 2 * per_task:
                reasons.append("incomplete_denominator:" + name + ":" + split)
    if not run["demand"]["propose_child"]:
        reasons.append("no_demand_for_structure_change")
    gains = {}
    candidate = arms["demand_split"]["observations"]["test"]
    for name in ARMS[1:]:
        comparator = arms[name]["observations"]["test"]
        if candidate["summary"]["mse"] is None or comparator["summary"]["mse"] is None:
            reasons.append("unmeasured_gain:" + name)
            gains[name] = None
            continue
        gain = comparator["summary"]["mse"] - candidate["summary"]["mse"]
        gains[name] = gain
        if gain < plan.policy.minimum_mse_gain:
            reasons.append("insufficient_gain_over:" + name)
        if candidate["old_task"]["mse"] - comparator["old_task"]["mse"] > plan.policy.maximum_old_task_mse_increase:
            reasons.append("old_task_regression_against:" + name)
    return {"decision": "RESEARCH_ELIGIBLE" if not reasons else "HOLD", "reasons": reasons, "gains": gains}


def run(prepared_path, output):
    frozen_bytes = prepared_path.read_bytes()
    prepared = json.loads(frozen_bytes)
    plan = verify_protocol(prepared)
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "ATTEMPT.json", {"protocol_digest": digest(prepared),
              "started_unix_ns": time.time_ns(), "planned_trials": len(SEEDS) * len(plan.scenarios),
              "no_automatic_resume_or_replay": True})
    write_new(output / "PROTOCOL.json", prepared)
    trials = []
    for scenario in plan.scenarios:
        for seed in SEEDS:
            try:
                result = run_trial(plan, seed, scenario, digest(prepared["source_files"]))
            except Exception as exc:
                result = {"seed": seed, "scenario": scenario, "status": "failed",
                          "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(),
                          "cost": None, "planned_test_requests": len(ARMS) * plan.test_per_task * 2}
                result["decision"] = adjudicate(result, plan)
            # Preserve completed numerical records before the independent checker runs.
            write_new(output / f"RAW-{scenario}-{seed}.json", result)
            if result["status"] == "completed":
                try:
                    from strong_control_audit import audit_trial
                    result["audit"] = audit_trial(result, plan, digest(prepared["source_files"]))
                except Exception as exc:
                    result["status"] = "audit_failed"
                    result["audit_error"] = f"{type(exc).__name__}: {exc}"
                    result["audit_traceback"] = traceback.format_exc()
                    result["decision"] = adjudicate(result, plan)
            write_new(output / f"{scenario}-{seed}.json", result)
            trials.append(result)
    if prepared_path.read_bytes() != frozen_bytes or sources() != prepared["source_files"]:
        raise ValueError("source/protocol changed during execution; keep all original trials")
    succeeded = [r for r in trials if r["status"] == "completed"]
    report = {"protocol_digest": digest(prepared), "source_files": prepared["source_files"],
              "environment": {"python": sys.version, "numpy": np.__version__, "platform": platform.platform(),
                              "peak_rss_raw": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource else None,
                              "peak_rss_unit": "KiB on Linux; bytes on macOS"},
              "planned_trials": len(plan.scenarios) * len(SEEDS), "completed_trials": len(succeeded),
              "failed_trials": len(trials) - len(succeeded), "trial_ids": [[r["scenario"], r["seed"]] for r in trials],
              "decisions": [r["decision"] for r in trials],
              "planned_test_predictions": len(plan.scenarios) * len(SEEDS) * len(ARMS) * 2 * plan.test_per_task,
              "completed_test_predictions": sum(a["observations"]["test"]["summary"]["completed"] for r in succeeded
                                                for a in r["arms"].values()),
              "matched_parameter_trials": sum(len({a["parameter_digest"] for a in r["arms"].values()}) == 1
                                               for r in succeeded),
              "decision": "HOLD" if len(succeeded) != len(trials) or any(r["decision"]["decision"] != "RESEARCH_ELIGIBLE"
                                                                        for r in trials) else "RESEARCH_ELIGIBLE",
              "production_authority": False, "rsi_proven": False, "p4_qualified": False, "p5_qualified": False,
              "cost_note": "Shared physical pretrain/diagnosis ran once per trial and is included once per arm comparison; do not sum comparison costs as physical total. Wall time is measured, floating ops estimated. No energy/billing/VRAM measurements."}
    write_new(output / "SUMMARY.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "run"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        print(json.dumps({"protocol_digest": prepare(args.protocol)}))
    else:
        if args.output is None:
            parser.error("run requires --output")
        report = run(args.protocol, args.output)
        print(json.dumps({k: report[k] for k in ("planned_trials", "completed_trials", "failed_trials",
                                               "completed_test_predictions", "matched_parameter_trials", "decision")}))


if __name__ == "__main__":
    main()
