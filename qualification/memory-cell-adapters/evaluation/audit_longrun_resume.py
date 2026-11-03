"""Independently inspect a completed-prefix snapshot of the live longrun.

No study module imports, training, inference, SQLite writes, or mutations of
the two run trees. A CYCLE file defines the observed completion boundary.
"""

import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import time

import numpy as np


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": sha(raw)}


def load(path):
    return json.loads(path.read_bytes())


def tree_identity(root):
    rows = [(str(path.relative_to(root)), identity(path)) for path in sorted(root.rglob("*")) if path.is_file()]
    return {"sha256": sha(canonical(rows)), "files": len(rows), "bytes": sum(row[1]["bytes"] for row in rows)}


def sql_state(path):
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        records = connection.execute(
            "SELECT idx,identity,version,active,payload FROM sources WHERE kind='semantic' ORDER BY idx").fetchall()
        return [{"index": row[0], "source_id": row[1], "version": row[2],
                 "active": bool(row[3]), "value": json.loads(row[4])} for row in records]
    finally:
        connection.close()


def score_rows(report, state, changed):
    output = {}
    for arm in report["arms"]:
        groups = {key: {"correct": 0, "count": 0} for key in ("active", "retention", "changed", "revoked")}
        by_index = {row["entity"]: row["result"] for row in arm["rows"]}
        if len(by_index) != 8 or set(by_index) != set(range(8)):
            raise ValueError("Fresh reader entity inventory mismatch")
        for row in state:
            actual = by_index[row["index"]]
            correct = actual["status"] == ("read" if row["active"] else "revoked")
            correct &= actual["value"] == (row["value"] if row["active"] else None)
            names = ["active" if row["active"] else "revoked"]
            if row["active"]:
                names.append("changed" if row["index"] in changed else "retention")
            for name in names:
                groups[name]["count"] += 1
                groups[name]["correct"] += int(correct)
        output[arm["arm"]] = groups
    return output


def audit_resource_samples(path, receipt, check, label, completed):
    """Recompute inter-sample integrals without importing the monitor."""
    names = ("tree_rss_bytes", "tree_pss_bytes", "storage_logical_bytes", "storage_allocated_bytes")
    totals = {name: {"observed_interval_ns": 0, "unobserved_interval_ns": 0,
                     "trapezoid_numerator_byte_ns": 0} for name in names}
    peaks = dict.fromkeys(names, None)
    previous, first, count, errors, max_gap = None, None, 0, 0, 0
    with path.open("rb") as stream:
        for line in stream:
            current = json.loads(line)
            count += 1
            if first is None:
                first = current
            metrics = current["metrics"]
            valid = not current["process_errors"]
            expected = {
                "tree_rss_bytes": sum(p["rss_bytes"] for p in current["processes"]) if valid else None,
                "tree_pss_bytes": sum(p["pss_bytes"] for p in current["processes"]) if valid else None,
                "storage_logical_bytes": current["storage"]["logical_bytes"],
                "storage_allocated_bytes": current["storage"]["allocated_bytes"],
            }
            if metrics != expected:
                raise ValueError("Sample metrics differ from raw observations: " + label)
            errors += len(current["process_errors"]) + current["storage"]["error_count"]
            for name in names:
                if metrics[name] is not None:
                    peaks[name] = metrics[name] if peaks[name] is None else max(peaks[name], metrics[name])
            if previous is not None:
                gap = current["monotonic_ns"] - previous["monotonic_ns"]
                if gap <= 0:
                    raise ValueError("Nonmonotone sample clock: " + label)
                max_gap = max(max_gap, gap)
                for name in names:
                    left, right = previous["metrics"][name], metrics[name]
                    if left is None or right is None:
                        totals[name]["unobserved_interval_ns"] += gap
                    else:
                        totals[name]["observed_interval_ns"] += gap
                        totals[name]["trapezoid_numerator_byte_ns"] += (left + right) * gap
            previous = current
    check("resource_sample_count:" + label, count == receipt["sample_count"])
    check("resource_sample_errors:" + label, errors == receipt["sample_error_count"])
    pre_gap = first["monotonic_ns"] - receipt["started_monotonic_ns"]
    post_gap = receipt["observations_ended_monotonic_ns"] - previous["monotonic_ns"] if completed else None
    for name in names:
        if completed:
            totals[name]["unobserved_interval_ns"] += pre_gap + post_gap
        totals[name]["sampled_byte_ns_estimate"] = (totals[name]["trapezoid_numerator_byte_ns"] // 2
                                                    if totals[name]["observed_interval_ns"] else None)
        check("resource_integral:" + label + ":" + name,
              all(value == receipt["integrals"][name][key] for key, value in totals[name].items())
              and receipt["integrals"][name]["exact_continuous_integral"] is False)
    expected_peaks = receipt["peaks_of_sequential_sample_sums"] if completed else receipt["observed_peaks"]
    check("resource_observed_peaks:" + label, peaks == expected_peaks)
    if completed:
        check("resource_sample_identity:" + label,
              identity(path) == {key: receipt["samples"][key] for key in ("bytes", "sha256")})
        check("resource_window_coverage:" + label,
              all(t["observed_interval_ns"] + t["unobserved_interval_ns"] == receipt["wall_ns_through_observation_close"]
                  for t in totals.values()))
        check("resource_gaps:" + label, receipt["sampling_gaps"]["before_first_sample_ns"] == pre_gap
              and receipt["sampling_gaps"]["after_last_sample_ns"] == post_gap
              and receipt["maximum_observed_gap_ns"] == max_gap)
        check("resource_completion:" + label,
              receipt["passed"] and receipt["exit_code"] == 0 and not receipt["timed_out_or_sample_cap"]
              and receipt["child_exit_rusage"] is not None and receipt["cleanup"]["observed_tree_stopped"]
              and not receipt["full_cost_exact"])
        for stream in ("stdout", "stderr"):
            check("resource_stream_identity:" + label + ":" + stream,
                  identity(Path(receipt[stream]["path"])) == {key: receipt[stream][key] for key in ("bytes", "sha256")})
    return {"sample_count": count, "sample_errors": errors, "peaks": peaks, "integrals": totals,
            "first_sample_ns": first["monotonic_ns"], "last_sample_ns": previous["monotonic_ns"],
            "before_first_sample_ns": pre_gap, "after_last_sample_ns": post_gap,
            "maximum_observed_gap_ns": max_gap,
            "integral_boundary": "Includes pre/post sample gaps as unknown" if completed else
                                 "Recorded interrupted integrals cover inter-sample spans only; pre-sample gap and tail are separate"}


def write_bounded_report(path, report):
    """Publish a small index and independently hashed parts below 400 kB."""
    output = dict(report)
    sections = {name: output.pop(name) for name in ("checks", "phase_records", "cycle_source_state_identities")}
    output["detail_parts"] = {}
    for name, values in sections.items():
        entries = list(values.items()) if isinstance(values, dict) else values
        batches = [entries[start:start + 500] for start in range(0, len(entries), 500)]
        inventory = []
        for number, batch in enumerate(batches):
            part = path.with_name(f"{path.stem}.{name}.{number:03d}.json")
            body = {"schema": "hepta.memory.audit-detail-part.v1", "section": name, "part": number,
                    "records": dict(batch) if isinstance(values, dict) else batch}
            raw = (json.dumps(body, sort_keys=True, indent=2) + "\n").encode()
            if len(raw) >= 400000:
                raise ValueError("Audit detail part exceeds byte limit")
            part.write_bytes(raw)
            inventory.append({"file": part.name, "records": len(batch), "bytes": len(raw), "sha256": sha(raw)})
        output["detail_parts"][name] = inventory
    raw = (json.dumps(output, sort_keys=True, indent=2) + "\n").encode()
    if len(raw) >= 400000:
        raise ValueError("Audit summary exceeds byte limit")
    path.write_bytes(raw)


def audit(root, require_complete=False):
    began = time.monotonic_ns()
    checks, phase_summaries, process_records = {}, [], []

    def check(name, okay):
        if name in checks:
            raise ValueError("Duplicate check " + name)
        checks[name] = bool(okay)

    old, resumed = root / "run-01", root / "run-02-resume"
    original_freeze, resume_freeze = load(old / "FREEZE.json"), load(resumed / "FREEZE.json")
    plan, protocol = load(root / "RESUME_PLAN.json"), load(root / "LONGRUN_PROTOCOL.json")
    protocol_sha = sha((root / "LONGRUN_PROTOCOL.json").read_bytes())
    old_tree_before = tree_identity(old)
    check("old_tree_matches_prefreeze_identity", old_tree_before == resume_freeze["original_tree_before_resume"])
    check("protocol_pin", protocol_sha == plan["original_protocol_sha256"] == original_freeze["protocol_sha256"]
          == resume_freeze["protocol_sha256"] == (root / "LONGRUN_PROTOCOL.sha256").read_text().strip())
    check("fixed_budget", {key: protocol["fit"][key] for key in ("steps", "batch_size", "lr", "train_head")}
          == {"steps": 600, "batch_size": 32, "lr": 0.01, "train_head": True})
    for freeze_name, freeze in (("old", original_freeze), ("resume", resume_freeze)):
        for name, expected in freeze["source_files"].items():
            check("frozen_source:" + freeze_name + ":" + name, identity(Path(name)) == expected)
    check("original_freeze_binding", identity(old / "FREEZE.json") == resume_freeze["original_freeze"])
    check("resume_plan_binding", sha((root / "RESUME_PLAN.json").read_bytes()) == resume_freeze["resume_plan_sha256"])
    for name, expected in original_freeze["input_files"].items():
        check("initial_input:" + name, identity(old / "inputs" / name) == expected)

    interruption, resource = load(old / "INFRA_INTERRUPTION.json"), load(old / "RESOURCE_INTERRUPTED.json")
    check("unknown_interruption_work_not_zero", all(interruption[key] is None for key in
          ("failed_attempt_cpu_seconds", "failed_attempt_exit_status", "failed_attempt_steps")))
    check("unknown_resource_tail_not_zero", resource["unobserved_tail_ns"] is None
          and resource["child_exit_rusage"] is None and resource["monitor_final_rusage"] is None
          and resource["full_cost_exact"] is False)
    check("old_resource_samples_pinned", identity(old / "resource-samples.jsonl")
          == {"bytes": resource["sample_bytes"], "sha256": resource["sample_sha256"]})
    resource_audits = {"interrupted": audit_resource_samples(old / "resource-samples.jsonl", resource, check, "run-01", False)}
    with (resumed / "resource-samples.jsonl").open() as stream:
        first_resume_sample = json.loads(stream.readline())
    gap_ns = first_resume_sample["monotonic_ns"] - resource["last_sample_ns"]
    check("resume_resource_after_interruption", gap_ns > 0)

    pending_root = old / "seed-732/stage-016/rebuild"
    pending = load(pending_root / "fit.request.json")
    resumed_first = resumed / "seed-732/stage-016/rebuild"
    first_request = load(resumed_first / "fit.request.json")
    changed_fields = sorted(key for key in set(pending) | set(first_request) if pending.get(key) != first_request.get(key))
    check("resume_only_output_path_relocated", changed_fields == ["output"])
    check("pending_request_identity", sha((pending_root / "fit.request.json").read_bytes())
          == resume_freeze["pending_fit_request_sha256"])
    check("old_partial_rebuild_not_claimed_complete",
          not any((pending_root / name).exists() for name in ("checkpoint", "fit.stdout", "fit.process.json", "RESULT.json")))
    check("completed_update_not_rerun", not (resumed / "seed-732/stage-016/update").exists())
    check("resumed_source_json_unchanged", (pending_root / "source-state.json").read_bytes()
          == (resumed_first / "source-state.json").read_bytes())
    check("resumed_training_rows_unchanged", (pending_root / "active-train-sources.json").read_bytes()
          == (resumed_first / "active-train-sources.json").read_bytes())
    state_keys = ("index", "source_id", "version", "active", "value")
    pending_state = [{key: row[key] for key in state_keys} for row in load(pending_root / "source-state.json")]
    check("interrupted_sql_state_binding", sql_state(pending_root / "sources.sqlite")
          == sql_state(old / "seed-732/owner.sqlite") == sql_state(resumed_first / "sources.sqlite") == pending_state)

    # Capture paths once: later live progress is deliberately outside this report.
    old_cycles = sorted(old.glob("seed-*/stage-*/CYCLE.json"))
    new_cycles = sorted(resumed.glob("seed-*/stage-*/CYCLE.json"))
    cycle_paths = old_cycles + new_cycles
    cycles = [(path, load(path)) for path in cycle_paths]
    cycle_map = {(row["seed"], row["stage"]): (path, row) for path, row in cycles}
    check("cycle_inventory_no_duplicate_keys", len(cycle_map) == len(cycles))
    check("old_completed_cycle_count", len(old_cycles) == interruption["completed_cycles"] == 79)
    old_phase_paths = sorted(old.glob("seed-*/stage-*/*/RESULT.json"))
    old_modes = Counter(load(path)["mode"] for path in old_phase_paths)
    check("old_completed_phases", len(old_phase_paths) == interruption["completed_fit_read_phases"] == 89
          and old_modes == {"update": 80, "rebuild": 9})
    check("resume_remaining_plan_count", plan["remaining_full_cycles"] == 192 - 79
          and plan["remaining_successful_fits_expected"] == 216 - 89)
    initial_sources = [row for row in load(old / "inputs/sources.json") if row["kind"] == "semantic"]
    with np.load(old / "inputs/canonical.npz", allow_pickle=False) as arrays:
        semantic_features = arrays["semantic"].copy()
    phase_keys, active_targets, snapshot_seeds = set(), {}, {}

    def verify_process(stem):
        receipt = load(stem.with_suffix(".process.json"))
        label = str(stem.relative_to(root))
        check("completed_process:" + label, receipt["exit_code"] == 0 and receipt["passed"] and not receipt["timed_out"])
        for name in ("request", "stdout", "stderr"):
            suffix = ".request.json" if name == "request" else "." + name
            check("process_blob:" + label + ":" + name, identity(stem.with_suffix(suffix)) == receipt[name])
        check("process_wall:" + label, receipt["exited_ns"] - receipt["started_ns"] == receipt["wall_ns"])
        process_records.append(receipt)
        return receipt

    for seed in (731, 732, 733):
        stages = sorted(stage for observed_seed, stage in cycle_map if observed_seed == seed)
        if not stages:
            continue
        snapshot_seeds[str(seed)] = max(stages)
        check("cycle_prefix:" + str(seed), stages == list(range(1, max(stages) + 1)))
        state = [{**copy.deepcopy(row), "active": True} for row in initial_sources]
        previous_checkpoint = old / "inputs" / f"seed-{seed}"
        initial_manifest = load(previous_checkpoint / "manifest.json")
        initial_parameter_sha = initial_manifest["training_history"][0]["initial_parameter_sha256"]
        initial_paths = [run / f"seed-{seed}" / "initial-read" for run in (old, resumed)
                         if (run / f"seed-{seed}" / "initial-read.process.json").exists()]
        check("one_initial_read:" + str(seed), len(initial_paths) == 1)
        initial_process = verify_process(initial_paths[0])
        initial_read = load(initial_paths[0].with_suffix(".stdout"))
        initial_quality = score_rows(initial_read, state, [])
        check("initial_read_quality:" + str(seed), all(initial_quality[arm]["active"] == {"correct": 8, "count": 8}
                                                    for arm in ("parameter", "exact_sql")))
        check("initial_read_parameter_binding:" + str(seed), initial_read["parameter_sha256"] == initial_manifest["parameter_sha256"])
        pending_entity, previous_read_exit = None, initial_process["exited_ns"]
        for stage in stages:
            cycle_path, cycle = cycle_map[(seed, stage)]
            modes = ["update", "rebuild"] if stage % 8 == 0 else ["update"]
            changed = sorted({stage % 8} | ({pending_entity} if pending_entity is not None else set()))
            reentered, pending_entity = pending_entity, None
            for entity in changed:
                row = state[entity]
                row["version"] += 1
                row["active"] = True
                row["value"] = [2 + (5 * stage + 3 * entity + seed % 7) % 12,
                                1 + (stage + entity) % 7, 8 + (3 * stage + entity) % 8]
                row["source_id"] = sha(canonical(["hepta.adapter.longrun.source.v1", seed, entity, row["version"], stage]))
            phase_paths = [Path(name) if Path(name).is_absolute() else old / name for name in cycle["phase_paths"]]
            check(f"cycle_phase_inventory:{seed}:{stage}", len(phase_paths) == cycle["phase_count"] == len(modes)
                  and [path.parent.name for path in phase_paths] == modes)
            for mode, phase_path in zip(modes, phase_paths, strict=True):
                key = (seed, stage, mode)
                if key in phase_keys:
                    raise ValueError("Phase appears twice in completed cycle inventory")
                phase_keys.add(key)
                phase_root = phase_path.parent
                record, frame = load(phase_path), load(phase_root / "fit.request.json")
                deleted = None
                if mode == "rebuild":
                    deleted = (stage // 8) % 8
                    state[deleted]["active"] = False
                    pending_entity = deleted
                label = f"{seed}:{stage}:{mode}"
                check("phase_metadata:" + label,
                      (record["seed"], record["stage"], record["mode"], record["changed_entities"], record["reentered_entity"], record["deleted_entity"])
                      == (seed, stage, mode, changed, reentered, deleted))
                check("independent_source_state:" + label, load(phase_root / "source-state.json") == state)
                check("phase_sql_state:" + label,
                      sql_state(phase_root / "sources.sqlite") == [{k: r[k] for k in state_keys} for r in state])
                train_rows = [{k: r[k] for k in ("kind", "index", "source_id", "version", "value")} for r in state if r["active"]]
                check("phase_active_training_rows:" + label,
                      load(phase_root / "active-train-sources.json") == load(Path(frame["source_rows_path"])) == train_rows)
                check("parameter_checkpoint_chain:" + label, Path(frame["checkpoint"]) == previous_checkpoint)
                check("phase_request_contract:" + label,
                      frame["mode"] == mode and frame["seed"] == seed and frame["stage"] == stage
                      and frame["protocol_sha256"] == protocol_sha and Path(frame["output"]) == phase_root / "checkpoint")
                fit_process, read_process = verify_process(phase_root / "fit"), verify_process(phase_root / "read")
                check("fresh_reader_after_fit:" + label, read_process["started_ns"] > fit_process["exited_ns"]
                      and read_process["pid"] != fit_process["pid"])
                if previous_read_exit is not None:
                    check("serial_training_and_readers:" + label, fit_process["started_ns"] > previous_read_exit)
                previous_read_exit = read_process["exited_ns"]
                fitted, readout = load(phase_root / "fit.stdout"), load(phase_root / "read.stdout")
                receipt = fitted["training"]
                check("fixed_training_receipt:" + label,
                      (receipt["steps"], receipt["batch_size"], receipt["lr"], receipt["updated_head"], receipt["seed"], receipt["sample_presentations"])
                      == (600, 32, 0.01, True, seed + stage, 19200))
                bits = np.asarray([[(v >> bit) & 1 for v in row["value"] for bit in range(4)] for row in train_rows], dtype=np.float32)
                indexes, source_ids = [r["index"] for r in train_rows], [r["source_id"] for r in train_rows]
                check("training_input_target_digest:" + label,
                      receipt["features_sha256"] == sha(semantic_features[indexes].astype("<f4").tobytes())
                      and receipt["targets_sha256"] == {"bits": sha(bits.tobytes())}
                      and receipt["source_ids_sha256"] == sha(canonical(source_ids))
                      and receipt["unique_rows_seen"] == receipt["available_rows"] == len(train_rows))
                checkpoint = phase_root / "checkpoint"
                manifest = load(checkpoint / "manifest.json")
                expected_start = load(previous_checkpoint / "manifest.json")["parameter_sha256"] if mode == "update" else initial_parameter_sha
                check("update_or_clean_rebuild_start:" + label,
                      fitted["loaded_previous_parameters"] == (mode == "update")
                      and receipt["initial_parameter_sha256"] == expected_start)
                check("checkpoint_and_reader_bindings:" + label,
                      fitted["parameter_sha256"] == receipt["final_parameter_sha256"] == manifest["parameter_sha256"]
                      == readout["parameter_sha256"] == record["model"]["parameter_sha256"]
                      and identity(checkpoint / "manifest.json")["sha256"] == readout["manifest_sha256"]
                      and sorted(source_ids) == manifest["source_ids"] == readout["source_ids"])
                for spec in manifest["tensors"].values():
                    for part in spec["parts"]:
                        check("checkpoint_blob:" + label + ":" + part["file"],
                              identity(checkpoint / part["file"]) == {"bytes": part["bytes"], "sha256": part["sha256"]})
                probe = load(phase_root / "preflight.json")
                check("preflight_blocks_before_prediction:" + label,
                      probe["passed"] and probe["model_reads"]["calls"] == 0
                      and all(row["result"]["status"] == ("revoked" if mode == "rebuild" else "stale_source") for row in probe["rows"]))
                independent_quality = score_rows(readout, state, changed)
                check("independent_quality_matches_phase:" + label, independent_quality == record["quality"])
                check("reader_parameter_source_guard:" + label,
                      all(arm["reads"]["explicit_values"] == 0 and arm["sql_audit"]["source_payload_column_authorizations"] == 0
                          for arm in readout["arms"] if arm["arm"] == "parameter"))
                check("reader_same_snapshot:" + label, len({arm["owner_snapshot_sha256"] for arm in readout["arms"]}) == 1)
                check("reader_target_blind_record:" + label,
                      not readout["training_modules_loaded"] and not readout["target_module_import_audit"]
                      and readout["gradient_steps"] == 0 and readout["native_runtime_executed"] is False)
                phase_summaries.append({"seed": seed, "stage": stage, "mode": mode,
                                        "path": str(phase_path.relative_to(root)), "quality": independent_quality,
                                        "parameter_sha256": manifest["parameter_sha256"]})
                previous_checkpoint = checkpoint
            check(f"cycle_uses_final_phase:{seed}:{stage}", cycle["quality"] == independent_quality
                  and cycle["final_model"]["parameter_sha256"] == manifest["parameter_sha256"])
            active_targets[f"{seed}:{stage}"] = {"active_entities": [r["index"] for r in state if r["active"]],
                                                  "source_state_sha256": sha(canonical(state))}

    interrupted_cycle = cycle_map[(732, 16)][1]
    check("interrupted_cycle_two_unique_segments", interrupted_cycle["phase_paths"] == [
        str(old / "seed-732/stage-016/update/RESULT.json"), str(resumed_first / "RESULT.json")]
        and interrupted_cycle["interrupted_cycle_wall_excludes_prior_segment"] is True)
    check("old_tree_still_immutable_after_audit", tree_identity(old) == old_tree_before)
    modes = Counter(mode for _, _, mode in phase_keys)
    expected_rebuilds = sum(stage % 8 == 0 for _, stage in cycle_map)
    check("completed_phase_count_no_duplicates_or_omissions",
          modes == {"update": len(cycles), "rebuild": expected_rebuilds})
    serial = sorted(process_records, key=lambda p: p["started_ns"])
    check("all_complete_phase_children_serial", all(a["exited_ns"] < b["started_ns"] for a, b in zip(serial, serial[1:])))
    aggregate = {arm: {g: {"correct": 0, "count": 0} for g in ("active", "retention", "changed", "revoked")}
                 for arm in ("parameter", "exact_sql")}
    for _, cycle in cycles:
        for arm, groups in cycle["quality"].items():
            for group, counts in groups.items():
                for name, value in counts.items():
                    aggregate[arm][group][name] += value
    final_summary_checks = {"required": require_complete, "available": False}
    if require_complete:
        final = load(resumed / "RESULT.json")
        final_cycles = load(resumed / "CYCLES.json")
        final_resource = load(resumed / "resource.json")
        check("full_horizon_unique_inventory", set(cycle_map) == {(seed, stage) for seed in (731, 732, 733) for stage in range(1, 65)}
              and len(cycles) == 192 and modes == {"update": 192, "rebuild": 24})
        check("full_horizon_summary_counts", final["completed_cycles"] == 192 and final["phase_count"] == 216
              and final["completed_update_fits"] == 192 and final["completed_rebuild_fits"] == 24
              and final["completed_fit_steps"] == 129600 and final["completed_sample_presentations"] == 4147200)
        check("full_horizon_cycle_inventory_file", final_cycles == sorted([row for _, row in cycles], key=lambda row: (row["seed"], row["stage"])))
        check("full_horizon_aggregate", final["final_cycle_aggregate"] == aggregate)
        check("interrupted_attempt_remains_explicit", final["infrastructure_interrupted_attempts"] == 1
              and final["interrupted_attempt_steps"] is None
              and final["cost"]["interrupted_child_cpu_seconds"] is None
              and final["cost"]["original_driver_final_cpu_seconds"] is None and not final["cost"]["full_cost_exact"])
        check("final_runtime_invariants", not final["new_failures"] and final["all_preflight_passed"]
              and final["all_trainers_and_readers_completed"] and final["all_readers_after_trainer_exit"]
              and final["original_evidence_unchanged"] and not final["held_inputs_opened"])
        process_inventory = [load(path) for run in (old, resumed) for path in run.rglob("*.process.json")]
        process_inventory = [p for p in process_inventory if p.get("script") in ("fit_worker.py", "owner_read.py")]
        check("all_child_cost_receipts_covered", len(process_records) == len(process_inventory) == 435
              and sorted(process_records, key=lambda p: p["started_ns"]) == sorted(process_inventory, key=lambda p: p["started_ns"]))
        for field, script in (("completed_children_cpu_seconds", None), ("training_children_cpu_seconds", "fit_worker.py"),
                              ("reader_children_cpu_seconds", "owner_read.py")):
            expected = sum(p["cpu_seconds"] for p in process_records if script is None or p["script"] == script)
            check("final_cpu_accounting:" + field, abs(expected - final["cost"][field]) < 0.000001)
        check("final_child_wall_accounting", sum(p["wall_ns"] for p in process_records) == final["cost"]["completed_children_wall_ns"])
        check("final_child_io_accounting", sum(p["kernel_output_blocks"] for p in process_records)
              == final["cost"]["kernel_output_blocks_completed_children"])
        checkpoints = [path for run in (old, resumed) for path in run.glob("seed-*/stage-*/**/checkpoint") if path.is_dir()]
        check("final_checkpoint_bytes", sum(p.stat().st_size for checkpoint in checkpoints for p in checkpoint.rglob("*") if p.is_file())
              == final["cost"]["fitted_checkpoint_bytes"])
        check("final_source_sqlite_bytes", sum(p.stat().st_size for run in (old, resumed) for p in run.rglob("*.sqlite"))
              == final["cost"]["source_sqlite_bytes_all_snapshots"])
        check("resume_monitor_registered_roots", set(final_resource["roots"]) == {str(old), str(resumed)})
        resource_audits["resumed"] = audit_resource_samples(resumed / "resource-samples.jsonl", final_resource, check, "run-02-resume", True)
        final_summary_checks = {"required": True, "available": True, "result_identity": identity(resumed / "RESULT.json"),
                                "cycles_identity": identity(resumed / "CYCLES.json"), "resource_identity": identity(resumed / "resource.json"),
                                "process_count": len(process_records), "cost": final["cost"]}
    return {
        "schema": "hepta.memory.longrun-resume-independent-audit.v1", "snapshot_started_ns": began,
        "snapshot_finished_ns": time.monotonic_ns(), "read_only_run_trees": True,
        "training_or_inference_executed": False, "passed": all(checks.values()),
        "check_count": len(checks), "failed_checks": [k for k, v in checks.items() if not v], "checks": checks,
        "protocol_sha256": protocol_sha, "old_tree_identity": old_tree_before,
        "first_resume_request_changed_fields": changed_fields,
        "old_complete_cycles": len(old_cycles), "resume_complete_cycles_in_snapshot": len(new_cycles),
        "combined_complete_cycles_in_snapshot": len(cycles), "completed_stage_by_seed": snapshot_seeds,
        "completed_phase_counts_in_snapshot": modes, "complete_phase_count": len(phase_keys),
        "completed_fit_steps": len(phase_keys) * 600, "completed_sample_presentations": len(phase_keys) * 19200,
        "final_cycle_quality_for_snapshot": aggregate, "phase_records": phase_summaries,
        "cycle_source_state_identities": active_targets,
        "full_horizon_verification": final_summary_checks, "resource_sample_audits": resource_audits,
        "cost_boundary": {"interrupted_attempt_steps": None, "interrupted_attempt_cpu_seconds": None,
                          "interrupted_attempt_exit_status": None, "unobserved_resource_tail_ns": None,
                          "between_monitored_sample_windows_ns": gap_ns, "gap_cpu_or_memory_cost": None,
                          "completed_children_including_initial_reads_cpu_seconds": sum(p["cpu_seconds"] for p in process_records),
                          "completed_children_including_initial_reads_wall_ns": sum(p["wall_ns"] for p in process_records),
                          "full_cost_exact": False},
        "limitations": [
            "All 192 completed cycles and final summary/resources were checked." if require_complete else
            "This is a snapshot of completed CYCLE records during an ongoing run; later phases are excluded.",
            "The failed infrastructure attempt is an additional incomplete attempt with unknown work, not zero work.",
            "The interrupted cycle duration in the resume file covers its resumed segment only, not the full wall-clock span.",
            "Recorded source authorization is not mathematical removal of old-source influence after an update; clean rebuild is a separate operation.",
            "The eight-address synthetic canonical maintenance workload does not test held language, autonomous topology, or generic long-term memory.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--longrun-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.longrun_root.resolve()):
        raise ValueError("Write audit outside frozen/live longrun trees")
    result = audit(args.longrun_root.resolve(), args.require_complete)
    write_bounded_report(args.output, result)
    print(json.dumps({k: result[k] for k in ("passed", "check_count", "failed_checks",
                      "combined_complete_cycles_in_snapshot", "completed_stage_by_seed", "completed_phase_counts_in_snapshot")}))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
