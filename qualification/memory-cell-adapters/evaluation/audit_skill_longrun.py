"""Independently audit a complete frozen 64 x 3 skill-maintenance experiment.

Reads original evidence through explicit path maps. Does not import the owner,
model, trainer, manager, target generator, or interpreter under test. NumPy
float32 arithmetic replays saved coefficients; an independent interpreter
checks each recorded execution trace. Quality may fail while integrity passes.
"""

import argparse
from collections import Counter
import copy
import json
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from skill_audit_report import write_bounded_report
from audit_skill_longrun_ci import audit_ci, audit_monitor, cost_summary
from audit_skill_longrun_fit import fit_check
from audit_skill_longrun_support import (
    ARMS, GROUPS, PROBES, SEEDS, EvidencePaths, ProcessAudit, canonical, checkpoint,
    decoded_programs, feature_arrays, file_bytes, groups, identity, load, next_program,
    preflight_check, read_check, sha, sql_state, tree_identity, unchanged_owner_state,
)


def aggregate(records, field):
    totals = {arm: groups() for arm in ARMS}
    for record in records:
        for arm in ARMS:
            for group in GROUPS:
                for key in ("correct", "count"):
                    totals[arm][group][key] += record[field][arm][group][key]
    return totals


def audit(run_root, checkout_root, initial_study, bundle_root=None):
    began = time.monotonic_ns()
    run, checkout = run_root.resolve(strict=True), checkout_root.resolve(strict=True)
    protocol_path = checkout / "qualification/memory-cell-adapters/skill_longrun/LONGRUN_PROTOCOL.json"
    protocol, freeze, summary = load(protocol_path), load(run / "FREEZE.json"), load(run / "RESULT.json")
    paths = EvidencePaths(run, checkout, initial_study, protocol, bundle_root)
    before = tree_identity(paths.bundle or run)
    checks, phase_records, state_identities = {}, [], {}

    def check(name, okay):
        if name in checks:
            raise ValueError("Duplicate audit check: " + name)
        checks[name] = bool(okay)

    protocol_sha = identity(protocol_path)["sha256"]
    check("protocol_identity", protocol_sha == freeze["protocol_sha256"] == summary["protocol_sha256"]
          == protocol_path.with_suffix(".sha256").read_text().strip())
    check("registered_horizon", protocol["schema"] == "hepta.memory.adapter-skill-longrun-protocol.v1"
          and protocol["seeds"] == list(SEEDS) and protocol["cycles_per_seed"] == 64
          and protocol["expected_fits"] == {"updates": 192, "clean_rebuilds": 24,
                                           "total_steps": 129600, "total_sample_presentations": 4147200})
    check("registered_fit", protocol["fit"] == {"steps": 600, "batch_size": 32, "lr": 0.01, "train_head": True,
          "threads": 1, "sample_seed": "seed + stage", "replay": "all active skill rows"})
    check("registered_execution_probes", protocol["execution_probes"] == [
        {"input": value, "policy": list(policy), "max_steps": 4} for value, policy in PROBES])
    check("freeze_scope", freeze["schema"] == "hepta.memory.adapter-longrun-freeze.v1" and freeze["scope"] == "skill"
          and not freeze["historical_clock_compared_to_runner"] and not freeze["held_or_main_result_opened"]
          and not freeze["reader_targets_supplied"] and not freeze["native_runtime_executed"])
    for name, expected in freeze["source_files"].items():
        check("frozen_source:" + name, identity(paths.resolve(name)) == expected)
    adapter = checkout / "qualification/memory-cell-adapters"
    required = {*(adapter / "skill_longrun").glob("*.py"), protocol_path, protocol_path.with_suffix(".sha256"),
                *[adapter / name for name in ("owner.py", "reader.py", "routing.py", "tensor_cell.py", "runtime_contract.py")],
                adapter / "longrun/ci_run.py", adapter / "evidence/formal-01/restore.py",
                *[checkout / "qualification/memory-cell-v9/learning" / name
                  for name in ("resource_monitor.py", "resource_samples.py", "resource_cleanup.py")]}
    check("frozen_source_dependency_inventory", {paths.resolve(name) for name in freeze["source_files"]} == required)
    input_files = {str(path.relative_to(run / "inputs")): identity(path)
                   for path in (run / "inputs").rglob("*") if path.is_file()}
    check("frozen_input_inventory", input_files == freeze["input_files"])
    for name in ("sources.json", "canonical.npz", "development-encoder.json", "training.process.json"):
        check("initial_source_copy:" + name, identity(run / "inputs" / name) == identity(paths.initial / name))
    training, historical = load(run / "inputs/TRAINING.json"), load(run / "inputs/training.process.json")
    check("initial_training_binding", identity(run / "inputs/TRAINING.json") == freeze["initial_training_receipt"]
          == identity(paths.initial / "models/TRAINING.json") and historical["exit_code"] == 0 and not historical["timed_out"]
          and historical["pid"] == training["pid"] == freeze["initial_training_pid"]
          and historical["exited_ns"] == freeze["initial_trainer_exited_ns_historical_clock"])
    features, feature_identity = feature_arrays(run / "inputs/canonical.npz")
    encoder = load(run / "inputs/development-encoder.json")
    check("initial_encoder_identity", encoder["base_encoder_sha"] == training["encoder_sha"])
    source_fields = ("kind", "index", "source_id", "version", "value")
    original_sources = [{key: row[key] for key in source_fields}
                        for row in load(run / "inputs/sources.json") if row["kind"] == "skill"]
    check("initial_source_inventory", [row["index"] for row in original_sources] == list(range(8)))
    context = {"paths": paths, "check": check, "processes": ProcessAudit(run, check),
               "protocol_path": protocol_path, "protocol_sha": protocol_sha, "encoder_sha": encoder["base_encoder_sha"],
               "features": features, "feature_identity": feature_identity, "manifests": {}, "decoded": {},
               "fit_records": [], "read_records": []}
    decoded_records = []

    def decode_checkpoint(folder):
        label = str(folder.relative_to(run))
        if str(folder) in context["manifests"]:
            raise ValueError("Checkpoint decoded twice: " + label)
        manifest, arrays = checkpoint(folder, context["encoder_sha"], check, label)
        context["manifests"][str(folder)] = manifest
        decoded = decoded_programs(arrays, features["skill"])
        context["decoded"][str(folder)] = decoded
        decoded_records.append({"checkpoint": label, "parameter_sha256": manifest["parameter_sha256"],
                                "persistent_bytes": file_bytes(folder), "float32_parameter_bytes": 55408,
                                "minimum_top_two_logit_margin": decoded["minimum_top_two_logit_margin"]})
        if folder.name.startswith("untrained-seed-"):
            check("untrained_initialization:" + label, not manifest["source_ids"] and not manifest["training_history"]
                  and not manifest["parents"] and np.count_nonzero(arrays["B"]) == 0)
        return manifest

    context["decode_checkpoint"] = decode_checkpoint
    cycles = [load(path) for path in sorted(run.glob("seed-*/stage-*/CYCLE.json"))]
    by_cycle = {(row["seed"], row["stage"]): row for row in cycles}
    check("complete_cycle_inventory", len(cycles) == len(by_cycle) == 192
          and set(by_cycle) == {(seed, stage) for seed in SEEDS for stage in range(1, 65)})
    check("cycles_file_binding", load(run / "CYCLES.json") == cycles)
    phases, initial_records = [], []
    state_keys = ("index", "source_id", "version", "active", "value")
    for seed in SEEDS:
        seed_root = run / f"seed-{seed}"
        previous_path, untrained_path = run / "inputs" / f"seed-{seed}", run / "inputs" / f"untrained-seed-{seed}"
        previous, untrained = decode_checkpoint(previous_path), decode_checkpoint(untrained_path)
        original_checkpoint = paths.initial / "models" / f"seed-{seed}" / "skill"
        check("trained_checkpoint_copy:" + str(seed), tree_identity(previous_path) == tree_identity(original_checkpoint))
        check("untrained_seed_architecture:" + str(seed), untrained["config"]["seed"] == previous["config"]["seed"] == seed
              and all(untrained["config"][key] == previous["config"][key] for key in ("rank", "input_dim", "outputs")))
        initial_database = run / "inputs" / f"read-seed-{seed}-event-0.sqlite"
        check("original_source_database_copy:" + str(seed), identity(initial_database)
              == identity(paths.initial / initial_database.name))
        state = [{**copy.deepcopy(row), "active": True} for row in original_sources]
        check("initial_source_database_state:" + str(seed), sql_state(initial_database)
              == sql_state(seed_root / "initial-sources.sqlite") == [{key: row[key] for key in state_keys} for row in state])
        stable_owner = unchanged_owner_state(initial_database)
        check("initial_non_skill_sources_preserved:" + str(seed), unchanged_owner_state(seed_root / "initial-sources.sqlite") == stable_owner)
        previous_read, readout, quality, execution_quality = read_check(seed_root / "initial-read", previous_path, previous,
            seed_root / "initial-sources.sqlite", state, [], context)
        context["read_records"].append((previous_read, readout))
        check("initial_reader_after_freeze:" + str(seed), previous_read["started_ns"] > freeze["created_ns"])
        initial_records.append({"seed": seed, "quality": quality, "execution_quality": execution_quality, "process": previous_read})
        pending = None
        for stage in range(1, 65):
            cycle = by_cycle[(seed, stage)]
            changed = sorted({stage % 8} | ({pending} if pending is not None else set()))
            reentered, pending = pending, None
            for workflow in changed:
                row = state[workflow]
                program = next_program(seed, stage, workflow, row["value"])
                row.update(version=row["version"] + 1, active=True, value=program)
                row["source_id"] = sha(canonical(["hepta.adapter.skill-longrun.source.v1", seed,
                    workflow, row["version"], stage, program]))
            modes = ["update", "rebuild"] if stage % 8 == 0 else ["update"]
            check(f"cycle_phase_order:{seed}:{stage}", cycle["phase_count"] == len(modes)
                  and cycle["phase_paths"] == [f"seed-{seed}/stage-{stage:03d}/{mode}/RESULT.json" for mode in modes])
            for mode in modes:
                folder = seed_root / f"stage-{stage:03d}" / mode
                label, record, deleted = str(folder.relative_to(run)), load(folder / "RESULT.json"), None
                if mode == "rebuild":
                    deleted = (stage // 8) % 8
                    state[deleted]["active"], pending = False, deleted
                check("phase_identity:" + label,
                      (record["seed"], record["stage"], record["mode"], record["changed_workflows"],
                       record["reentered_workflow"], record["deleted_workflow"]) == (seed, stage, mode, changed, reentered, deleted))
                check("independent_source_schedule:" + label, load(folder / "source-state.json") == state)
                check("actual_sqlite_source_state:" + label,
                      sql_state(folder / "sources.sqlite") == [{key: row[key] for key in state_keys} for row in state])
                check("non_skill_sources_and_events_preserved:" + label,
                      unchanged_owner_state(folder / "sources.sqlite") == stable_owner)
                preflight_check(load(folder / "preflight.json"), "revoked" if mode == "rebuild" else "stale_source",
                    [deleted] if mode == "rebuild" else changed, state, previous, check, label)
                fit_process, fit, manifest = fit_check(folder, previous_path, untrained_path, state, seed, stage, mode, context)
                check("trainer_after_previous_reader_exit:" + label, fit_process["started_ns"] > previous_read["exited_ns"])
                previous_path = folder / "checkpoint"
                previous_read, readout, quality, execution_quality = read_check(folder / "read", previous_path, manifest,
                    folder / "sources.sqlite", state, changed, context)
                context["read_records"].append((previous_read, readout))
                check("fresh_reader_after_trainer_exit:" + label,
                      previous_read["started_ns"] > fit_process["exited_ns"] and previous_read["pid"] != fit_process["pid"])
                check("phase_outcome_binding:" + label,
                      record["quality"] == quality and record["execution_quality"] == execution_quality
                      and record["model"] == {"checkpoint": str(previous_path.relative_to(run)),
                                             "parameter_sha256": manifest["parameter_sha256"]}
                      and record["preflight_passed"] and record["trainer_passed"] and record["reader_passed"]
                      and record["fresh_reader_after_trainer_exit"])
                check("phase_cost_binding:" + label,
                      record["fit_wall_ns"] == fit_process["wall_ns"] and record["fit_cpu_seconds"] == fit_process["cpu_seconds"]
                      and record["read_process_wall_ns"] == previous_read["wall_ns"]
                      and record["read_process_cpu_seconds"] == previous_read["cpu_seconds"]
                      and record["baseline_and_parameter_read_wall_ns"] == {arm["arm"]: arm["read_wall_ns"] for arm in readout["arms"]})
                check("phase_storage_binding:" + label, record["storage"] == {
                    "current_checkpoint_bytes": file_bytes(previous_path), "source_sqlite_bytes": identity(folder / "sources.sqlite")["bytes"],
                    "active_source_payload_json_bytes": len(canonical([row["value"] for row in state if row["active"]])),
                    "all_source_payload_json_bytes": len(canonical([row["value"] for row in state])),
                    "source_version_record_json_bytes": len(canonical(state)), "shared_encoder_reference_bytes": encoder["base_bytes"],
                    "canonical_feature_file_bytes": feature_identity["bytes"]})
                phases.append(record)
                phase_records.append({"seed": seed, "stage": stage, "mode": mode, "quality": quality,
                    "execution_quality": execution_quality, "parameter_sha256": manifest["parameter_sha256"],
                    "source_rows_sha256": fit["source_rows_sha256"], "sample_schedule_sha256": fit["sample_schedule"]["sha256"]})
                previous = manifest
            check(f"cycle_final_phase_binding:{seed}:{stage}", cycle["quality"] == quality
                  and cycle["execution_quality"] == execution_quality and cycle["final_model"] == record["model"])
            state_identities[f"{seed}:{stage}"] = {"source_state_sha256": sha(canonical(state)),
                "active_workflows": [row["index"] for row in state if row["active"]]}
        check("final_sqlite_source_state:" + str(seed), sql_state(seed_root / "owner.sqlite")
              == [{key: row[key] for key in state_keys} for row in state])
    # The retained original training.process.json belongs to a different host
    # and study. Count only children executed by this skill-maintenance run.
    inventory = [load(path) for seed in SEEDS for path in (run / f"seed-{seed}").rglob("*.process.json")]
    processes = context["processes"].records
    ordered = sorted(processes, key=lambda row: row["started_ns"])
    check("complete_child_process_inventory", len(processes) == len(inventory) == 435
          and ordered == sorted(inventory, key=lambda row: row["started_ns"])
          and processes == load(run / "PROCESSES.json"))
    check("all_children_serial", all(a["exited_ns"] < b["started_ns"] for a, b in zip(ordered, ordered[1:])))
    check("complete_fit_read_checkpoint_inventory", len(context["fit_records"]) == 216
          and len(context["read_records"]) == 219 and len(context["manifests"]) == 222
          and Counter(row["mode"] for row in phases) == {"update": 192, "rebuild": 24})
    check("initial_quality_binding", summary["initial_quality"] == initial_records)
    aggregates = {"final_cycle_aggregate": aggregate(cycles, "quality"),
                  "final_cycle_execution_aggregate": aggregate(cycles, "execution_quality"),
                  "all_phase_aggregate": aggregate(phases, "quality"),
                  "all_phase_execution_aggregate": aggregate(phases, "execution_quality")}
    for name, result in aggregates.items():
        check("summary_aggregate:" + name, summary[name] == result)
    all_correct = all(counts["correct"] == counts["count"] for record in [*initial_records, *phases]
                      for key in ("quality", "execution_quality") for arm in ARMS for counts in record[key][arm].values())
    check("quality_boolean_is_independent_of_integrity", summary["quality_all_correct"] == all_correct)
    check("execution_horizon", summary["completed_cycles"] == 192 and summary["phase_count"] == 216
          and summary["update_fits_attempted"] == 192 and summary["rebuild_fits_attempted"] == 24
          and not summary["failures"] and summary["all_preflight_passed"] and summary["all_readers_after_trainer_exit"]
          and summary["all_steps_retained"] and not summary["native_runtime_executed"] and not summary["held_inputs_opened"]
          and summary["actual_public_programs_executed"])
    cost = summary["cost"]
    for key, script in (("children_cpu_seconds_including_failures", None),
                        ("training_children_cpu_seconds", "fit_worker.py"), ("reader_children_cpu_seconds", "owner_read.py")):
        check("process_cpu_sum:" + key, abs(cost[key] - sum(row["cpu_seconds"] for row in processes
              if script is None or row["script"] == script)) < 0.000001)
    check("process_wall_io_sum", cost["children_wall_ns_including_failures"] == sum(row["wall_ns"] for row in processes)
          and cost["kernel_output_blocks_children"] == sum(row["kernel_output_blocks"] for row in processes))
    for key, pattern in (("initial_checkpoint_copies_bytes", "inputs/seed-*"),
                         ("untrained_checkpoint_bytes", "inputs/untrained-seed-*"),
                         ("retained_fitted_checkpoint_bytes", "seed-*/stage-*/*/checkpoint")):
        check("checkpoint_storage:" + key, cost[key] == sum(file_bytes(path) for path in run.glob(pattern)))
    for key, pattern in (("current_source_sqlite_bytes", "seed-*/owner.sqlite"),
                         ("historical_source_sqlite_snapshot_bytes", "seed-*/stage-*/*/sources.sqlite"),
                         ("initial_source_sqlite_snapshot_bytes", "seed-*/initial-sources.sqlite"),
                         ("retained_sample_schedule_bytes", "seed-*/stage-*/*/sample-schedule.i64")):
        check("raw_storage:" + key, cost[key] == sum(identity(path)["bytes"] for path in run.glob(pattern)))
    check("source_payload_json_storage", cost["retained_explicit_source_json_bytes"]
          == sum(identity(path)["bytes"] for path in run.rglob("*sources.json"))
          + sum(identity(path)["bytes"] for path in run.rglob("source-state.json")))
    check("shared_encoder_and_features", cost["shared_encoder_reference_bytes"] == encoder["base_bytes"]
          and cost["canonical_features_bytes"] == feature_identity["bytes"])
    resource, resource_audit = audit_monitor(context)
    ci = audit_ci(context, summary, freeze, resource)
    check("evidence_tree_read_only", tree_identity(paths.bundle or run) == before)
    forbidden = {"torch", "tensor_cell", "owner", "reader", "targets", "manager", "fit_worker", "runtime_contract"}
    check("audit_import_boundary", not forbidden.intersection(sys.modules))
    return {"schema": "hepta.memory.skill-longrun-independent-audit.v1", "scope": "skill",
            "passed": all(checks.values()), "check_count": len(checks), "failed_checks": [name for name, okay in checks.items() if not okay],
            "checks": checks, "read_only_evidence": True, "training_executed": False,
            "producer_model_or_trainer_imported": False, "independent_float32_arithmetic_replay": True,
            "independent_program_interpreter_executed": True, "native_runtime_executed": False,
            "protocol_sha256": protocol_sha, "completed_cycles": 192, "completed_fit_phases": 216,
            "completed_update_fits": 192, "completed_clean_rebuilds": 24,
            "completed_steps": 129600, "completed_sample_presentations": 4147200,
            "fresh_read_processes": 219, "completed_child_processes": 435,
            "quality_all_correct": all_correct, **aggregates,
            "phase_records": phase_records, "cycle_source_state_identities": state_identities,
            "tensor_decoding": decoded_records, "cost_inventory": cost,
            "cost_summary": cost_summary(context, resource, ci), "resource_sample_audit": resource_audit,
            "read_only_path_mapping": paths.report(), "evidence_tree_identity": before,
            "final_artifact_identities": {name: identity(run / name) for name in
                ("FREEZE.json", "RESULT.json", "CYCLES.json", "PROCESSES.json", "resource.json")},
            "audit_started_ns": began, "audit_finished_ns": time.monotonic_ns(),
            "limitations": [
                "Eight known canonical addresses, full active replay, synthetic changes, and four public execution probes; no held-language or open-world skill claim.",
                "Saved schedule bytes match the actual-fit schedule digest and checked row bounds; this auditor does not independently reproduce PyTorch's random-number generator.",
                "Parameter and exact-SQL arms share fresh reader processes and fixed arm order; arm timings are not isolated deployment latencies.",
                "Historical checkpoints and explicit sources remain stored. Revocation and clean rebuilding do not erase historical archives.",
                "No production model is imported; saved coefficients are independently replayed with float32 NumPy arithmetic and argmax.",
                "Sampled memory/storage integrals include explicit unknown intervals. Nested child, manager, monitor, and wrapper CPU totals must not be added.",
                "The manager before-summary byte count overlaps a concurrently growing monitor log; it is retained as a snapshot claim, not independently reconstructed as an exact continuous storage total.",
                "This separate skill run cannot replace the prior semantic experiments or their costs. Native Agentd integration and full lifecycle superiority are not demonstrated."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--checkout-root", type=Path, required=True)
    parser.add_argument("--initial-study", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to((args.bundle_root or args.run_root).resolve()):
        raise ValueError("Audit output must be outside the original evidence")
    report = audit(args.run_root, args.checkout_root, args.initial_study, args.bundle_root)
    write_bounded_report(args.output, report)
    print(json.dumps({key: report[key] for key in ("passed", "check_count", "failed_checks", "quality_all_correct",
                                                 "completed_cycles", "completed_fit_phases")}))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
