"""Read every persisted lifecycle checkpoint in the evaluator's fresh process."""

import gc
import json
from pathlib import Path
import time

import numpy as np

from export_native import canonical
from reference import decode, forward, load_checkpoint


def evaluate_maintenance(root, features, output):
    root = Path(root)
    fit = json.loads((root / "MAINTENANCE.json").read_text())
    report = {"schema": "hepta.memory.v10.maintenance-evaluation.v1", "cycles": [],
              "fresh_from_training_process": True, "native_owner_claimed": False}
    for cycle in fit["cycles"]:
        record = {"cycle": cycle["cycle"], "event": cycle["event"], "index": cycle["index"], "arms": {}}
        for name in cycle["arms"]:
            directory = root / f"cycle-{cycle['cycle']:02d}" / name
            started = time.perf_counter()
            arrays, manifest = load_checkpoint(directory)
            predictions = decode(forward(arrays, features), "semantic")
            active = cycle["active_indices"]
            correct = {i: predictions[i]["value"] == cycle["values"][i] for i in active}
            retained = [i for i in active if i != cycle["index"]]
            reads = [0]

            def service_read(index, running):
                if not running:
                    return {"status": "owner_stopped", "value": None}
                if index not in active:
                    return {"status": "deleted", "value": None}
                reads[0] += 1
                return {"status": "ok", "value": decode(forward(arrays, features[index:index + 1]), "semantic")[0]["value"]}

            stopped = service_read(active[0], False)
            if reads[0] != 0:
                raise AssertionError("stopped service entered model inference")
            denied = service_read(cycle["index"], True) if cycle["event"] == "delete_clean_rebuild" else None
            if denied is not None and (denied["status"] != "deleted" or reads[0] != 0):
                raise AssertionError("deleted address entered model inference")
            record["arms"][name] = {"canonical_correct": sum(correct.values()), "active_count": len(active),
                                      "retained_correct": sum(correct[i] for i in retained), "retained_count": len(retained),
                                      "changed_record_correct": correct.get(cycle["index"]),
                                      "source_ids": manifest["source_ids"], "predictions": predictions,
                                      "deleted_read": denied, "stopped_read": stopped,
                                      "model_reads_during_denials": reads[0], "read_wall_seconds": time.perf_counter() - started,
                                      "scope": "research service guard; actual DurableCognitiveStore lifecycle is separate"}
        report["cycles"].append(record)
    Path(output).write_bytes(canonical(report))
    return report


def evaluate_structure(root, features, query_features, query_indices, output, *, phase="held"):
    root = Path(root)
    fit = json.loads((root / "STRUCTURE.json").read_text())
    report = {"proposal_valid": fit["proposal_valid"], "phase": phase, "arms": {}, "split_admitted": False, "merge_admitted": False}
    for name, arm in fit["arms"].items():
        checkpoints = [load_checkpoint(root / f"{name}-{i}")[0] for i in range(len(arm["checkpoints"]))]
        if arm["assignments"] is None:
            canonical_raw, query_raw = forward(checkpoints[0], features), forward(checkpoints[0], query_features)
        else:
            assignment = np.asarray(arm["assignments"])
            canonical_raw = np.asarray([forward(checkpoints[assignment[i]], features[i:i + 1])[0] for i in range(len(features))])
            query_raw = np.asarray([forward(checkpoints[assignment[index]], row[None, :])[0] for row, index in zip(query_features, query_indices, strict=True)])
        predictions, worded = decode(canonical_raw, "semantic"), decode(query_raw, "semantic")
        report["arms"][name] = {"canonical_correct": sum(row["value"] == target for row, target in zip(predictions, fit["values"], strict=True)),
                               "canonical_count": len(features), "worded_correct": sum(row["value"] == fit["values"][index] for row, index in zip(worded, query_indices, strict=True)),
                               "worded_count": len(query_indices), "canonical_predictions": predictions, "worded_predictions": worded}
    if fit["proposal_valid"]:
        dynamic = report["arms"]["dynamic_children"]
        controls = [report["arms"][name] for name in ("rank8", "fixed_experts")]
        report["quality_gate"] = {"strict_worded_gain_over_both_controls": all(dynamic["worded_correct"] > row["worded_correct"] for row in controls),
                                  "no_canonical_regression": all(dynamic["canonical_correct"] >= row["canonical_correct"] for row in controls),
                                  "used_for_admission": phase == "calibration"}
        arrays, _ = load_checkpoint(root / "merged")
        merged = decode(forward(arrays, features), "semantic")
        report["merge"] = {"canonical_correct": sum(row["value"] == target for row, target in zip(merged, fit["values"], strict=True)),
                           "canonical_count": len(features), "predictions": merged}
        worded_merge = decode(forward(arrays, query_features), "semantic")
        report["merge"]["worded_correct"] = sum(row["value"] == fit["values"][index] for row, index in zip(worded_merge, query_indices, strict=True))
        report["merge"]["worded_count"] = len(query_indices)
        report["merge"]["no_quality_regression"] = (report["merge"]["canonical_correct"] >= dynamic["canonical_correct"]
                                                       and report["merge"]["worded_correct"] >= dynamic["worded_correct"])
        awake, manifest = load_checkpoint(root / "dynamic_children-0")
        before = forward(awake, features[:2])
        del awake
        gc.collect()
        start = time.perf_counter()
        awake, after_manifest = load_checkpoint(root / "dynamic_children-0")
        after = forward(awake, features[:2])
        report["sleep_wake"] = {"parameter_sha256": manifest["parameter_sha256"], "same_parameter_identity": manifest["parameter_sha256"] == after_manifest["parameter_sha256"],
                                 "raw_read_equal": bool(np.array_equal(before, after)), "wake_and_read_seconds": time.perf_counter() - start,
                                 "scope": "explicit Python arrays release and persisted reload, not process RSS reclamation guarantee"}
    report["admission_gate"] = "no promotion: required full lifecycle cost scopes remain unmeasured"
    Path(output).write_bytes(canonical(report))
    return report
