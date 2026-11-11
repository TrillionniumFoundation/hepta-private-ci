#!/usr/bin/env python3
"""Read original strong-control evidence without training or executing archive code."""

import argparse
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

import numpy as np

from study_cost import COST_FIELDS, audit_cost, audit_stages, total_cost
from study_data import canonical_bytes, digest, make_data
from study_model import Model, evaluate
from strong_control import ARMS, StrongPlan
from strong_control_audit import audit_trial


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def read_archive(directory):
    metadata = json.loads((directory / "ARCHIVE.json").read_bytes())
    manifest_raw = (directory / "MEMBERS.json").read_bytes()
    require(sha256(manifest_raw) == metadata["members_sha256"], "member manifest digest changed")
    manifest = json.loads(manifest_raw)
    raw = (directory / "original-attempt.tar.gz").read_bytes()
    require(sha256(raw) == metadata["archive_sha256"] and len(raw) == metadata["compressed_bytes"],
            "original archive digest or size changed")
    contents = {}
    observed = []
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for entry in archive:
            path = PurePosixPath(entry.name)
            require(entry.isfile() and not path.is_absolute() and ".." not in path.parts
                    and str(path) == entry.name and entry.name not in contents,
                    "non-regular, unsafe or repeated archive member")
            data = archive.extractfile(entry).read()
            contents[entry.name] = data
            observed.append({"path": entry.name, "size": len(data), "sha256": sha256(data)})
    require(observed == manifest, "archive member population or bytes changed")
    require(len(observed) == metadata["member_count"]
            and sum(item["size"] for item in observed) == metadata["uncompressed_bytes"],
            "archive member totals changed")
    return contents, metadata


def expected_costs(run, plan):
    """Derive every declared ledger quantity from kernels, data and the frozen plan."""
    shared, per_arm = {}, {}

    def add(events, phase, stage, **values):
        fields = {key: 0 for key in COST_FIELDS if key != "wall_time_ns"}
        fields.update(values)
        events[(phase, stage)] = fields

    def observe(events, stage, count, dense=False):
        if dense:
            add(events, "eval", stage, requests=count, estimated_float_ops=38 * count,
                route_decisions=count)
        else:
            add(events, "route", stage, requests=count, route_decisions=count)
            add(events, "eval", stage, requests=count, estimated_float_ops=14 * count)

    def train(events, stage, count, parameter_bytes, data_bytes):
        add(events, "train", stage, requests=count, parameter_bytes=parameter_bytes,
            estimated_float_ops=plan.training_steps * (25 * count + 30),
            hash_input_bytes=data_bytes)

    data = run["data"]
    add(shared, "setup", "dataset_and_freeze", requests=sum(v["requests"] for v in data.values()))
    train(shared, "parent_pretrain", plan.pretrain_per_task, 48, data["pretrain"]["data_bytes"])
    observe(shared, "demand_monitor", data["monitor"]["requests"])
    add(shared, "train", "negative_transfer_one_step_probe", requests=plan.train_per_task,
        estimated_float_ops=25 * plan.train_per_task + 18, parameter_bytes=48,
        hash_input_bytes=data["train"]["data_bytes"])
    observe(shared, "negative_transfer_monitor", data["monitor"]["requests"])
    for name, arm in run["arms"].items():
        events = {}
        dense = name == "unsplit_selective"
        if run["demand"]["propose_child"]:
            train(events, "new_slot_fit", plan.train_per_task, 96 if dense else 48,
                  data["train"]["data_bytes"])
        else:
            add(events, "train", "no_update", parameter_bytes=96)
        for stage, split in (("validation", "validation"), ("test", "test"),
                             ("cold_decode_validation", "validation")):
            observe(events, stage, data[split]["requests"], dense)
        size = len(canonical_bytes(arm["model"]))
        add(events, "storage", "snapshot_and_decode", parameter_bytes=96,
            serialized_bytes=size, hash_input_bytes=size)
        per_arm[name] = events
    return shared, per_arm


def audit_common_information(run, plan):
    """Replay recorded monitoring inference, never the diagnostic training update."""
    demand = run["demand"]
    monitor = make_data(plan, run["seed"], run["scenario"])["monitor"]
    for payload_key, observation_key in (("parent_model", "before"), ("probe_model", "probe")):
        model = Model.restore(demand[payload_key])
        require(model.router == "shared" and model.experts[0].mode == "shared" and model.salt == "",
                "common diagnostic model representation changed")
        observed = evaluate(monitor, model, [], "read_only_monitor_replay")
        require(observed == demand[observation_key], "diagnostic observations changed")
    windows = [float(np.mean([r["squared_error"] for i, r in enumerate(demand["before"]["records"])
                              if r["task"] == 1 and monitor.window[i] == window]))
               for window in range(plan.monitoring_windows)]
    regression = demand["probe"]["old_task"]["mse"] - demand["before"]["old_task"]["mse"]
    persistent = all(value >= plan.policy.persistent_window_mse for value in windows)
    negative = regression >= plan.policy.negative_transfer_mse_increase
    expected = {"window_new_task_mse": windows, "window_requests": plan.monitor_per_task_per_window,
                "old_task_probe_mse_increase": regression, "persistent_demand": persistent,
                "negative_transfer_observed": negative, "propose_child": persistent and negative,
                "training_evidence_splits": ["pretrain", "train", "monitor"]}
    require({key: demand[key] for key in expected} == expected, "common demand condition changed")
    shared, per_arm = expected_costs(run, plan)
    audit_stages(run["shared_ledger"], shared)
    for name, arm in run["arms"].items():
        payload = arm["model"]
        if name == "unsplit_selective":
            require(payload["mode"] == "single_tensor", "unsplit representation changed")
        else:
            model = Model.restore(payload)
            require(model.router == "task" and model.salt == ""
                    and all(expert.mode == "shared" for expert in model.experts),
                    "expert routing or feature information changed")
        audit_stages(arm["ledger"], per_arm[name])
        ledger = run["shared_ledger"] + arm["ledger"]
        audit_cost(ledger, required=frozenset(("train", "eval", "route", "storage")))
        require(arm["cost"] == total_cost(ledger), "cost summary differs from executed ledger")


def audit_payload(contents, metadata, source_root):
    """Validate the sealed historical denominator and reproduce its HOLD decision."""
    load = lambda name: json.loads(contents[name])
    inventory = load("INVENTORY.json")
    require({item["path"] for item in inventory} == set(contents) - {"INVENTORY.json"},
            "original inventory population changed")
    for item in inventory:
        data = contents[item["path"]]
        require(len(data) == item["size"] and sha256(data) == item["sha256"],
                "original inventory member changed: " + item["path"])
    for name, expected_hash in metadata["readback_source_files"].items():
        require(sha256((source_root / name).read_bytes()) == expected_hash,
                "readback implementation changed: " + name)
    protocol = load("actual-01/PROTOCOL.json")
    require(contents["PROTOCOL.json"] == contents["actual-01/PROTOCOL.json"], "protocol copies differ")
    require(digest(protocol) == metadata["original_protocol_digest"], "original frozen protocol changed")
    plan = StrongPlan()
    require(canonical_bytes(protocol["plan"]) == canonical_bytes(asdict(plan)), "frozen plan differs")
    require(protocol["minimum_mse_gain"] == plan.policy.minimum_mse_gain
            and protocol["maximum_old_task_mse_increase"] == plan.policy.maximum_old_task_mse_increase,
            "frozen gain or retention threshold changed")
    for name, expected_hash in protocol["source_files"].items():
        require(sha256(contents["actual-01/EXECUTED_SOURCE/" + name]) == expected_hash,
                "executed source differs from frozen protocol: " + name)
    expected_ids = [[scenario, seed] for scenario in plan.scenarios for seed in plan.seeds]
    names = [f"{scenario}-{seed}.json" for scenario, seed in expected_ids]
    actual_names = {name.removeprefix("actual-01/") for name in contents
                    if name.startswith("actual-01/") and name.count("/") == 1 and name.endswith(".json")}
    require(actual_names == set(names) | {"ATTEMPT.json", "PROTOCOL.json", "SUMMARY.json"},
            "original trial file denominator changed")
    attempt = load("actual-01/ATTEMPT.json")
    require(attempt["planned_trials"] == len(names) and attempt["protocol_digest"] == digest(protocol)
            and attempt["no_automatic_resume_or_replay"] is True, "attempt identity changed")
    trials, checks = [], []
    for name, trial_id in zip(names, expected_ids, strict=True):
        raw = contents["actual-01/" + name]
        trial = json.loads(raw)
        require([trial["scenario"], trial["seed"]] == trial_id, "trial identity changed")
        check = {"file": name, "sha256": sha256(raw), "original_status": trial["status"]}
        if trial["status"] == "completed":
            check.update(audit_trial(trial, plan, digest(protocol["source_files"])))
            audit_common_information(trial, plan)
        else:
            require(trial["status"] == "failed" and trial["cost"] is None and trial["traceback"]
                    and trial["planned_test_requests"] == len(ARMS) * 2 * plan.test_per_task,
                    "failed trial lost its unknown cost or planned requests")
            require(trial["decision"] == {"decision": "HOLD", "reasons": ["trial_failed_or_incomplete"],
                                          "gains": {}}, "failed trial was promoted")
            check.update(readback="unavailable_original_numerical_payload", reason=trial["error"])
        trials.append(trial)
        checks.append(check)
    completed = [trial for trial in trials if trial["status"] == "completed"]
    readback = {"kind": "read_only_reaudit_of_retained_original_results", "new_training_updates": 0,
                "new_trial_executions": 0, "verified_original_trials": len(completed),
                "unrecoverable_original_trials": len(trials) - len(completed), "planned_trials": len(trials),
                "decision": "HOLD", "checks": checks}
    require(readback == load("READBACK.json"), "saved readback differs from independent archive audit")
    summary = load("actual-01/SUMMARY.json")
    expected = {"protocol_digest": digest(protocol), "source_files": protocol["source_files"],
                "planned_trials": len(trials), "completed_trials": len(completed),
                "failed_trials": len(trials) - len(completed), "trial_ids": expected_ids,
                "decisions": [trial["decision"] for trial in trials],
                "planned_test_predictions": len(trials) * len(ARMS) * 2 * plan.test_per_task,
                "completed_test_predictions": len(completed) * len(ARMS) * 2 * plan.test_per_task,
                "matched_parameter_trials": sum(len({arm["parameter_digest"] for arm in t["arms"].values()}) == 1
                                                for t in completed),
                "production_authority": False, "rsi_proven": False, "p4_qualified": False, "p5_qualified": False}
    require({key: summary[key] for key in expected} == expected, "summary denominator or decision changed")
    decision = ("HOLD" if len(completed) != len(trials) or any(t["decision"]["decision"] != "RESEARCH_ELIGIBLE"
                                                             for t in trials) else "RESEARCH_ELIGIBLE")
    require(summary["decision"] == decision == "HOLD", "historical HOLD was relabelled as qualification")
    return {"integrity": "PASS", "scientific_decision": decision,
            "planned_trials": len(trials), "verified_original_trials": len(completed),
            "failed_original_trials": len(trials) - len(completed),
            "planned_test_predictions": expected["planned_test_predictions"],
            "verified_test_predictions": expected["completed_test_predictions"],
            "new_training_updates": 0, "new_trial_executions": 0,
            "failure_costs_known": False, "full_campaign_cost_measured": False,
            "final_implementation_model_qualified": False,
            "production_authority": False, "p3_qualified": False, "p4_qualified": False, "p5_qualified": False,
            "cost_scope": "declared algorithmic kernels and recorded wall time; physical energy/GPU/network/billing unmeasured",
            "evidence_archive_sha256": metadata["archive_sha256"],
            "original_protocol_digest": digest(protocol), "readback": readback}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--expect-decision", choices=("HOLD",), required=True)
    args = parser.parse_args()
    try:
        contents, metadata = read_archive(args.evidence)
        result = audit_payload(contents, metadata, Path(__file__).resolve().parent)
    except (ValueError, KeyError, TypeError, OSError, tarfile.TarError) as exc:
        print(json.dumps({"integrity": "FAIL", "scientific_decision": "HOLD", "production_authority": False,
                          "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
