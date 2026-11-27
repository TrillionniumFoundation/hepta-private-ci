#!/usr/bin/env python3
"""Run the frozen CPU study; the JSON result grants no production authority."""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
import time

import numpy as np

from study_cost import expected_events, retain_unfinished_stages, total_cost
from study_data import ARMS, FrozenRun, Plan, SOURCE_FILES, canonical_bytes, digest, make_data
from study_gate import adjudicate, audit_study, summarize_study
from study_model import LinearModel, Model, charge, diagnose, evaluate, fit, route, snapshot_and_check, summarize


def source_manifest():
    directory = Path(__file__).resolve().parent
    return {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def unavailable_observation(batch, reason):
    records = [{"id": i, "task": int(t), "target": float(y), "prediction": None,
                "squared_error": None, "status": "incomplete", "reason": reason}
               for i, t, y in zip(batch.ids, batch.task, batch.y, strict=True)]
    return {"split": batch.split, "summary": summarize(records),
            "old_task": summarize([r for r in records if r["task"] == 0]),
            "new_task": summarize([r for r in records if r["task"] == 1]), "records": records}


def train_arm(name, parent, train, frozen, plan, ledger, demand, seed):
    if name == "frozen_incumbent" or name == "demand_specialization" and not demand["propose_child"]:
        charge(ledger, "train", "frozen_reuse" if name == "frozen_incumbent" else "no_child_reuse",
               time.perf_counter_ns(), note="incumbent reused unchanged; common pretraining is charged separately")
        return Model("shared", (parent,))
    if name in ("continued_parent", "expanded_monolith"):
        initial = parent if name == "continued_parent" else LinearModel(
            "expanded", np.concatenate((parent.weights, np.zeros(4))))
        trained = fit(train, np.ones(len(train.ids), dtype=bool), initial, frozen, plan, ledger, f"{name}_fit")
        return Model("shared", (trained,))
    router = "random" if name == "random_grouping" else "task"
    salt = f"precommitted-random/{seed}" if router == "random" else ""
    assignments = route(train, Model(router, (parent, parent), salt), ledger, f"{name}_training_partition")
    if name == "demand_specialization":
        child = fit(train, assignments == 1, parent, frozen, plan, ledger, "demand_child_fit")
        return Model("task", (parent, child))
    experts = tuple(fit(train, assignments == i, parent, frozen, plan, ledger, f"{name}_{i}_fit") for i in (0, 1))
    return Model(router, experts, salt)


def run_trial(plan, seed, scenario, source_digest):
    began = time.perf_counter_ns()
    shared, ledgers = [], {name: [] for name in ARMS}
    failures = {name: None for name in ARMS}
    data = make_data(plan, seed, scenario)
    frozen = FrozenRun.freeze(plan, data, source_digest)
    manifests = json.loads(frozen.manifest_json)
    charge(shared, "setup", "dataset_and_freeze", began,
           requests=sum(m["requests"] for m in manifests.values()),
           note="independent split generation and preregistration; random-number arithmetic is not estimated")
    parent, pretrain_failure = None, None
    try:
        parent = fit(data["pretrain"], np.ones(len(data["pretrain"].ids), dtype=bool),
                     LinearModel("shared", np.zeros(6)), frozen, plan, shared, "incumbent_pretrain")
    except Exception as exc:
        pretrain_failure = f"{type(exc).__name__}: {exc}"
    retain_unfinished_stages(shared, expected_events("shared", None, data, plan, False, seed), pretrain_failure)
    incumbent = None if parent is None else Model("shared", (parent,)).payload()
    parent_before = None if incumbent is None else digest(incumbent)
    try:
        if parent is None:
            raise RuntimeError(f"incumbent unavailable: {pretrain_failure}")
        demand = diagnose(parent, data, frozen, plan, ledgers["demand_specialization"])
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        demand = {"failure": reason, "persistent_demand": False, "negative_transfer_observed": False,
                  "propose_child": False, "parent_model": incumbent, "probe_model": None,
                  "before": unavailable_observation(data["monitor"], reason),
                  "probe": unavailable_observation(data["monitor"], reason)}
        failures["demand_specialization"] = reason
    # No validation/test observation is available to any training invocation.
    models = {}
    for name in ARMS:
        try:
            if parent is None:
                raise RuntimeError(f"incumbent unavailable: {pretrain_failure}")
            models[name] = train_arm(name, parent, data["train"], frozen, plan, ledgers[name], demand, seed)
        except Exception as exc:
            failures[name] = f"{type(exc).__name__}: {exc}"
            models[name] = None
    parent_after = None if parent is None else Model("shared", (parent,)).identity()
    observations = {
        name: evaluate(data["validation"], models[name], ledgers[name], "validation") if models[name] is not None
        else unavailable_observation(data["validation"], failures[name]) for name in ARMS
    }
    migrations = {}
    for name in ARMS:
        try:
            if models[name] is None:
                raise RuntimeError(f"model unavailable: {failures[name]}")
            migrations[name] = snapshot_and_check(models[name], data["validation"], observations[name], ledgers[name])
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            failures[name] = failures[name] or reason
            migrations[name] = {
                "failure": reason, "parameter_digest": None if models[name] is None else models[name].identity(),
                "roundtrip_digest": None, "roundtrip_model": None, "exact_validation_behavior": False,
                "requests": len(data["validation"].ids), "scope": "failed in-process parameter roundtrip",
                "after": unavailable_observation(data["validation"], reason),
            }
    tests = {
        name: evaluate(data["test"], models[name], ledgers[name], "test") if models[name] is not None
        else unavailable_observation(data["test"], failures[name]) for name in ARMS
    }
    frozen.verify(plan)
    arms = {}
    for name in ARMS:
        model = models[name]
        payload = None if model is None else model.payload()
        retain_unfinished_stages(ledgers[name],
                                 expected_events(name, payload, data, plan, demand["propose_child"], seed),
                                 failures[name] or "required stage did not produce complete evidence")
        arms[name] = {
            "model": payload, "model_digest": None if model is None else model.identity(),
            "expert_instances": 0 if model is None else len(model.experts), "failure": failures[name],
            "validation": observations[name], "test": tests[name], "migration": migrations[name],
            "ledger": ledgers[name], "cost": total_cost(shared + ledgers[name]),
        }
    result = {
        "seed": seed, "scenario": scenario, "data": manifests, "preregistration_digest": frozen.commitment,
        "execution_order": ["freeze_plan_and_data", "pretrain_incumbent", "diagnose_train_and_monitor",
                            "train_all_arms", "validate_all_arms", "snapshot_and_migrate_all_arms", "test_all_arms"],
        "incumbent_model": incumbent, "incumbent_digest_before_training": parent_before,
        "incumbent_digest_after_training": parent_after, "pretrain_failure": pretrain_failure,
        "demand_evidence": demand, "shared_ledger": shared, "arms": arms,
    }
    result["decision"] = adjudicate(result, plan, source_digest)
    result["total_elapsed_wall_time_ns"] = time.perf_counter_ns() - began
    measured = sum(e["wall_time_ns"] for e in shared if e["wall_time_ns"] is not None)
    measured += sum(e["wall_time_ns"] for l in ledgers.values() for e in l if e["wall_time_ns"] is not None)
    result["orchestration_and_verification_wall_time_ns"] = max(0, result["total_elapsed_wall_time_ns"] - measured)
    return result


def run_study(plan=None, source_commit=None):
    began = time.perf_counter_ns()
    plan = Plan() if plan is None else plan
    plan.validate()
    if source_commit is not None and re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ValueError("--source-commit must be a complete lowercase Git commit SHA")
    sources = source_manifest()
    source_digest = digest(sources)
    runs = [run_trial(plan, seed, scenario, source_digest) for scenario in plan.scenarios for seed in plan.seeds]
    report = {
        "schema_version": 1,
        "scope": "Synthetic two-task CPU FP64 regression study; not seven neural organs or a production lifecycle",
        "production_authority": False, "rsi_proven": False,
        "plan": asdict(plan), "plan_digest": digest(asdict(plan)),
        "source_files": sources, "source_digest": source_digest, "caller_declared_source_commit": source_commit,
        "source_identity_note": "File digests are checked against executed local files. Commit identity requires external verification; no local Git ancestry is inferred.",
        "environment": {"python": sys.version.split()[0], "numpy": np.__version__,
                        "platform": platform.platform(), "device": "CPU", "dtype": "float64"},
        "data_description": {
            "old_weights": [1.4, -0.8, 0.4, 0.6], "helpful_new_weights": [-1.4, 0.8, 0.4, -0.6],
            "redundant_new_weights": [1.4, -0.8, 0.4, 0.6], "intercept": 0.1,
            "input_distribution": "four independent standard normal features; supplied task identity",
            "noise": "independent Gaussian with plan.noise_std; paired scenarios reuse inputs/noise",
            "splits": "pretrain, train, monitor, validation, test use disjoint IDs, rows and RNG streams",
            "selection": "No hyperparameter, threshold, seed or comparator selection after validation/test. Every planned seed must pass.",
            "expanded_baseline": "single linear model with task-feature interactions, initialized from the same parent",
            "fixed_baseline": "two preassigned task experts, each continued from the same parent",
            "random_baseline": "two experts, routed by a seeded SHA-256 of request ID without using targets",
        },
        "cost_units": {
            "estimated_float_ops": "dense float arithmetic estimates, multiply-add=2; not hardware counters or joules",
            "route_decisions": "logical dispatch decisions, never added to floating-point operation estimates",
            "hash_input_bytes": "named digest/routing input byte estimates; hash bookkeeping also appears in wall time",
            "parameter_bytes": "actual float64 parameter bytes retained for a snapshot",
            "wall_time_ns": "nonoverlapping measured stages; orchestration/verification remainder reported separately",
            "unknown_cost": "failed/unexecuted stages retain their original requests and null unknown costs; no zero-cost credit",
            "shared_cost": "data preparation and incumbent pretraining reported once, included in every arm's comparison",
            "migration": "serialization and validation replay only; actual Hepta lifecycle migration remains untested",
            "limitations": "CPU reference training/evaluation/routing/storage/migration are covered. No GPU, physical energy, network, external tool or production throughput measurements.",
        },
        "runs": runs, "summary": summarize_study(runs, plan),
    }
    audit_study(report, plan)
    report["study_elapsed_wall_time_ns"] = time.perf_counter_ns() - began
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", help="externally verified source commit, recorded as caller-declared metadata")
    args = parser.parse_args()
    report = run_study(source_commit=args.source_commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_bytes(report) + b"\n")
    # Check the actual deliverable after serialization, not only the in-memory object.
    audit_study(json.loads(args.output.read_text()), Plan())
    print(json.dumps({"output": str(args.output), "source_digest": report["source_digest"],
                      "plan_digest": report["plan_digest"], "summary": report["summary"]}, indent=2))


if __name__ == "__main__":
    main()
