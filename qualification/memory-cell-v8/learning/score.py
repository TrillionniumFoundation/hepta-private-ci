"""Validate and score the complete native V8 prospective comparison.

CLI: python -I -B score.py prospective-learning.json prospective-score.json
Use the exact source checkout recorded by the input. Raw .artifacts remain
unchanged. Valid negative/NoChange results exit zero; corrupt or incomplete
experiments produce an integrity-failure receipt and exit nonzero.
"""

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from allocation import freeze_trace
from costs import ADAPTIVE, FIXED, ROLES, WEIGHTS, compare, complete_matrix, resources
from evidence import decode, digest, integer, owner_facts, read_bytes, read_json, require, verify_batch, verify_model_use, verify_progress
from fit_evidence import equivalent, verify_direct, verify_fit


SOURCE_FILES = (
    "codex-rs/hepta-agentd/src/memory_cell_prospective_tests.rs",
    "codex-rs/hepta-agentd/src/memory_cell_prospective_support.rs",
    "codex-rs/hepta-agentd/src/memory_cell_prospective_batches.rs",
    "codex-rs/hepta-agentd/src/memory_cell_prospective_direct.rs",
    "codex-rs/hepta-neuron/src/memory_population.rs",
    "codex-rs/hepta-neuron/src/memory_population_learned.rs",
    "codex-rs/hepta-agentd/src/memory_cell_bundle.rs",
    *(f"qualification/memory-cell-v8/learning/{name}.py" for name in ("score", "evidence", "fit_evidence", "costs")),
)
TRAINING_FILES = (
    "memory-cell-v7/training.py", "memory-cell-v7/training_worker.py", "memory-cell-v7/native_export.py",
    "memory-cell-v6/v6/__init__.py", "memory-cell-v6/v6/cells.py", "memory-cell-v6/v6/values.py",
    "memory-cell-v6/v6/contracts.py", "memory-cell-v7/population_training.py",
    *(f"memory-cell-v8/learning/{name}.py" for name in ("__init__", "allocation", "population_training", "worker")),
)


def verify_protocol(manifest):
    require(manifest["schema"] == "hepta.memory.prospective-lock.v1", "protocol lock schema")
    protocol = manifest["protocol"]
    require(protocol["schema"] == "hepta.memory.future-coaccess.v1"
            and protocol["fixed_inventory"] == list(range(1, 9)) and protocol["new_written_entities"] == 24
            and protocol["resident_budget_per_type_bytes"] == 16384 and protocol["weights"] == WEIGHTS,
            "frozen experimental protocol differs")
    require([(phase, protocol[phase]) for phase in ("prefix", "selection", "future", "retention")] == [
        ("prefix", {"tasks": 16, "reads_per_task": 6, "operation": "current"}),
        ("selection", {"tasks": 4, "reads_per_task": 6}), ("future", {"tasks": 12, "reads_per_task": 6}),
        ("retention", {"tasks": 4, "reads_per_task": 6})], "changed task budget")
    repository = Path(__file__).resolve().parents[3]
    pins = [{"path": name, "sha256": digest(read_bytes(repository / name))} for name in SOURCE_FILES]
    require(protocol["source_files"] == pins, "replay requires the exact recorded native/scoring source checkout")
    code = bytearray(b"hepta.memory.prospective.code.v1")
    for name in TRAINING_FILES:
        encoded = name.encode()
        code.extend(len(encoded).to_bytes(8, "big"))
        code.extend(encoded)
        code.extend(bytes.fromhex(digest(read_bytes(repository / "qualification" / name))))
    require(digest(code) == protocol["training_code_digest"], "training source files changed")
    return protocol


def native_costs(arm):
    if arm["trial"]["routing_mode"] == "direct_owner":
        return None
    snapshots = [batch["native_cost_after_phase"] for batch in arm["evaluations"]]
    counters = ("read_count", "wake_count", "eviction_count", "artifact_load_wall_ns", "read_wall_ns", "wake_wall_ns")
    for phase in snapshots:
        require(len(phase) == 2, "missing native type cost")
        for model in phase:
            require(model["resident_budget_bytes"] == arm["trial"]["resident_budget_bytes"], "native budget mismatch")
            resident = sum(integer(model[f"resident_{name}_bytes"], "resident payload")
                           for name in ("parameter", "catalog", "support", "lineage"))
            require(resident <= model["resident_budget_bytes"], "native cache exceeded frozen logical budget")
    for before, after in zip(snapshots, snapshots[1:]):
        require(all(integer(end[name], name) >= integer(start[name], name)
                    for start, end in zip(before, after) for name in counters), "native cumulative counter moved backwards")
    return {"last_cumulative_snapshot": snapshots[-1],
            "future_phase_counter_delta": [{name: end[name] - start[name] for name in counters}
                                           for start, end in zip(snapshots[0], snapshots[1])],
            "cumulative_snapshots_summed": False, "nested_wall_added_to_lifecycle_again": False}


def verify_arm(augmented, directory, manifest, cut):
    trial = augmented["trial"]
    role = trial["id"]
    require(role in ROLES, "unknown trial")
    location = directory / role
    require(location.is_dir() and not location.is_symlink(), "missing trial directory")
    raw = read_bytes(location / "TRIAL.json")
    require(digest(raw) == augmented["raw_trial_sha256"], "raw trial digest differs")
    arm = decode(raw)
    extras = {name: augmented[name] for name in ("parent_execution", "raw_trial_sha256", "materialized_trial_logical_bytes")}
    require(equivalent(dict(arm, **extras), augmented), "parent summary changed child evidence")
    arm.update(extras)
    require(arm["schema"] == "hepta.memory.prospective-trial.v1" and arm["source_cut"] == cut, "trial source cut mismatch")
    require(read_json(location / "CONFIG.json") == trial and trial["seed"] == manifest["seed"]
            and trial["resident_budget_bytes"] == 16384, "trial configuration mismatch")
    direct = role == "direct-owner"
    require(trial["routing_mode"] == ("direct_owner" if direct else "learned" if role == "learned-coaccess" else "fixed"),
            "role and routing mode differ")
    require(1 <= integer(trial["count"], "shard count", 1) <= 8, "shard count exceeds frozen inventory")
    if role in FIXED:
        require(trial["count"] == int(role.split("-")[1]), "fixed inventory count changed")
    require(trial["expected_source_cut"] == (None if role == "fixed-1" else cut), "trial source precondition mismatch")
    execution_file = directory / f"{role}-execution.json"
    execution = read_json(execution_file)
    require(execution == arm["parent_execution"] and execution["exit_code"] == 0
            and execution["child_pid"] == arm["child_pid"] != execution["parent_pid"], "failed/nonindependent child execution")
    files = list(location.iterdir())
    require(all(file.is_file() and not file.is_symlink() for file in files), "unexpected nested or symbolic trial evidence")
    require(sum(file.stat().st_size for file in files) == arm["materialized_trial_logical_bytes"], "trial material byte inventory changed")
    start = read_json(location / "START.json")
    require(start == {"trial": trial, "source_cut": cut, "child_pid": arm["child_pid"],
                      "training_code_digest": manifest["protocol"]["training_code_digest"]}, "trial start binding mismatch")
    causal = verify_progress(location, direct)
    export = read_json(location / "OWNER_EXPORT.json")
    facts = owner_facts(export, cut)
    before, prefix = arm["before_retention"], arm["prefix"]
    require(before == read_json(location / "before-retention.json") and prefix == read_json(location / "completed-prefix.json"),
            "retention/prefix bytes differ from recorded phase")
    before_score = verify_batch(before, export, facts, trial["seed"], direct, 1)
    prefix_score = verify_batch(prefix, export, facts, trial["seed"], direct, 1)
    require(prefix_score["read_errors"] == 0, "completed source observation prefix was unsuccessful")
    require([batch["phase"] for batch in arm["evaluations"]] == ["selection", "future", "retention"], "incomplete evaluation order")
    scores = {}
    for batch in arm["evaluations"]:
        require(batch == read_json(location / f"{batch['phase']}.json"), "raw evaluation differs")
        scores[batch["phase"]] = verify_batch(batch, export, facts, trial["seed"], direct, 2)
    require(before_score["request_digests"] == scores["retention"]["request_digests"], "before/after retention cohort changed")
    lock = read_json(location / "FIT_LOCK.json")
    require(lock["source_cut"] == cut and lock["future_outcomes_seen"] is False
            and lock["future_protocol"] == manifest["protocol"]["schema"], "candidate/future lock mismatch")
    fits = []
    if direct:
        require(arm["routing_trace"] is None and arm["training_processes"] == [] and arm["training_fit_calls"] == 0
                and arm["model_storage_bytes"] == 0 and arm["bootstrap_training"] is None and arm["candidate_training"] is None
                and arm["training_code_digest"] is None and arm["artifact_owner_logical_bytes"] == 0
                and arm["artifact_files"] == [] and lock["training_executed"] is False, "direct baseline performed model work")
        acquisition = read_json(location / "owner-acquisition.json")
        require(acquisition == arm["owner_acquisition"] and acquisition["logical_cache_bytes"] == arm["direct_owner_cache_logical_bytes"],
                "direct acquisition summary mismatch")
        require(lock["direct_owner_cache_bytes"] == acquisition["logical_cache_bytes"], "direct cache differs from lock")
        verify_direct(acquisition, facts, export, trial["resident_budget_bytes"])
    else:
        observations = [{name: record[name] for name in ("sequence", "request_digest", "readout_digest", "addresses")}
                        for record in prefix["records"]]
        trace = freeze_trace(cut, observations)
        require(arm["routing_trace"] == read_json(location / "ROUTING_TRACE.json") == trace
                and lock["routing_trace_digest"] == trace["trace_digest"], "routing trace is not the complete retained prefix")
        for stage, count, fit_trace in (("bootstrap", 4, None), ("candidate", trial["count"], trace if role == "learned-coaccess" else None)):
            fit = verify_fit(location / f"{stage}-fit.json", facts, cut, count, fit_trace, manifest["protocol"]["training_code_digest"])
            require(equivalent(fit["receipt"], arm[f"{stage}_training"]), "summarized training receipt differs from exact worker bytes")
            fits.append(fit)
        require([fit["measurement"] for fit in fits] == arm["training_processes"], "training process accounting mismatch")
        for batch in (before, prefix):
            verify_model_use(batch, fits[0]["native_digests"])
        for batch in arm["evaluations"]:
            verify_model_use(batch, fits[1]["native_digests"])
            require(all(readout["status"] != "ok" or readout["snapshot_digest"] == lock["bundle_digest"]
                        for record in batch["records"] for readout in record["readouts"]), "future used an unlocked candidate")
    for category in ("source", "artifact"):
        field = "source_ledger_logical_bytes" if category == "source" else "artifact_owner_logical_bytes"
        require(sum(integer(file["logical_bytes"], "observed file size") for file in arm[f"{category}_files"]) == arm[field],
                "owner storage byte sum mismatch")
    for field in ("rpc_attempts", "transmitted_bytes", "received_bytes"):
        require(integer(arm["traffic"][field], field) >= sum(batch["traffic"][field] for batch in [before, prefix, *arm["evaluations"]]),
                "phase transport exceeds complete actual transport")
    vector, cost_details = resources(arm, fits, execution_file.stat().st_size)
    retention = {"before": before_score, "after": scores["retention"],
        "read_error_delta": scores["retention"]["read_errors"] - before_score["read_errors"],
        "decision_error_delta": scores["retention"]["decision_errors"] - before_score["decision_errors"],
        "scope": "same written support/cut through clean refit and repartition; not longitudinal new-data forgetting"}
    return {"id": role, "count": trial["count"], "prefix": prefix_score, "selection": scores["selection"],
        "future": scores["future"], "retention": retention, "resources": vector, "cost_observations": cost_details,
        "native_cost": native_costs(arm), "causal_chain": causal,
        "training_diagnostics": [item for fit in fits for item in fit["diagnostics"]],
        "selection_wall_ns": arm["evaluations"][0]["socket_and_native_wall_ns"]}


def score(path):
    raw = read_bytes(path)
    report = decode(raw)
    require(report["schema"] == "hepta.memory.v8.actual-prospective-comparison.v1"
            and report["total_actual_trials"] == 11, "incomplete prospective experiment")
    directory = path.with_suffix(".artifacts")
    require(directory.is_dir() and not directory.is_symlink(), "missing relocated raw evidence directory")
    manifest = read_json(directory / "MANIFEST.json")
    require(manifest == report["manifest"], "manifest changed")
    protocol = verify_protocol(manifest)
    complete_matrix([{"id": arm["trial"]["id"]} for arm in report["arms"]])
    arms = [verify_arm(arm, directory, manifest, report["source_cut"]) for arm in report["arms"]]
    inventory = complete_matrix(arms)
    for phase in ("prefix", "selection", "future"):
        require(all(arm[phase]["request_digests"] == arms[0][phase]["request_digests"] for arm in arms), "counterfactual requests differ")
    require(all(arm["retention"]["before"]["request_digests"] == arms[0]["retention"]["before"]["request_digests"] for arm in arms),
            "counterfactual retention cohort differs")
    selected = min((inventory[role] for role in FIXED), key=lambda arm: (arm["selection"]["decision_errors"], arm["selection_wall_ns"], arm["count"]))["count"]
    lock = read_json(directory / "SELECTION_LOCK.json")
    expected_lock = {"selected_count": selected, "fixed_inventory_selection_search_is_charged": True,
        "future_outcomes_are_selector_input": False, "input": [{"count": arm["trial"]["count"], "selection": arm["evaluations"][0]}
        for arm in report["arms"] if arm["trial"]["id"] in FIXED]}
    require(equivalent(lock, expected_lock) and selected == report["selected_count_from_prefix"]
            and all(inventory[role]["count"] == selected for role in (*ADAPTIVE, "direct-owner")), "past-only selector lock mismatch")
    common_bytes = len(raw) + sum((directory / name).stat().st_size for name in ("MANIFEST.json", "SELECTION_LOCK.json"))
    accounting = compare(arms, protocol["weights"], common_bytes, report["selector_wall_ns"])
    return {"schema": "hepta.memory.v8.prospective-score.v1", "input_sha256": digest(raw), "integrity_verified": True,
        "actual_trials": len(arms), "source_cut": report["source_cut"], "selected_count_from_prefix": selected,
        "arms": arms, "accounting": accounting, "decision": "NoChange",
        "scope": {"real_native_sqlite_socket_execution": True,
            "parameter_updates_observed": any(item["parameter_update"] for arm in arms for item in arm["training_diagnostics"]),
            "future_composite_tasks_on_previously_written_support": True,
            "retention_before_and_after_clean_repartition": True, "same_prefix_requests_source_values_and_selection_information": True,
            "unseen_unwritten_address_generalization": False, "language_model_finetuning": False,
            "parameter_only_compression": False, "independent_iid_population_risk": False,
            "autonomous_structural_actions": False, "self_authenticating_owner_export_or_progress_chain": False}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    status = 0
    try:
        result = score(arguments.input)
    except Exception as error:
        # The CLI is a fail-closed audit boundary: malformed data and unexpected
        # verifier errors both retain a diagnostic receipt and a nonzero status.
        result = {"schema": "hepta.memory.v8.prospective-score.v1", "integrity_verified": False,
                  "decision": "NoChange", "error": str(error), "error_type": type(error).__name__,
                  "failed_or_missing_arms_discarded": False}
        status = 1
    with arguments.output.open("xb") as stream:
        stream.write(json.dumps(result, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"output": str(arguments.output), "integrity_verified": result["integrity_verified"], "decision": "NoChange"}))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
