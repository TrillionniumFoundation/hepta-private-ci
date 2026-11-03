"""Audit a completed clean longrun without executing models or training.

Reconstructs the declared source schedule, checks every fit/read chain, scores
saved outputs independently, and recomputes sampled resource accounting.
"""

import argparse
from collections import Counter
import copy
import json
from pathlib import Path
import time

import numpy as np

from audit_longrun_resume import (
    audit_resource_samples, canonical, identity, load, score_rows, sha, sql_state,
    write_bounded_report,
)


def file_bytes(root):
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def audit(run):
    began = time.monotonic_ns()
    checks, processes, phase_records, state_identities = {}, [], [], {}

    def check(name, okay):
        if name in checks:
            raise ValueError("Duplicate audit check " + name)
        checks[name] = bool(okay)

    summary = load(run / "RESULT.json")
    resource = load(run / "resource.json")
    freeze = load(run / "FREEZE.json")
    protocol_path = run.parent / "LONGRUN_PROTOCOL.json"
    protocol = load(protocol_path)
    protocol_sha = identity(protocol_path)["sha256"]
    check("protocol_binding", protocol_sha == freeze["protocol_sha256"] == summary["protocol_sha256"]
          == (run.parent / "LONGRUN_PROTOCOL.sha256").read_text().strip())
    check("unchanged_fixed_fit_protocol", protocol["fit"]["steps"] == 600 and protocol["fit"]["batch_size"] == 32
          and protocol["fit"]["lr"] == 0.01 and protocol["fit"]["train_head"] is True)
    check("registered_horizon", protocol["seeds"] == [731, 732, 733] and protocol["cycles_per_seed"] == 64)
    for name, expected in freeze["source_files"].items():
        check("frozen_source:" + name, identity(Path(name)) == expected)
    for name, expected in freeze["input_files"].items():
        check("frozen_input:" + name, identity(run / "inputs" / name) == expected)
    check("original_training_finished_first", freeze["initial_trainer_exited_ns"] < freeze["created_ns"])
    original_run = Path(protocol["initial_study"])
    check("initial_training_receipt_bound", identity(original_run / "models/TRAINING.json") == freeze["initial_training_receipt"])
    source_rows = [row for row in load(run / "inputs/sources.json") if row["kind"] == "semantic"]
    with np.load(run / "inputs/canonical.npz", allow_pickle=False) as data:
        features = data["semantic"].copy()
    encoder = load(run / "inputs/development-encoder.json")
    check("canonical_and_source_inventory", features.shape == (8, 384)
          and [row["index"] for row in source_rows] == list(range(8)))
    cycles = [load(path) for path in sorted(run.glob("seed-*/stage-*/CYCLE.json"))]
    by_cycle = {(row["seed"], row["stage"]): row for row in cycles}
    check("full_cycle_inventory", len(cycles) == len(by_cycle) == 192
          and set(by_cycle) == {(seed, stage) for seed in (731, 732, 733) for stage in range(1, 65)})
    check("cycles_file_binding", load(run / "CYCLES.json") == sorted(cycles, key=lambda row: (row["seed"], row["stage"])))
    prior_phases = {}
    for name in ("run-01", "run-02-resume"):
        for path in (run.parent / name).glob("seed-*/stage-*/*/RESULT.json"):
            value = load(path)
            key = (value["seed"], value["stage"], value["mode"])
            if key in prior_phases:
                raise ValueError("Duplicate completed phase in comparison chain")
            prior_phases[key] = path.parent
    check("prior_replication_phase_inventory", len(prior_phases) == 216)

    def process(stem):
        label = str(stem.relative_to(run))
        receipt = load(stem.with_suffix(".process.json"))
        check("child_completed:" + label, receipt["exit_code"] == 0 and receipt["passed"] and not receipt["timed_out"])
        check("child_wall:" + label, receipt["wall_ns"] == receipt["exited_ns"] - receipt["started_ns"])
        for kind in ("stdout", "stderr", "request"):
            suffix = ".request.json" if kind == "request" else "." + kind
            check("child_blob:" + label + ":" + kind, identity(stem.with_suffix(suffix)) == receipt[kind])
        processes.append(receipt)
        return receipt

    def read_check(folder, checkpoint, state, changed, stem_name="read"):
        stem = folder / stem_name
        proc = process(stem)
        report, request = load(stem.with_suffix(".stdout")), load(stem.with_suffix(".request.json"))
        label = str(stem.relative_to(run))
        manifest = load(checkpoint / "manifest.json")
        check("reader_request_contract:" + label,
              set(request) == {"checkpoint", "encoder_sha", "database", "canonical_features_path", "protocol_sha256"}
              and Path(request["checkpoint"]) == checkpoint and request["protocol_sha256"] == protocol_sha)
        check("reader_checkpoint_binding:" + label,
              report["parameter_sha256"] == manifest["parameter_sha256"]
              and report["manifest_sha256"] == identity(checkpoint / "manifest.json")["sha256"]
              and report["source_ids"] == manifest["source_ids"])
        check("reader_boundary:" + label, not report["training_modules_loaded"] and not report["target_module_import_audit"]
              and report["gradient_steps"] == 0 and not report["native_runtime_executed"])
        check("reader_arms:" + label, [arm["arm"] for arm in report["arms"]] == ["parameter", "exact_sql"])
        check("same_owner_state:" + label, len({arm["owner_snapshot_sha256"] for arm in report["arms"]}) == 1)
        parameter = report["arms"][0]
        check("parameter_no_source_payload:" + label, parameter["reads"]["explicit_values"] == 0
              and parameter["sql_audit"]["source_payload_column_authorizations"] == 0)
        check("owner_stop_contract:" + label, all(arm["owner_stop_probe"]["status"] == "owner_stopped"
              and arm["memory_stop_probe"]["status"] == "owner_stopped" for arm in report["arms"]))
        check("reader_model_call_inventory:" + label, report["model_reads"]["calls"] == sum(row["active"] for row in state))
        return proc, report, score_rows(report, state, changed)

    phase_keys = set()
    replicate_parameters, replicate_inputs, quality = 0, 0, {}
    state_keys = ("index", "source_id", "version", "active", "value")
    for seed in (731, 732, 733):
        seed_root = run / f"seed-{seed}"
        state = [{**copy.deepcopy(row), "active": True} for row in source_rows]
        checkpoint = run / "inputs" / f"seed-{seed}"
        initial_manifest = load(checkpoint / "manifest.json")
        initial_digest = initial_manifest["training_history"][0]["initial_parameter_sha256"]
        previous_read, _, initial_quality = read_check(seed_root, checkpoint, state, [], "initial-read")
        check("initial_quality:" + str(seed), all(initial_quality[arm]["active"] == {"count": 8, "correct": 8}
                                                 for arm in ("parameter", "exact_sql")))
        pending = None
        for stage in range(1, 65):
            cycle = by_cycle[(seed, stage)]
            changed = sorted({stage % 8} | ({pending} if pending is not None else set()))
            reentered, pending = pending, None
            for entity in changed:
                row = state[entity]
                row["version"] += 1
                row["active"] = True
                row["value"] = [2 + (5 * stage + 3 * entity + seed % 7) % 12,
                                1 + (stage + entity) % 7, 8 + (3 * stage + entity) % 8]
                row["source_id"] = sha(canonical(["hepta.adapter.longrun.source.v1", seed, entity, row["version"], stage]))
            modes = ["update", "rebuild"] if stage % 8 == 0 else ["update"]
            expected_paths = [f"seed-{seed}/stage-{stage:03d}/{mode}/RESULT.json" for mode in modes]
            check(f"cycle_phase_order:{seed}:{stage}", cycle["phase_count"] == len(modes) and cycle["phase_paths"] == expected_paths)
            for mode in modes:
                label = f"{seed}:{stage}:{mode}"
                key = (seed, stage, mode)
                if key in phase_keys:
                    raise ValueError("Duplicate completed phase")
                phase_keys.add(key)
                phase_root = seed_root / f"stage-{stage:03d}" / mode
                record = load(phase_root / "RESULT.json")
                deleted = None
                if mode == "rebuild":
                    deleted = (stage // 8) % 8
                    pending = deleted
                    state[deleted]["active"] = False
                check("phase_metadata:" + label,
                      (record["seed"], record["stage"], record["mode"], record["changed_entities"], record["reentered_entity"], record["deleted_entity"])
                      == (seed, stage, mode, changed, reentered, deleted))
                check("independent_source_schedule:" + label, state == load(phase_root / "source-state.json"))
                check("phase_sqlite_truth:" + label,
                      sql_state(phase_root / "sources.sqlite") == [{k: row[k] for k in state_keys} for row in state])
                rows = [{k: row[k] for k in ("kind", "index", "source_id", "version", "value")} for row in state if row["active"]]
                request = load(phase_root / "fit.request.json")
                check("fit_input_paths:" + label, request["seed"] == seed and request["stage"] == stage
                      and request["mode"] == mode and request["protocol_sha256"] == protocol_sha
                      and Path(request["checkpoint"]) == checkpoint and Path(request["output"]) == phase_root / "checkpoint")
                check("all_and_only_active_replay:" + label, load(Path(request["source_rows_path"])) == rows
                      == load(phase_root / "active-train-sources.json"))
                fit_process = process(phase_root / "fit")
                fit = load(phase_root / "fit.stdout")
                training = fit["training"]
                check("fit_after_prior_reader_exit:" + label, fit_process["started_ns"] > previous_read["exited_ns"])
                check("fixed_fit_receipt:" + label,
                      (training["steps"], training["batch_size"], training["lr"], training["updated_head"], training["seed"], training["sample_presentations"])
                      == (600, 32, 0.01, True, seed + stage, 19200))
                bits = np.asarray([[(value >> bit) & 1 for value in row["value"] for bit in range(4)] for row in rows], dtype=np.float32)
                indexes, source_ids = [row["index"] for row in rows], [row["source_id"] for row in rows]
                check("fit_feature_target_source_binding:" + label,
                      training["features_sha256"] == sha(features[indexes].astype("<f4").tobytes())
                      and training["targets_sha256"] == {"bits": sha(bits.tobytes())}
                      and training["source_ids_sha256"] == sha(canonical(source_ids))
                      and training["available_rows"] == training["unique_rows_seen"] == len(rows))
                expected_start = load(checkpoint / "manifest.json")["parameter_sha256"] if mode == "update" else initial_digest
                check("update_or_reinitialize_chain:" + label, training["initial_parameter_sha256"] == expected_start
                      and fit["loaded_previous_parameters"] == (mode == "update"))
                probe = load(phase_root / "preflight.json")
                expected_probe_entities = [deleted] if mode == "rebuild" else changed
                check("source_refusal_before_model_read:" + label,
                      probe["passed"] and probe["model_reads"]["calls"] == 0
                      and [row["entity"] for row in probe["rows"]] == expected_probe_entities
                      and all(row["result"]["status"] == ("revoked" if mode == "rebuild" else "stale_source") for row in probe["rows"]))
                checkpoint = phase_root / "checkpoint"
                manifest = load(checkpoint / "manifest.json")
                check("saved_checkpoint_parameter_identity:" + label,
                      fit["parameter_sha256"] == training["final_parameter_sha256"] == manifest["parameter_sha256"]
                      and sorted(source_ids) == manifest["source_ids"])
                for spec in manifest["tensors"].values():
                    for part in spec["parts"]:
                        check("tensor_blob:" + label + ":" + part["file"],
                              identity(checkpoint / part["file"]) == {"bytes": part["bytes"], "sha256": part["sha256"]})
                previous_read, readout, quality = read_check(phase_root, checkpoint, state, changed)
                check("fresh_reader_after_trainer_exit:" + label, previous_read["started_ns"] > fit_process["exited_ns"]
                      and previous_read["pid"] != fit_process["pid"])
                check("phase_quality_independent_recalculation:" + label, quality == record["quality"])
                check("phase_model_binding:" + label, record["model"]["parameter_sha256"] == manifest["parameter_sha256"]
                      and run / record["model"]["checkpoint"] == checkpoint)
                reference_fit = load(prior_phases[key] / "fit.stdout")
                reference_training = reference_fit["training"]
                input_equal = all(training[name] == reference_training[name] for name in (
                    "features_sha256", "targets_sha256", "source_ids_sha256", "sample_schedule_sha256", "seed", "steps", "batch_size", "lr"))
                check("replication_training_inputs_equal:" + label, input_equal)
                replicate_inputs += int(input_equal)
                parameter_equal = fit["parameter_sha256"] == reference_fit["parameter_sha256"]
                replicate_parameters += int(parameter_equal)
                phase_records.append({"seed": seed, "stage": stage, "mode": mode, "quality": quality,
                                      "parameter_sha256": manifest["parameter_sha256"],
                                      "prior_run_parameter_sha_equal": parameter_equal,
                                      "prior_run_training_inputs_equal": input_equal})
            check(f"cycle_final_phase_binding:{seed}:{stage}", cycle["quality"] == quality
                  and cycle["final_model"]["parameter_sha256"] == manifest["parameter_sha256"])
            state_identities[f"{seed}:{stage}"] = {"source_state_sha256": sha(canonical(state)),
                                                   "active_entities": [row["index"] for row in state if row["active"]]}
        check("final_source_database:" + str(seed), sql_state(seed_root / "owner.sqlite")
              == [{k: row[k] for k in state_keys} for row in state])

    modes = Counter(mode for _, _, mode in phase_keys)
    check("full_phase_inventory", len(phase_keys) == 216 and modes == {"update": 192, "rebuild": 24})
    inventory = [load(path) for path in run.rglob("*.process.json")]
    inventory = [p for p in inventory if p.get("script") in ("fit_worker.py", "owner_read.py")]
    ordered = sorted(processes, key=lambda p: p["started_ns"])
    check("all_process_receipts_covered", len(processes) == len(inventory) == 435
          and ordered == sorted(inventory, key=lambda p: p["started_ns"]))
    check("all_processes_serial", all(a["exited_ns"] < b["started_ns"] for a, b in zip(ordered, ordered[1:])))
    aggregate = {arm: {group: {"correct": 0, "count": 0} for group in ("active", "retention", "changed", "revoked")}
                 for arm in ("parameter", "exact_sql")}
    for cycle in cycles:
        for arm, groups in cycle["quality"].items():
            for group, counts in groups.items():
                for key, value in counts.items():
                    aggregate[arm][group][key] += value
    check("final_aggregate", aggregate == summary["final_cycle_aggregate"])
    check("final_horizon_counts", summary["completed_cycles"] == 192 and summary["phase_count"] == 216
          and summary["update_fits_attempted"] == 192 and summary["rebuild_fits_attempted"] == 24
          and summary["all_steps_retained"])
    check("final_runtime_outcome", not summary["failures"] and summary["all_preflight_passed"]
          and summary["all_readers_after_trainer_exit"] and not summary["held_inputs_opened"]
          and not summary["native_runtime_executed"])
    cost = summary["cost"]
    for field, script in (("children_cpu_seconds_including_failures", None), ("training_children_cpu_seconds", "fit_worker.py"),
                          ("reader_children_cpu_seconds", "owner_read.py")):
        expected = sum(p["cpu_seconds"] for p in processes if script is None or p["script"] == script)
        check("cpu_accounting:" + field, abs(expected - cost[field]) < 0.000001)
    check("child_wall_accounting", sum(p["wall_ns"] for p in processes) == cost["children_wall_ns_including_failures"])
    check("child_io_accounting", sum(p["kernel_output_blocks"] for p in processes) == cost["kernel_output_blocks_children"])
    checkpoints = list(run.glob("seed-*/stage-*/**/checkpoint"))
    check("checkpoint_storage", sum(file_bytes(path) for path in checkpoints) == cost["retained_fitted_checkpoint_bytes"])
    check("initial_checkpoint_storage", sum(file_bytes(run / "inputs" / f"seed-{seed}") for seed in (731, 732, 733))
          == cost["initial_checkpoint_copies_bytes"])
    check("source_storage", sum(path.stat().st_size for path in run.glob("seed-*/owner.sqlite")) == cost["current_source_sqlite_bytes"]
          and sum(path.stat().st_size for path in run.rglob("sources.sqlite")) == cost["historical_source_sqlite_snapshot_bytes"])
    check("explicit_source_json_storage", sum(path.stat().st_size for path in run.rglob("*sources.json"))
          + sum(path.stat().st_size for path in run.rglob("source-state.json")) == cost["retained_explicit_source_json_bytes"])
    check("shared_encoder_and_features", cost["shared_encoder_reference_bytes"] == encoder["base_bytes"]
          and cost["canonical_features_bytes"] == (run / "inputs/canonical.npz").stat().st_size)
    check("clean_monitor_scope", resource["roots"] == [str(run)]
          and any(str(value).endswith("/manager.py") for value in resource["command"])
          and not any(str(value).endswith("/resume.py") for value in resource["command"]))
    resource_audit = audit_resource_samples(run / "resource-samples.jsonl", resource, check, run.name, True)
    check("one_uninterrupted_monitor_window", resource["termination_signal"] is None and resource["monitor_error"] is None
          and resource["launch_error"] is None and not resource["timed_out_or_sample_cap"])
    for name, expected in freeze["source_files"].items():
        check("frozen_source_still_unchanged:" + name, identity(Path(name)) == expected)
    return {
        "schema": "hepta.memory.clean-longrun-independent-audit.v1", "run_root": str(run),
        "audit_started_ns": began, "audit_finished_ns": time.monotonic_ns(),
        "passed": all(checks.values()), "check_count": len(checks),
        "failed_checks": [name for name, okay in checks.items() if not okay], "checks": checks,
        "read_only_evidence": True, "training_or_inference_executed": False,
        "protocol_sha256": protocol_sha, "completed_cycles": 192, "completed_fit_phases": 216,
        "completed_update_fits": modes["update"], "completed_rebuild_fits": modes["rebuild"],
        "completed_steps": 129600, "completed_sample_presentations": 4147200,
        "completed_child_process_count": len(processes), "final_cycle_aggregate": aggregate,
        "phase_records": phase_records, "cycle_source_state_identities": state_identities,
        "replication": {"same_training_input_and_schedule_phases": replicate_inputs,
                        "identical_parameter_phases": replicate_parameters, "phase_count": 216,
                        "independent_statistical_sample_claimed": False},
        "cost": cost, "resource_sample_audit": resource_audit,
        "resource_kernel_child_exit_rusage": resource["child_exit_rusage"],
        "resource_monitor_rusage_before_final_receipt": resource["monitor_rusage_before_final_receipt"],
        "resource_full_cost_exact": resource["full_cost_exact"],
        "final_artifact_identities": {name: identity(run / name) for name in ("FREEZE.json", "RESULT.json", "CYCLES.json", "resource.json")},
        "limitations": [
            "This clean replication has a complete monitor lifecycle and is a separate additional experiment. It does not reconstruct missing work from the earlier interrupted attempt.",
            "Memory/storage integrals remain sampled estimates with recorded missing intervals, sequential snapshot effects and a post-final-sample serialization/exit tail.",
            "Kernel wait4 command usage and summed child receipts overlap; they are reported separately and must not be added together.",
            "The same eight canonical addresses, deterministic targets, initialization and sampling schedules are repeated; this is not an independent statistical generalization sample.",
            "Exact-SQL and parameter arms run sequentially in shared reader processes. Arm slices are not independent deployment latencies.",
            "Historical checkpoints and explicit source snapshots remain stored; revocation and clean rebuild do not prove physical erasure of archives.",
            "All active records are replayed at each update. Capacity growth, one-shot learning, discarded-source operation and a general memory system are not demonstrated.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.run_root.resolve()):
        raise ValueError("Write audit outside the run evidence")
    result = audit(args.run_root.resolve())
    write_bounded_report(args.output, result)
    print(json.dumps({key: result[key] for key in ("passed", "check_count", "failed_checks", "completed_cycles", "replication")}))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
