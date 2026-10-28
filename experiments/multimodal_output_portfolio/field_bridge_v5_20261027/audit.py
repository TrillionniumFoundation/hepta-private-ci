"""Independent artifact audit and descriptive V5 development comparisons.

No model is instantiated or evaluated. Checkpoints are read as tensor records;
all policy, transaction, endpoint and source identities must be present.
"""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re

import numpy as np

from ..field_bridge_v3_20261027.training_common import file_hash, object_hash, require, write_json
from ..field_bridge_v4_20261027_review.training_panel_origin import fit_origin, translate
from .calibration import decision, load_saved


HERE = Path(__file__).resolve().parent
V3 = HERE.parent / "field_bridge_v3_20261027"


def read_json(path):
    return json.loads(Path(path).read_text())


def identity(value):
    require(set(value) == {"parameters", "optimizer"}
            and all(re.fullmatch(r"[a-f0-9]{64}", item) for item in value.values()), "Invalid state identity")
    return value


def verify_stage(path):
    require(not (path / "FAILED.json").exists(), f"Failed stage: {path}")
    complete = read_json(path / "COMPLETE.json")
    actual = {str(item.relative_to(path)) for item in path.rglob("*")
              if item.is_file() and item != path / "COMPLETE.json"}
    require(actual == set(complete["files"]), f"Unsealed or missing stage files: {path}")
    for name, expected in complete["files"].items():
        item = (path / name).resolve()
        require(item.is_relative_to(path.resolve()) and file_hash(item) == expected, f"Stage hash mismatch: {item}")
    require(type(complete["completed_unix_ns"]) is int, "Missing stage sealing time")
    return complete


def read_trace(path, expected_head):
    rows, previous = [], None
    with gzip.open(path, "rt") as stream:
        for index, line in enumerate(stream):
            row = json.loads(line)
            require(row["record_index"] == index and row["previous_record_sha256"] == previous,
                    f"Broken trace chain at {path}:{index}")
            digest = object_hash({key: value for key, value in row.items() if key != "record_sha256"})
            require(digest == row["record_sha256"], f"Trace record hash mismatch: {path}:{index}")
            require(not rows or row["committed_monotonic_ns"] >= rows[-1]["committed_monotonic_ns"],
                    "Trace monotonic clock reversed")
            rows.append(row)
            previous = digest
    require(bool(rows) and previous == expected_head, "Trace head mismatch or empty trace")
    return rows


def checkpoint_identity(path, record, training):
    """Rehash stored tensors/state directly, without constructing a generator."""
    import torch

    require(file_hash(path) == record["checkpoint"]["file_sha256"], "Checkpoint file hash mismatch")
    saved = torch.load(path, map_location="cpu", weights_only=True)
    require(saved["schema"] == "hepta.field-bridge.v3.complete-adapter.1"
            and saved["training_configuration"] == training, "Checkpoint configuration changed")
    require(saved["metadata"] == record["checkpoint"]["metadata"], "Checkpoint metadata mismatch")
    for key in ("seed", "method", "schedule_id", "study_id"):
        require(saved["metadata"][key] == record[key], "Wrong checkpoint binding")
    tensors = saved["parameters"]
    require(set(tensors) == {name + suffix for name in training["adapter_modules"]
                            for suffix in (".up", ".down")}, "Incomplete adapter inventory")
    parameter_digest = hashlib.sha256()
    for name, value in tensors.items():
        require(torch.is_tensor(value) and value.ndim == 2 and torch.isfinite(value).all(), "Invalid adapter tensor")
        require(value.shape[0 if name.endswith(".down") else 1] == training["adapter_rank"], "Wrong adapter rank")
        parameter_digest.update(name.encode())
        parameter_digest.update(value.detach().cpu().contiguous().numpy().tobytes())
    optimizer = saved["optimizer"]
    require(len(optimizer["param_groups"]) == 1, "Unexpected optimizer groups")
    indices = optimizer["param_groups"][0]["params"]
    require(indices == list(range(len(tensors))), "Incomplete optimizer parameter inventory")
    require(not optimizer["state"] or set(optimizer["state"]) == set(indices), "Incomplete momentum inventory")
    optimizer_digest = hashlib.sha256(json.dumps(optimizer["param_groups"], sort_keys=True).encode())
    for index, fields in sorted(optimizer["state"].items()):
        require(set(fields) == {"momentum_buffer"}, "Unexpected SGD state")
        optimizer_digest.update(str(index).encode())
        for name, value in sorted(fields.items()):
            require(torch.is_tensor(value) and torch.isfinite(value).all(), "Invalid optimizer tensor")
            require(value.shape == list(tensors.values())[index].shape, "Momentum shape mismatch")
            optimizer_digest.update(name.encode())
            optimizer_digest.update(value.detach().cpu().contiguous().numpy().tobytes())
    observed = {"parameters": parameter_digest.hexdigest(), "optimizer": optimizer_digest.hexdigest()}
    require(observed == identity(saved["identity"])
            == {key: record["checkpoint"][key] for key in observed}, "Stored checkpoint state hash mismatch")
    require(record["state"] == record["checkpoint"], "Final path state mismatch")
    return observed, saved["frozen_base_sha256"]


def scheduled_rows(seed, schedule_id, start, end, training):
    return [{"step": step, "adapt_seed": seed * 100003 + training["batch_seed_offset"] + schedule_id * 1009 + step,
             "clean_seed": seed * 100003 + training["rehearsal_seed_offset"] + schedule_id * 1009 + step,
             "noise_seed": training["forward_seed_offset"] + step,
             "condition": training["conditions"][step % len(training["conditions"])]} for step in range(start, end)]


def audit_path(path, protocol, training, seed, method, schedule_id, fitted, origin, tau):
    record = read_json(path / "PATH.json")
    mode, grain = method.split("_")
    grain, interval, steps = int(grain), protocol["decision_interval"], protocol["physical_steps_per_path"]
    require(grain in protocol["transaction_grains"] and interval % grain == 0, "Invalid transaction grain")
    require((record["seed"], record["method"], record["schedule_id"], record["study_id"])
            == (seed, method, schedule_id, protocol["study_id"]), "Wrong path identity")
    require(record["final_step"] == steps and record["endpoint_access"] is False, "Incomplete or contaminated path")
    trace = read_trace(path / "trace.jsonl.gz", record["trace_head_sha256"])
    require(len(trace) == record["trace_records"], "Trace record count mismatch")
    rows = iter(trace)
    receipts, decisions, costs, previous, observed_initial = [], [], Counter(), None, None
    baseline = protocol["baseline_actions"][str(seed)]
    for step in range(0, steps, interval):
        selected = next(rows)
        require(selected["kind"] == "decision" and selected["step"] == step, "Missing macro decision")
        require(selected["baseline_action"] == baseline and selected["certificate"] is False, "Invalid gate baseline")
        if mode == "ordinary":
            require(selected["chosen"] == baseline and not selected["override"]
                    and selected["prediction_performed"] is False, "Ordinary policy changed")
        else:
            observed_initial = selected["raw"] if observed_initial is None else observed_initial
            mapped = translate(selected["raw"], observed_initial, origin)
            require(np.array_equal(mapped, selected["mapped"]), "Origin translation mismatch")
            replay = decision(fitted["controllers"][mode], mapped, baseline, tau)
            require(all(selected[key] == value for key, value in replay.items()), "Gate decision does not replay")
            feature = selected["feature_receipt"]
            require(feature["state_grad_rng_invariant"] is True, "Feature measurement mutated state")
            require(previous is None or feature["before"] == previous, "Feature state discontinuity")
            costs.update(feature["resources"])
        decisions.append({key: selected[key] for key in ("step", "chosen", "override")})
        for start in range(step, step + interval, grain):
            transaction_start = next(rows) if grain != interval else None
            entry = next(rows)
            require(entry["kind"] == "transaction" and entry["grain"] == grain, "Missing transaction receipt")
            receipt = entry["receipt"]
            require((receipt["start"], receipt["end"], receipt["action_index"], receipt["schedule_id"])
                    == (start, start + grain, selected["chosen"], schedule_id), "Transaction schedule mismatch")
            expected_schedule = object_hash(scheduled_rows(seed, schedule_id, start, start + grain, training))
            require(receipt["schedule_sha256"] == expected_schedule, "Microstep schedule changed")
            before, candidate, after = (identity(receipt[key]) for key in ("before", "candidate", "after"))
            require(previous is None or before == previous, "Transaction state chain broke")
            if mode != "ordinary" and start == step:
                require(before == selected["feature_receipt"]["before"], "Feature/transaction state mismatch")
            if transaction_start is not None:
                require(transaction_start["kind"] == "transaction_start"
                        and all(transaction_start[key] == receipt[key] for key in ("start", "end", "before", "schedule_sha256")),
                        "Transaction start does not bind its outcome")
            accepted = receipt["accepted"]
            require(type(accepted) is bool and np.isfinite(receipt["guard_delta"])
                    and accepted == (receipt["guard_delta"] >= training["guard_min_delta"]), "Guard decision mismatch")
            require(after == (candidate if accepted else before), "Rejected state not fully restored or accepted state lost")
            action = receipt["action_index"]
            require(receipt["multiplier"] == training["multipliers"][action]
                    and receipt["clock_advances_on_rejection"] is True, "Actuation/clock rule changed")
            require(action != 0 or before == candidate == after, "Zero action changed parameters or optimizer")
            for key in ("first_gradient", "last_gradient"):
                require(receipt[key]["optimizer_advanced"] == (action != 0)
                        and np.isfinite([receipt[key]["loss"], receipt[key]["unclipped_gradient_norm"]]).all(), "Bad gradient receipt")
            local = receipt["resources"]
            expected = {"scheduled_gradient_microsteps": grain, "gradient_backward_calls": grain,
                        "gradient_backward_examples": grain * (training["adapt_batch_size"] + training["rehearsal_batch_size"]),
                        "optimizer_steps": grain if action != 0 else 0, "transaction_snapshots": 1,
                        "accepted_blocks": int(accepted), "rejected_blocks": int(not accepted),
                        "discarded_gradient_microsteps": grain if not accepted else 0}
            require(all(local.get(key, 0) == value for key, value in expected.items()), "Transaction work counter mismatch")
            require(len(receipt["guard_values"]) == len(receipt["guard_output_sha256"]) > 0
                    and np.isfinite(receipt["guard_values"]).all(), "Missing guard evidence")
            costs.update(local)
            receipts.append(receipt)
            previous = after
    require(next(rows, None) is None, "Unexpected trailing trace records")
    require(decisions == record["decisions"] and len(receipts) == record["transactions"] == steps // grain,
            "Path summary does not match trace")
    accepted = sum(row["accepted"] for row in receipts)
    nonzero = sum(row["accepted"] and row["action_index"] != 0 for row in receipts)
    require(record["accepted"] == accepted and record["accepted_nonzero"] == nonzero, "Accepted counts mismatch")
    require(dict(sorted((key, value) for key, value in costs.items() if value)) == record["resources"], "Unaccounted path work")
    final, base = checkpoint_identity(path / "checkpoint.pt", record, training)
    require(final == previous, "Checkpoint differs from final transaction")
    require(record["cpu_ns"] > 0 and record["wall_ns"] > 0, "Missing measured path time")
    return {"seed": seed, "method": method, "schedule_id": schedule_id, "transactions": len(receipts),
            "accepted": accepted, "accepted_nonzero": nonzero,
            "accepted_parameter_changes": sum(row["accepted"] and row["before"]["parameters"] != row["after"]["parameters"] for row in receipts),
            "overrides": sum(row["override"] for row in decisions), "initial": receipts[0]["before"], "final": final,
            "frozen_base_sha256": base, "resources": dict(costs), "cpu_ns": record["cpu_ns"], "wall_ns": record["wall_ns"]}


def hard_output(path, panel):
    with np.load(path, allow_pickle=False) as archive:
        data = {key: archive[key] for key in archive.files}
    batches = panel["batches"]
    ids = np.asarray([source for batch in batches for source in batch["source_ids"]], dtype=str)
    conditions = np.asarray([batch["condition"] for batch in batches for _ in batch["source_ids"]])
    require(np.array_equal(data["source_ids"], ids) and np.array_equal(data["conditions"], conditions), "Unpaired endpoint sources")
    require(data["pixels_u8"].dtype == np.uint8 and len(data["pixels_u8"]) == len(ids)
            and data["captions_utf8"].shape == (len(ids),), "Missing hard output bytes")
    hashes = [hashlib.sha256(pixel.tobytes() + str(caption).encode()).hexdigest()
              for pixel, caption in zip(data["pixels_u8"], data["captions_utf8"], strict=True)]
    require(np.array_equal(hashes, data["output_sha256"]), "Hard output hashes do not match bytes")
    values = np.stack([data["values_" + observer] for observer in ("reward", "audit")])
    require(values.shape == (2, len(ids)) and np.isfinite(values).all(), "Invalid endpoint utilities")
    return values


def audit_endpoints(path, protocol):
    panels = read_json(path / "PANELS.json")
    require(set(panels) == {"task", "clean"}, "Missing endpoint panel")
    for panel in panels.values():
        require(panel["sha256"] == object_hash(panel["batches"])
                and panel["independent_of_schedule_id"] is True, "Invalid panel binding")
    with np.load(path / "ENDPOINTS.npz", allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    for key in ("methods", "schedules", "observers"):
        require(arrays[key].tolist() == protocol[key], "Endpoint axes changed: " + key)
    for endpoint, panel in panels.items():
        frozen = hard_output(path / ("original-" + endpoint + ".npz"), panel)
        require(np.array_equal(frozen, arrays["frozen_" + endpoint]), "Frozen endpoint array mismatch")
        expected_shape = (len(protocol["methods"]), len(protocol["schedules"]), *frozen.shape)
        require(arrays[endpoint].shape == expected_shape, "Incomplete endpoint census")
        for mi, method in enumerate(protocol["methods"]):
            for si, schedule in enumerate(protocol["schedules"]):
                values = hard_output(path / method / str(schedule) / (endpoint + ".npz"), panel)
                require(np.array_equal(values, arrays[endpoint][mi, si]), "Aggregate endpoint array mismatch")
    return arrays


def comparisons(protocol, endpoints, paths):
    means, costs = {}, {}
    for method in [*protocol["methods"], "frozen"]:
        means[method] = {}
        for endpoint in ("task", "clean"):
            means[method][endpoint] = np.stack([
                arrays["frozen_" + endpoint].mean(-1) if method == "frozen"
                else arrays[endpoint][protocol["methods"].index(method)].mean(axis=(0, 2))
                for arrays in endpoints])
        if method != "frozen":
            rows = [row for row in paths if row["method"] == method]
            total = Counter()
            for row in rows:
                total.update(row["resources"])
                total.update({"cpu_ns": row["cpu_ns"], "wall_ns": row["wall_ns"]})
            costs[method] = {"paths": len(rows), "total": dict(total),
                             "mean_per_path": {key: value / len(rows) for key, value in total.items()}}
    table = []
    for name in protocol["descriptive_comparisons"]:
        left, right = name.split("-")
        delta = {endpoint: means[left][endpoint] - means[right][endpoint] for endpoint in ("task", "clean")}
        table.append({"comparison": name,
                      "pooled": {endpoint: dict(zip(protocol["observers"], value.mean(0).tolist())) for endpoint, value in delta.items()},
                      "per_seed": {str(seed): {endpoint: dict(zip(protocol["observers"], value[index].tolist()))
                                               for endpoint, value in delta.items()} for index, seed in enumerate(protocol["seeds"])},
                      "positive_task_seed_counts": dict(zip(protocol["observers"], (delta["task"] > 0).sum(0).tolist())),
                      "mean_cost_delta": {key: costs[left]["mean_per_path"].get(key, 0) - costs[right]["mean_per_path"].get(key, 0)
                                          for key in sorted(set(costs[left]["total"]) | set(costs[right]["total"]))}})
    rule, gates = protocol["development_entry"], {}
    candidate = rule["candidate"]
    require(rule["all_paths_complete"] and rule["all_observers_required"]
            and not rule["passing_authorizes_new_holdout_automatically"], "Unknown development admission semantics")
    for observer_index, observer in enumerate(protocol["observers"]):
        frozen = means[candidate]["task"][:, observer_index] - means["frozen"]["task"][:, observer_index]
        gates[observer + "_frozen_each_model"] = bool((frozen >= rule["task_gain_over_frozen_each_model_min"]).all())
        gates[observer + "_frozen_pooled"] = bool(frozen.mean() >= rule["task_gain_over_frozen_pooled_min"])
        for control in ("ordinary", "richer"):
            matched = control + "_" + candidate.rsplit("_", 1)[1]
            gain = means[candidate]["task"][:, observer_index] - means[matched]["task"][:, observer_index]
            prefix = "field_over_matched_" + control
            gates[observer + "_" + control + "_each_model"] = bool((gain >= rule[prefix + "_each_model_min"]).all())
            gates[observer + "_" + control + "_pooled"] = bool(gain.mean() > rule[prefix + "_pooled_strict_min"])
        clean = means[candidate]["clean"][:, observer_index] - means["frozen"]["clean"][:, observer_index]
        gates[observer + "_clean_each_model"] = bool((clean >= rule["clean_delta_each_model_min"]).all())
    absolute = {method: {endpoint: value.tolist() for endpoint, value in score.items()} for method, score in means.items()}
    return {"comparisons": table, "costs": costs, "absolute_seed_observer_means": absolute,
            "development_entry": {"rule": rule, "checks": gates, "passed": all(gates.values()),
                                  "new_holdout_authorized": False}}


def old_ordinary_regression(root, protocol, endpoints, paths):
    """Compare paired old endpoints; explicitly mark absent historical checkpoint bytes."""
    selection = read_json(V3 / "evidence/DEVELOPMENT_SELECTION.json")
    runtime = read_json(V3 / "evidence/ARCHIVE_RUNTIME_ENVIRONMENT.json")
    runtime_match = (runtime["torch"] == protocol["runtime"]["torch"]
                     and runtime["numpy"] == protocol["runtime"]["numpy"]
                     and runtime["training_torch_threads"] == protocol["runtime"]["torch_threads"]
                     and runtime["interop_threads"] == protocol["runtime"]["interop_threads"])
    report = {"recorded_runtime_matches": runtime_match, "old_runtime": runtime,
              "checkpoint_file_hash_equality_expected": False, "seeds": {}}
    for seed, current in zip(protocol["seeds"], endpoints, strict=True):
        old = V3 / "evidence/development" / str(seed)
        complete, start = read_json(old / "COMPLETE.json"), read_json(old / "START.json")
        require(file_hash(old / "ENDPOINTS.npz") == selection["endpoint_file_sha256"][str(seed)], "Historical endpoint hash changed")
        require(selection["ordinary_action_indices"][str(seed)] == protocol["baseline_actions"][str(seed)], "Historical ordinary selection differs")
        sources = ["field_bridge_v3_20261027/learning.py", "field_bridge_20261027/adapters.py", "v6/neural.py", "v6/data.py", "v6/observer.py"]
        source_matches = {name: file_hash(HERE.parent / name) == start["source_files"][name] for name in sources}
        panels = read_json(root / "evaluate" / str(seed) / "PANELS.json")
        with np.load(old / "ENDPOINTS.npz", allow_pickle=False) as archive:
            values = {key: archive[key] for key in archive.files}
        require(values["schedule_ids"].tolist() == protocol["schedules"]
                and values["observer_names"].tolist() == protocol["observers"], "Historical endpoint axes changed")
        old_method = "ordinary_" + str(protocol["baseline_actions"][str(seed)])
        old_index, new_index = values["methods"].tolist().index(old_method), protocol["methods"].index("ordinary_48")
        result = {"old_method": old_method, "core_source_matches": source_matches, "endpoints": {}, "checkpoints": {}}
        for endpoint in ("task", "clean"):
            require(str(values[endpoint + "_panel_identity"]) == panels[endpoint]["sha256"], "Old/new panel identities differ")
            observed, expected = current[endpoint][new_index], values[endpoint + "_values"][old_index]
            result["endpoints"][endpoint] = {"exact": bool(np.array_equal(observed, expected)),
                "maximum_absolute_difference": float(np.max(np.abs(observed - expected))),
                "mean_observer_delta": (observed - expected).mean(axis=(0, 2)).tolist(),
                "frozen_exact": bool(np.array_equal(current["frozen_" + endpoint], values["original_" + endpoint]))}
            if runtime_match and all(source_matches.values()):
                require(result["endpoints"][endpoint]["exact"] and result["endpoints"][endpoint]["frozen_exact"],
                        "Ordinary48 historical endpoint regression failed")
        for schedule in protocol["schedules"]:
            binding = complete["paths"][old_method + "/" + str(schedule)]
            old_checkpoint = old / binding["checkpoint"]
            checkpoint = {"old_file_sha256": binding["checkpoint_sha256"], "old_bytes_available": old_checkpoint.is_file(),
                          "identity_comparison": "UNAVAILABLE_OLD_CHECKPOINT_BYTES"}
            if old_checkpoint.is_file():
                import torch
                require(file_hash(old_checkpoint) == binding["checkpoint_sha256"], "Old checkpoint hash mismatch")
                saved = torch.load(old_checkpoint, map_location="cpu", weights_only=True)
                current_identity = next(row["final"] for row in paths if row["seed"] == seed
                                        and row["method"] == "ordinary_48" and row["schedule_id"] == schedule)
                checkpoint["identity_comparison"] = "MATCH" if saved["identity"] == current_identity else "DIFFERS"
                if runtime_match and all(source_matches.values()):
                    require(checkpoint["identity_comparison"] == "MATCH", "Historical ordinary checkpoint identity differs")
            result["checkpoints"][str(schedule)] = checkpoint
        report["seeds"][str(seed)] = result
    return report


def audit_run(root, freeze_path):
    root, freeze_path = Path(root), Path(freeze_path)
    protocol, freeze = read_json(HERE / "PROTOCOL.json"), read_json(freeze_path)
    require(freeze["schema"] == "hepta.field-bridge.v5.source-freeze.1"
            and re.fullmatch(r"[a-f0-9]{40}", freeze["registered_commit"]), "Unregistered source freeze")
    for name, expected in freeze["files"].items():
        location = (HERE.parent / name).resolve()
        require(location.is_relative_to(HERE.parent) and file_hash(location) == expected, "Frozen source changed: " + name)
    require(str(Path(HERE.name) / "audit.py") in freeze["files"], "Audit source was not frozen")
    require(not protocol["new_holdout_access"] and protocol["observers"] == ["reward", "audit"], "Unregistered source/observer scope")
    training = read_json(V3 / "PROTOCOL.json")["training"]
    calibration = read_json(HERE / "evidence/CALIBRATION.json")["seeds"]
    paths, train_stages, evaluation_stages, evaluation_starts, endpoints = [], [], [], [], []
    for phase in ("train", "evaluate"):
        require({item.name for item in (root / phase).iterdir() if item.is_dir()}
                == {str(seed) for seed in protocol["seeds"]}, "Incomplete seed census")
        for seed in protocol["seeds"]:
            destination = root / phase / str(seed)
            sealed, start = verify_stage(destination), read_json(destination / "START.json")
            require(start["phase"] == phase and start["seed"] == seed and start["new_holdout_access"] is False
                    and start["study_id"] == protocol["study_id"]
                    and start["freeze_sha256"] == file_hash(freeze_path)
                    and start["protocol_sha256"] == file_hash(HERE / "PROTOCOL.json")
                    and start["registered_commit"] == freeze["registered_commit"], "Stage registration mismatch")
            require(start["torch"] == protocol["runtime"]["torch"] and start["numpy"] == protocol["runtime"]["numpy"], "Runtime identity mismatch")
            require(sealed["completed_unix_ns"] >= start["started_unix_ns"], "Stage wall clock reversed")
            if phase == "evaluate":
                require(sealed["new_holdout_access"] is False, "New holdout access reported")
                require(sealed["training_seals"] == {str(item): file_hash(root / "train" / str(item) / "COMPLETE.json")
                                                     for item in protocol["seeds"]}, "Evaluation used different training seals")
                endpoints.append(audit_endpoints(destination, protocol))
                evaluation_stages.append(sealed)
                evaluation_starts.append(start["started_unix_ns"])
                continue
            bank, fitted, _ = load_saved(V3 / "evidence", seed)
            expected_paths = {f"{method}/{schedule}" for method in protocol["methods"] for schedule in protocol["schedules"]}
            require({row["path"] for row in sealed["paths"]} == expected_paths
                    and sealed["train_paths"] == len(sealed["paths"]) == len(expected_paths)
                    and sealed["endpoint_access"] is False, "Incomplete training census")
            for binding in sealed["paths"]:
                require(file_hash(destination / binding["path"] / "PATH.json") == binding["record_sha256"], "Path record binding mismatch")
            for method in protocol["methods"]:
                for schedule in protocol["schedules"]:
                    paths.append(audit_path(destination / method / str(schedule), protocol, training, seed, method,
                                            schedule, fitted, fit_origin(bank), calibration[str(seed)]["tau"]))
            rows = [row for row in paths if row["seed"] == seed]
            require(len({object_hash(row["initial"]) for row in rows}) == 1
                    and len({row["frozen_base_sha256"] for row in rows}) == 1, "Unequal path initialization/base")
            train_stages.append(sealed)
    require(len(paths) == protocol["paths"] == len(protocol["seeds"]) * len(protocol["methods"]) * len(protocol["schedules"]), "Incomplete global census")
    require(min(evaluation_starts) >= max(stage["completed_unix_ns"] for stage in train_stages), "Endpoint barrier violated")
    return {"schema": "hepta.field-bridge.v5.independent-artifact-audit.1", "integrity_status": "PASS",
            "scope": "exploratory old development; no p-values, confidence intervals or new holdout",
            "source_freeze_sha256": file_hash(freeze_path), "protocol_sha256": file_hash(HERE / "PROTOCOL.json"),
            "new_model_evaluations": 0, "new_holdout_access": False, "paths": paths,
            "phase_resources": {"train": [{key: row[key] for key in ("seed", "resources", "cpu_ns", "wall_ns")} for row in train_stages],
                                "evaluate": [{key: row[key] for key in ("seed", "resources", "cpu_ns", "wall_ns")} for row in evaluation_stages]},
            "old_ordinary_regression": old_ordinary_regression(root, protocol, endpoints, paths),
            **comparisons(protocol, endpoints, paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit_run(args.run_root, args.freeze)
    except Exception as error:
        write_json(args.output, {"integrity_status": "FAIL", "error_type": type(error).__name__, "error": str(error),
                                "development_entry": {"passed": False, "new_holdout_authorized": False}})
        raise
    write_json(args.output, report)
    print(json.dumps({"integrity_status": report["integrity_status"], "development_entry": report["development_entry"]}))


if __name__ == "__main__":
    main()
