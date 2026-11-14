"""Post-seal arithmetic, identity and retained parity evidence verification."""

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

import numpy as np

from audit_training_checks import decode_arrays, read_json, require, same_number, sha


def quantiles(values):
    array = np.asarray(values, dtype=np.float64)
    return {
        "median": float(np.median(array)),
        "p95": float(np.quantile(array, 0.95)),
        "p05": float(np.quantile(array, 0.05)),
        "min": float(array.min()),
        "max": float(array.max()),
        "sum": float(array.sum()),
    }


def audit_one(path, run, spec):
    measurement, result = (
        read_json(path / "MEASUREMENT.json"),
        read_json(run / "RESULT.json"),
    )
    identity = measurement["identity"]
    require(identity["spec"] == spec == result["spec"], "measurement/run spec")
    require(
        identity["run_result_sha256"] == sha(run / "RESULT.json"),
        "measurement result binding",
    )
    require(
        identity["source_seals"] == result["source_seals"], "measurement source seals"
    )
    selected = result["candidates"][result["selection"]["candidate_index"]]
    require(
        identity["checkpoint_manifest_sha256"]
        == selected["checkpoint_manifest_sha256"],
        "measurement selected weights",
    )
    require(
        identity["selected_checkpoint"] == result["selected_checkpoint"],
        "measurement checkpoint path",
    )
    require(measurement["strict_reload"], "measurement reload contract")
    require(
        measurement["environment"]["threads"] == 1
        and not measurement["environment"]["cuda"],
        "CPU single-thread environment",
    )
    batch = measurement["fixed_batch"]["batch_size"]
    require(batch == min(16, spec["test_size"]), "fixed measurement batch")
    require(measurement["warmup_repetitions_per_mode"] == 2, "warmup count")
    require(measurement["measurement_repetitions_per_mode"] == 7, "timed repeat count")
    expected_order = []
    for phase, repeats in (("warmup", 2), ("measurement", 7)):
        for repeat in range(repeats):
            modes = ("batch", "stream") if repeat % 2 == 0 else ("stream", "batch")
            expected_order.extend((phase, repeat, mode) for mode in modes)
    raw = measurement["raw_samples"]
    require(
        [(row["phase"], row["repeat"], row["mode"]) for row in raw] == expected_order,
        "alternating measurement order",
    )
    for row in raw:
        forward, request = row["forward"], row["reset_plus_forward_interval"]
        for timer in ("cpu_seconds", "wall_seconds"):
            require(
                forward[timer] > 0 and request[timer] >= forward[timer],
                "forward/request timer nesting",
            )
        reset = row["reset_with_identity_check"]
        if row["mode"] == "batch":
            require(reset is None, "batch reset field")
        else:
            require(reset is not None, "stream reset field")
            for timer in ("cpu_seconds", "wall_seconds"):
                require(
                    reset[timer] >= 0
                    and request[timer] + 1e-8 >= reset[timer] + forward[timer],
                    "reset/forward timer nesting",
                )
    modes = {}
    for mode in ("batch", "stream"):
        rows = [
            row for row in raw if row["phase"] == "measurement" and row["mode"] == mode
        ]
        wall = [row["forward"]["wall_seconds"] for row in rows]
        cpu = [row["forward"]["cpu_seconds"] for row in rows]
        summary = measurement["measurement"][mode]
        require(
            summary["wall_seconds"] == wall and summary["process_cpu_seconds"] == cpu,
            "raw timing arrays",
        )
        for key, values in (
            ("wall_latency_seconds", wall),
            ("process_cpu_seconds_stats", cpu),
            ("examples_per_second", [batch / value for value in wall]),
        ):
            recomputed = quantiles(values)
            require(set(summary[key]) == set(recomputed), "timing statistic inventory")
            for name, value in recomputed.items():
                same_number(
                    summary[key][name], value, "timing statistic " + name, 1e-10
                )
        require(
            summary["reset_plus_forward_wall_seconds"]
            == [row["reset_plus_forward_interval"]["wall_seconds"] for row in rows],
            "request timing arrays",
        )
        require(
            summary["repeat_output_max_abs_difference"] == 0,
            "repeat output determinism",
        )
        modes[mode] = {
            "median_ms": 1000 * np.median(wall),
            "p95_ms": 1000 * np.quantile(wall, 0.95),
            "median_cpu_ms": 1000 * np.median(cpu),
            "median_examples_per_second": np.median([batch / value for value in wall]),
            "median_reset_plus_forward_ms": 1000
            * np.median(summary["reset_plus_forward_wall_seconds"]),
        }
    parity = measurement["parity"]
    require(
        (parity["rtol"], parity["atol"]) == (3e-5, 3e-6),
        "prespecified parity tolerance",
    )
    arrays = decode_arrays(path / "parity_arrays", parity["arrays_manifest_sha256"])
    full, stream = (
        arrays["full_sequence_prefix_logits"],
        arrays["incremental_prefix_logits"],
    )
    require(
        full.shape == stream.shape and full.shape[:2] == (batch, spec["length"]),
        "prefix parity layout",
    )
    require(
        np.isfinite(full).all() and np.isfinite(stream).all(), "prefix parity finite"
    )
    predictions = decode_arrays(
        run / "predictions", result["predictions_manifest_sha256"]
    )
    require(
        np.array_equal(arrays["sample_ids"], predictions["sample_ids"][:batch]),
        "fixed parity sources",
    )
    require(
        np.array_equal(arrays["labels"], predictions["labels"][:batch]),
        "fixed parity labels",
    )
    require(
        measurement["fixed_batch"]["sample_ids"] == arrays["sample_ids"].tolist(),
        "measurement source list",
    )
    close = np.isclose(stream, full, rtol=3e-5, atol=3e-6)
    changes = stream.argmax(-1) != full.argmax(-1)
    saved_close = bool(
        np.allclose(full[:, -1], predictions["logits"][:batch], rtol=3e-5, atol=3e-6)
    )
    expected = {
        "all_prefixes_within_tolerance": bool(close.all()),
        "tensor_entries_outside_tolerance": int((~close).sum()),
        "max_abs_logit_error": float(np.abs(stream - full).max()),
        "final_max_abs_logit_error": float(np.abs(stream[:, -1] - full[:, -1]).max()),
        "prefix_predicted_class_changes": int(changes.sum()),
        "final_predicted_class_changes": int(changes[:, -1].sum()),
        "saved_training_predictions_within_tolerance": saved_close,
        "saved_training_prediction_max_abs_error": float(
            np.abs(full[:, -1] - predictions["logits"][:batch]).max()
        ),
        "passed": bool(close.all()) and not bool(changes.any()) and saved_close,
    }
    for key, value in expected.items():
        require(parity[key] == value, "recorded parity outcome " + key)
    sizes = parity["state_payload_bytes_initial_and_after_each_step"]
    require(
        len(sizes) == spec["length"] + 1
        and sizes[-1] == parity["final_state_payload_bytes"],
        "state-size trace",
    )
    require(
        parity["processed_rows"] == batch * spec["length"]
        and parity["steps"] == spec["length"],
        "stream work counters",
    )
    if spec["architecture"] == "transformer":
        require(all(b > a for a, b in zip(sizes, sizes[1:])), "growing causal KV cache")
    else:
        require(len(set(sizes)) == 1, "constant recurrent state payload")
    replay = measurement["cross_process_replay"]
    selected_replay = (
        spec["stage"] == "representation"
        and spec["task"] == "mnist"
        and spec["seed"] == 6201
    )
    if selected_replay:
        require(
            replay == read_json(path / "cold_replay/EXECUTION.json"),
            "child execution receipt",
        )
        require(
            replay["status"] == "completed" and replay["returncode"] == 0,
            "child completion",
        )
        child = replay["child"]
        require(
            child["model_sha256"] == measurement["model_sha256"], "child model binding"
        )
        require(
            child["pid"] != replay["parent_pid"]
            and child["parent_pid"] == replay["parent_pid"],
            "distinct replay process",
        )
        expected_logits = decode_arrays(
            path / "cold_replay/parent_expected",
            replay["parent_expected_manifest_sha256"],
        )["logits"]
        actual_logits = decode_arrays(
            path / "cold_replay/child/arrays", child["arrays_manifest_sha256"]
        )["logits"]
        require(
            np.array_equal(actual_logits, expected_logits), "cross-process exact logits"
        )
        require(
            child["final_state_sha256"] == replay["parent_expected_final_state_sha256"],
            "cross-process exact final state digest",
        )
        require(
            replay["passed"]
            and replay["exact_logits"]
            and replay["exact_final_state"]
            and replay["distinct_process"],
            "cross-process result flags",
        )
    else:
        require(replay["status"] == "not_selected", "prespecified replay selection")
    return {
        "id": spec["id"],
        "measurement_sha256": sha(path / "MEASUREMENT.json"),
        "spec": spec,
        "modes": modes,
        "parity": expected,
        "persistent_state_payload_bytes": sizes[-1],
        "state_payload_trace": sizes,
        "cross_process_replay": replay,
        "total_parent_cpu_seconds": measurement["total_parent_cpu_seconds"],
        "total_wall_seconds": measurement["total_wall_seconds"],
    }


def audit_measurements(package, results):
    package, results = Path(package), Path(results)
    start = time.process_time(), time.perf_counter()
    inventory = read_json(package / "RUNS.json")
    selected = [
        spec
        for spec in inventory
        if (spec["stage"] == "representation" and spec["seed"] == 6201)
        or (spec["stage"] == "scaling" and spec["seed"] == 7301)
    ]
    checked, missing, issues = [], [], []
    for spec in selected:
        path = results / "measurements" / spec["id"]
        if not (path / "MEASUREMENT.json").exists():
            missing.append(spec["id"])
            continue
        try:
            checked.append(audit_one(path, results / spec["id"], spec))
        except Exception as error:
            issues.append(
                {"id": spec["id"], "type": type(error).__name__, "issue": str(error)}
            )
    return {
        "status": "failed" if issues else "incomplete" if missing else "passed",
        "expected": len(selected),
        "audited": len(checked),
        "missing": missing,
        "issues": issues,
        "parity_passing": sum(row["parity"]["passed"] for row in checked),
        "parity_disagreements": [
            row["id"] for row in checked if not row["parity"]["passed"]
        ],
        "exact_cross_process_replays": sum(
            row["cross_process_replay"].get("passed", False) for row in checked
        ),
        "measurements": checked,
        "analysis_source_sha256": sha(__file__),
        "cpu_seconds": time.process_time() - start[0],
        "wall_seconds": time.perf_counter() - start[1],
        "scope": "independent arithmetic and retained identity/parity evidence; no timing rerun or dedicated-host claim",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("--results", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output")
    args = parser.parse_args()
    result = audit_measurements(args.package, args.results)
    destination = (
        Path(args.output)
        if args.output
        else Path(args.results) / "MEASUREMENT_AUDIT.json"
    )
    destination.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "status",
                    "audited",
                    "parity_passing",
                    "exact_cross_process_replays",
                    "issues",
                )
            }
        )
    )
    raise SystemExit(0 if result["status"] == "passed" else 1)
