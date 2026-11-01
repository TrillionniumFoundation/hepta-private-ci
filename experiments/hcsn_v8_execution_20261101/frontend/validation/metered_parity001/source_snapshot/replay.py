"""Recompute historical predictions and exercise exact-content cache admission."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import (
    CacheBudget, Modality, VisibleContent,
)
from .legacy_v3 import LegacyV3Head, RECOVERED, REPO, prepared_observation, predict_prefix


DATA = RECOVERED / "experiments/hcsn_task_value_v1/results/async_frontend001/data"


def legacy_data(task, split, diagnostic=None):
    """Load restored real features with explicit historical, already-used roles."""
    from experiments.hcsn_mechanism_content_v2.data import load_data

    job = {"task": task, "av_directory": str(DATA), "av_window_seconds": .1,
           "binding_deadline_seconds": 1.5, "binding_pair_seed": 2026110173}
    data = load_data(job, split, diagnostic=diagnostic, allow_heldout=split == "test")
    # The original timestamp origin is used only to admit source-causal rows.
    with np.load(DATA / (("validation" if split == "val" else split) + ".npz"),
                 allow_pickle=False) as raw:
        origins = dict(zip(raw["clip_ids"].astype(str), raw["origins"], strict=True))
    if task == "async_av":
        data["relative_times"] = data["timestamps"] - np.array(
            [origins[str(i)] for i in data["ids"]])[:, None]
    else:
        data["relative_times"] = data["timestamps"].copy()
    return data


def episode_arrays(data, index):
    valid = data["valid"][index]
    return (data["x"][index, valid], data["observed"][index, valid],
            data["relative_times"][index, valid])


def populated_cache(data, index, audio_level, video_level, order="audio_first"):
    """Construct the same causal snapshot through two legal acquisition orders."""
    if order not in ("audio_first", "video_first"):
        raise ValueError("Unknown acquisition order")
    content = VisibleContent(f"historical-row-{index}", CacheBudget(65536))
    x, observed, times = episode_arrays(data, index)
    modalities = (Modality.AUDIO, Modality.VIDEO)
    if order == "video_first":
        modalities = tuple(reversed(modalities))
    levels = {Modality.AUDIO: audio_level, Modality.VIDEO: video_level}
    for modality in modalities:
        for level in range(1, levels[modality] + 1):
            now = max(float(level), content.last_accepted_at + .001)
            observation = prepared_observation(
                x, observed, times, object_id=content.object_id, modality=modality,
                prefix_end=level, completed_at=now)
            content = content.accept(observation, now)
    return content


def source_inventory():
    files = [Path(__file__), Path(__file__).with_name("legacy_v3.py")]
    manifests = [RECOVERED / name for name in ("SOURCE_VERIFICATION.json", "ARCHIVE_RECOVERY_RECEIPT.json")]
    return {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files + manifests}


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    began_cpu, began_wall = time.process_time(), time.perf_counter()
    from experiments.hcsn_causal_execution_v3.av_audit import audit
    from experiments.hcsn_causal_execution_v3.av_probe import encode, labels_of, predict_features
    from experiments.hcsn_mechanism_content_v2.binding_data import verify_single_modality_marginals

    historical = RECOVERED / "experiments/hcsn_causal_execution_v3/results/av_probe"
    original_audit = audit(historical)
    (output / "HISTORICAL_AUDIT.json").write_text(json.dumps(original_audit, indent=2) + "\n")
    protocol = {
        "scope": "Historical V3 development replay; not V6 restoration, new confirmation or a scientific candidate",
        "sources": source_inventory(), "tasks": ["async_av", "av_binding"],
        "splits": ["train", "val", "test"], "audio_prefixes": [0, 1, 2, 3],
        "video_prefixes": [0, 1, 2, 3], "orders": ["audio_first", "video_first"],
        "comparison": "The same frozen original head on exactly the same accepted source rows",
        "probability_tolerance": 1e-12, "fresh_confirmation": False,
        "labels": "V3 six-emotion classification and same-recording source binding, not V6 five-class/statement binding",
        "source_use": "All splits and actors were previously exposed; test is a historical replay label only",
        "cost_boundary": "Import, prepared-array load, adapter and original inference, all checks and artifacts; original decoding/training excluded",
    }
    (output / "PROTOCOL.json").write_text(json.dumps(protocol, indent=2) + "\n")
    report, comparisons, max_error, max_payload, max_objects = {}, [], 0.0, 0, 0
    for task in protocol["tasks"]:
        head = LegacyV3Head(task)
        task_report = {"checkpoint_sha256": head.checkpoint_sha256,
                       "head_storage": head.storage_accounting(), "splits": {}}
        for split in protocol["splits"]:
            data = legacy_data(task, split)
            labels = labels_of(data)
            split_rows, max3_predictions = [], []
            for index in range(len(labels)):
                x, observed, times = episode_arrays(data, index)
                kinds = (x[:, 33] > x[:, 32]).astype(int)
                for audio in protocol["audio_prefixes"]:
                    for video in protocol["video_prefixes"]:
                        mask = times <= np.where(kinds == 0, audio, video)
                        expected = predict_prefix(head.model, x[mask], observed[mask])
                        for order in protocol["orders"]:
                            cache = populated_cache(data, index, audio, video, order)
                            predicted = head.classify(cache)
                            error = float(np.max(np.abs(predicted - expected)))
                            accounting = cache.storage_accounting()
                            max_payload = max(max_payload, accounting["nominal_float64_payload_bytes"])
                            max_objects = max(max_objects, accounting["retained_python_object_graph_bytes"])
                            max_error = max(max_error, error)
                            row = {"task": task, "split": split, "row": index,
                                   "audio": audio, "video": video, "order": order,
                                   "error": error, "label": int(labels[index]),
                                   "prediction": predicted.tolist(), "expected": expected.tolist()}
                            comparisons.append(row)
                            split_rows.append(error)
                            if audio == video == 3 and order == "audio_first":
                                max3_predictions.append(predicted)
            full = predict_features(head.model, encode(data, str(head.model["feature_kind"])))
            selection = json.loads((historical / task / "selection.json").read_text())
            archived_path = historical / task / ("test_normal.npz" if split == "test" else
                selection["id"] + ("_validation_predictions.npz" if split == "val" else "_train_predictions.npz"))
            with np.load(archived_path, allow_pickle=False) as archived:
                archive_error = float(np.max(np.abs(full - archived["probabilities"])))
                same_objects = np.array_equal(data["ids"], archived["sample_ids"])
                same_labels = np.array_equal(labels, archived["labels"])
            task_report["splits"][split] = {
                "objects": len(labels), "actors": sorted(np.unique(data["group_ids"]).astype(str).tolist()),
                "comparisons": len(split_rows), "max_cache_probability_error": max(split_rows),
                "original_full_probability_error": archive_error,
                "original_full_objects_match": bool(same_objects), "original_full_labels_match": bool(same_labels),
                "original_full_correct": int(np.sum(full.argmax(1) == labels)),
                "three_second_prefix_correct": int(np.sum(np.array(max3_predictions).argmax(1) == labels)),
                "input_array_sha256": data["metadata"]["array_sha256"],
            }
            if not same_objects or not same_labels or archive_error > 1e-12:
                raise AssertionError("Historical prediction replay differs")
        report[task] = task_report
    marginal_checks = {}
    for split in protocol["splits"]:
        marginal_checks[split] = verify_single_modality_marginals(
            legacy_data("av_binding", split, "missing_video"),
            legacy_data("av_binding", split, "missing_audio"))
    with (output / "PAIRED_ROWS.jsonl").open("x") as stream:
        for row in comparisons:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    summary = {"scope": protocol["scope"], "fresh_confirmation": False,
               "tasks": report, "cache_comparisons": len(comparisons),
               "maximum_probability_error": max_error,
               "maximum_nominal_cache_payload_bytes": max_payload,
               "maximum_cache_python_object_graph_bytes": max_objects,
               "same_modality_binding_marginals": marginal_checks,
               "historical_audit_passed": original_audit["all_passed"],
               "adapter_parity_passed": max_error <= 1e-12,
               "content_quality_gate_passed": False,
               "gate_reason": "Historical V3 tasks/weights do not instantiate missing V6 frontend; independent new objects unavailable",
               "inner_process_cpu_seconds": time.process_time() - began_cpu,
               "inner_wall_seconds": time.perf_counter() - began_wall,
               "energy_joules": None}
    (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)
    if not original_audit["all_passed"] or max_error > 1e-12:
        raise SystemExit("Historical audit or exact cache replay failed; evidence retained")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
