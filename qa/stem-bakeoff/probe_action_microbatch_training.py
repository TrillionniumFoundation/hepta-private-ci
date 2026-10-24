"""Fixed 770D private-training engineering probe on one sealed TRAIN bank.

The nine conditions measure independent state updates and costs, not nine tasks.
Their final parameters are archived without saving a second scalar weight bank.
"""

import argparse
import json
import os
from pathlib import Path
import platform
import sys
import time

import numpy as np

from action_microbatch_compare import (MAX_TENSOR_BYTES, TOLERANCE, array_sha, compare_condition,
    file_sha, peak_rss, save_checkpoint, verify_checkpoint, write_json)
from cell_microbatch_training import FrozenTrainingBank

CODE_FILES = ("probe_action_microbatch_training.py", "action_microbatch_compare.py",
    "cell_runtime_bundle.py", "cell_microbatch_training.py", "cell_learning_models.py",
    "cell_learning_metrics.py", "cell_calibration_bounded.py")
SCALES, MODES = (64, 256, 1024), ("linear", "gated", "residual")


def source_code_snapshot():
    result = {}
    for name in CODE_FILES:
        try:
            result[name] = file_sha(Path(__file__).with_name(name))
        except OSError:
            result[name] = None
    return result


def prepare_bank(metadata, x, y, rows):
    if (metadata.get("schema") != "hepta.action-runtime-input-bundle.v1"
            or metadata.get("task_id") != "action_usefulness" or metadata.get("generation") != 1
            or metadata.get("width") != 770 or metadata.get("classes") != 2
            or metadata.get("training", {}).get("role") != "train"
            or metadata["training"].get("budget") != 32 or metadata["training"].get("seed") != 7
            or x.shape != (32, 770) or x.dtype != np.float32 or not np.isfinite(x).all()
            or y.shape != (32,) or y.dtype != np.int64 or np.bincount(y, minlength=2).tolist() != [16, 16]
            or len(rows) != 32 or len({r["group_id"] for r in rows}) != 32):
        raise ValueError("fixed real train-only seed7/n32/770D binary bank required")
    sources = [row["source_id"] for row in rows]
    task = metadata["task_id"]
    return FrozenTrainingBank.build({task: x}, {task: sources}, metadata["feature_identity"])


def run_probe(bundle, manifest_sha256, output):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    if sys.platform != "linux" or any(os.environ.get(name) != "1"
            for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")):
        raise ValueError("Linux measurement and explicit single-thread BLAS required")
    root, bundle = Path(output), Path(bundle)
    if root.exists() or any(path.is_symlink() for path in (root, *root.absolute().parents)):
        raise ValueError("fresh owned probe output without symlink ancestors required")
    code = source_code_snapshot()
    root.mkdir(parents=True, exist_ok=False)
    report = {"conditions": []}
    condition = None
    try:
        if any(pin is None for pin in code.values()):
            raise ValueError("required numerical implementation is unavailable before input loading")
        from cell_runtime_bundle import load_training_inputs
        metadata, x, y, rows = load_training_inputs(bundle, expected_manifest_sha256=manifest_sha256)
        bank_started, bank_cpu = time.perf_counter_ns(), time.process_time_ns()
        bank = prepare_bank(metadata, x, y, rows)
        bank_load = {"wall_ns": time.perf_counter_ns()-bank_started, "cpu_ns": time.process_time_ns()-bank_cpu,
            "raw_tensor_bytes": bank._raw.nbytes, "normalized_tensor_bytes": bank._normalized.nbytes,
            "index_tensor_bytes": bank._indices.nbytes, "total_tensor_bytes": bank.tensor_bytes,
            "distinct_training_sources": len(bank.source_ids), "distinct_bug_groups": len({r["group_id"] for r in rows})}
        input_arrays = {"features": array_sha(x), "labels": array_sha(y)}
        plan = {"schema": "hepta.action-770d-private-gradient-probe.v1", "bundle": str(bundle.resolve()),
            "bundle_manifest_sha256": manifest_sha256, "source_code_sha256": code,
            "feature_identity": bank.feature_identity, "task_id": metadata["task_id"], "task_count": 1,
            "generation": 1, "training_source_ids": list(bank.source_ids),
            "training_group_ids": [r["group_id"] for r in rows], "training_array_sha256": input_arrays,
            "training_rows": 32, "feature_width": 770, "classes": 2, "rank": 4,
            "scales": list(SCALES), "modes": list(MODES), "steps": 20, "microbatch": 8,
            "max_tensor_bytes": MAX_TENSOR_BYTES, "learning_rate": .02, "l2": .001,
            "initial_seed": "1000000 + physical Cell index; same in both methods",
            "parameter_and_loss_atol": TOLERANCE, "parameter_and_loss_rtol": TOLERANCE,
            "fit_order": "scalar first for linear/residual, batched first for gated; both setups precede fits",
            "scientific_scope": "engineering work on a previously frozen TRAIN bank; no independent quality test",
            "parameter_checkpoint_scope": "every final batched parameter; scalar SHA and parity retained; Adam not resumable",
            "timing_scope": "same shared Linux CPU process; descriptive single runs, not isolated capacity",
            "runtime": {"python": sys.version, "numpy": np.__version__, "platform": platform.platform()},
            "encoder_forwards": 0, "encoder_updates": 0, "calibration_fit_calls": 0,
            "heldout_or_calibration_labels_used": False, "authority": "DENY_ALL", "quality_qualified": False}
        write_json(root/"plan.json", plan)
        report.update(plan=plan, feature_bank_construction=bank_load)
        for mode_index, mode in enumerate(MODES):
            for count in SCALES:
                condition = {"mode": mode, "physical_cells": count}
                result, state = compare_condition(bank, y, count, mode,
                    steps=20, microbatch=8, max_tensor_bytes=MAX_TENSOR_BYTES,
                    first="scalar" if mode_index % 2 == 0 else "batched")
                location = root/f"{mode}-{count}"
                began, began_cpu = time.perf_counter_ns(), time.process_time_ns()
                digest = save_checkpoint(location, result, state)
                del state
                recovered = verify_checkpoint(location, digest)
                result["checkpoint"] = {"directory": location.name, "manifest_sha256": digest,
                    "parameter_archive_bytes": (location/"parameters.npz").stat().st_size,
                    "recovery": recovered, "wall_ns": time.perf_counter_ns()-began,
                    "cpu_ns": time.process_time_ns()-began_cpu,
                    "scope": "compression, all parameter-byte verification and first/last Head recovery; no new updates"}
                write_json(location/"report.json", result)
                report["conditions"].append(result)
                print(json.dumps({**condition, "max_parameter_difference": result["maximum_absolute_parameter_difference"],
                    "scalar_fit_seconds": result["executions"]["scalar"]["fit"]["wall_ns"]/1e9,
                    "batched_fit_seconds": result["executions"]["batched"]["fit"]["wall_ns"]/1e9,
                    "parameter_archive_bytes": result["checkpoint"]["parameter_archive_bytes"]}), flush=True)
        repeated, rx, ry, rr = load_training_inputs(bundle, expected_manifest_sha256=manifest_sha256)
        if (repeated != metadata or rr != rows or {"features": array_sha(rx), "labels": array_sha(ry)} != input_arrays
                or code != source_code_snapshot()):
            raise ValueError("frozen input bundle or numerical implementation changed during the probe")
    except Exception as error:
        observed = source_code_snapshot()
        write_json(root/"failed-attempt.json", {"failed_condition": condition,
            "completed_conditions": len(report["conditions"]), "error": str(error)[:2000],
            "wall_ns": time.perf_counter_ns()-started, "cpu_ns": time.process_time_ns()-cpu,
            "source_code_sha256_initial": code, "source_code_sha256_observed_at_failure": observed,
            "changed_code_files": {name: {"initial": pin, "observed": observed.get(name)}
                for name, pin in code.items() if observed.get(name) != pin},
            "partial_work_is_not_zero_cost": True, "authority": "DENY_ALL"})
        raise
    report["inclusive_probe"] = {"wall_ns": time.perf_counter_ns()-started,
        "cpu_ns": time.process_time_ns()-cpu,
        "scope": "input/code validation, bank construction, both methods, all comparisons/checkpoints/recovery and final input validation; excludes final report/manifest writes; nested measurements are not additional cost"}
    report.update(actual_total_private_optimizer_updates_both_methods=sum(
        r["actual_total_private_optimizer_updates_both_methods"] for r in report["conditions"]),
        actual_total_example_updates_both_methods=sum(r["actual_total_example_updates_both_methods"] for r in report["conditions"]),
        parameter_archives_total_bytes=sum(r["checkpoint"]["parameter_archive_bytes"] for r in report["conditions"]),
        process_lifetime_peak_rss_bytes=peak_rss(), task_count=1, new_tasks_inferred_from_cell_count=False,
        encoder_forwards=0, encoder_updates=0, heldout_or_calibration_labels_used=False,
        mode="SHADOW_ONLY", authority="DENY_ALL", quality_qualified=False)
    write_json(root/"report.json", report)
    write_json(root/"manifest.json", {str(path.relative_to(root)): {"sha256": file_sha(path), "bytes": path.stat().st_size}
        for path in sorted(root.rglob("*")) if path.is_file()})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bundle", "manifest-sha256", "output", "verify-checkpoint", "checkpoint-manifest-sha256"):
        parser.add_argument("--"+name)
    args = parser.parse_args()
    if args.verify_checkpoint:
        if not args.checkpoint_manifest_sha256 or any((args.bundle, args.manifest_sha256, args.output)):
            parser.error("checkpoint verification needs only directory and its externally pinned manifest SHA")
        began, cpu = time.perf_counter_ns(), time.process_time_ns()
        result = verify_checkpoint(args.verify_checkpoint, args.checkpoint_manifest_sha256)
        result.update(wall_ns=time.perf_counter_ns()-began, cpu_ns=time.process_time_ns()-cpu,
                      fresh_process_entrypoint=True)
        print(json.dumps(result, sort_keys=True))
    else:
        if not all((args.bundle, args.manifest_sha256, args.output)) or args.checkpoint_manifest_sha256:
            parser.error("training probe needs --bundle --manifest-sha256 --output")
        result = run_probe(args.bundle, args.manifest_sha256, args.output)
        print(json.dumps({"conditions": len(result["conditions"]), "task_count": result["task_count"],
            "optimizer_updates_both_methods": result["actual_total_private_optimizer_updates_both_methods"]}))


if __name__ == "__main__":
    main()
