"""Linux resource experiment for private replicas of the two fixed P40 Heads.

Each child has an 800 MiB address-space hard limit, a 90 second wall limit,
and one frozen template. No Encoder, optimizer, policy or new quality trial runs.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import time

COUNTS = (1, 32, 256, 4096)
MODES = ("gated", "linear")
MEMORY_BYTES = 800 * 1024 * 1024
CHILD_SECONDS = 90
TOTAL_SECONDS = 12 * 60
MAX_REPORT_BYTES = 512 * 1024
SCIENCE_REPORT_SHA = "26c74e604c9404f93677d64687603f50afbf0414e7773c07a4237f5f9cbe0211"
TOLERANCE = 2e-5
ROOT = Path(__file__).resolve().parents[2]
DRIVER = "codex-rs/hepta-neuron/examples/native_task_head_pool.rs"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_pinned(path, expected=None, limit=MAX_REPORT_BYTES):
    path = Path(path)
    require(not path.is_symlink() and path.is_file(), "regular non-symlink file required")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, "input byte budget")
    require(expected is None or sha(raw) == expected, "input digest differs: " + str(path))
    return raw


def source_identity(expected_source):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()
    require(git("rev-parse", "HEAD") == expected_source and not git("status", "--porcelain"),
            "an exact clean committed source is required")
    paths = (DRIVER, "qa/stem-bakeoff/native_task_head_pool.py",
             "codex-rs/hepta-neuron/src/task_head_native.rs",
             "codex-rs/hepta-neuron/src/lib.rs",
             "qa/stem-bakeoff/replay_native_task_head_v1.py")
    return {"git_head_sha": expected_source, "git_tree_sha": git("rev-parse", "HEAD^{tree}"),
            "working_tree_clean": True, "source_file_sha256": {name: sha(read_pinned(ROOT / name)) for name in paths},
            "compiler_attestation_independently_verified": False}


def prepare_inputs(p40_directory, report_pin, output):
    """Reconstruct only the already pinned cached inputs; perform no prediction."""
    p40 = Path(p40_directory)
    original_raw = read_pinned(p40 / "native-results/report.json", report_pin)
    original = json.loads(original_raw)
    require(original["schema"] == "hepta.native-task-head-replay.v1" and original["status"] == "PASS",
            "complete original P40 report required")
    for name, digest in original["retained_file_sha256"].items():
        require(name in {f"{mode}-{case}.jsonl" for mode in MODES for case in (
            "paired", "missing_text", "missing_image", "shuffled_image", "mixed_presence")}
            | {f"{mode}-head/{part}" for mode in MODES for part in ("manifest.json", "weights.f32le")}
            | {f"{mode}-cost.json" for mode in MODES}, "unexpected P40 artifact name")
        read_pinned(p40 / "native-results" / name, digest)
    science = json.loads(read_pinned(p40 / "restored/results/report.json", SCIENCE_REPORT_SHA))
    require(original["original_report_sha256"] == SCIENCE_REPORT_SHA, "original science differs")
    for name, digest in science["plan"]["code_file_sha256"].items():
        require(Path(name).name == name, "invalid science source filename")
        read_pinned(Path(__file__).with_name(name), digest)
    from multimodal_features import load_bank, pair_features
    from replay_native_task_head_v1 import _request_lines
    import torch
    torch.set_num_threads(science["plan"]["threads"])
    bank, features = load_bank(p40 / "restored/bank",
        expected_manifest_sha256=science["bank_manifest_sha256"],
        expected_data_sha256=science["data_manifest_sha256"])
    rows = [json.loads(line) for line in read_pinned(p40 / "restored/cohorts/test.jsonl").splitlines()]
    bundle = pair_features(rows, bank, features, arm="text_image", intervention="paired")
    requests = b"".join(_request_lines(bundle))
    require(len(rows) == 256 and len(requests) <= 32 * 1024 * 1024, "paired input inventory differs")
    request_sha = sha(requests)
    for mode in MODES:
        require(original["cases"][mode + "-paired"]["request_stream_sha256"] == request_sha,
                "reconstructed paired request stream differs from original native execution")
    (output / "requests.jsonl").write_bytes(requests)
    references, artifacts = {}, {}
    for mode in MODES:
        target = output / (mode + "-head")
        target.mkdir()
        for name in ("manifest.json", "weights.f32le"):
            relative = mode + "-head/" + name
            raw = read_pinned(p40 / "native-results" / relative, original["retained_file_sha256"][relative])
            (target / name).write_bytes(raw)
        manifest = json.loads((target / "manifest.json").read_bytes())
        require(manifest["temperature"] == 0.25 and manifest["confidence_threshold"] == 0.7
                and manifest["required_present_mask"] == 3, "frozen Head contract differs")
        artifacts[mode] = {"directory": str(target), "manifest_sha256": original["retained_file_sha256"][mode + "-head/manifest.json"],
                           "weights_sha256": manifest["weights_sha256"], "weights_bytes": manifest["weights_bytes"]}
        references[mode] = [json.loads(line) for line in read_pinned(
            p40 / "native-results" / (mode + "-paired.jsonl"),
            original["retained_file_sha256"][mode + "-paired.jsonl"]).splitlines()]
    return original, requests, request_sha, artifacts, references


def summarize(observed, cells, artifact, request_sha, reference):
    require(observed["schema"] == "hepta.native-task-head-pool.v1" and observed["status"] == "PASS",
            "native pool execution incomplete")
    require(all(type(observed[key]) is int for key in ("cells", "resident_heads", "independently_trained_templates",
            "weights_bytes_per_head", "private_weights_payload_bytes", "warmup_calls", "input_rows",
            "fanout_predictions_per_sample", "validation_extra_reference_calls")), "native counters must be integers")
    require(observed["cells"] == observed["resident_heads"] == cells
            and observed["independently_trained_templates"] == 1
            and observed["weights_bytes_per_head"] == artifact["weights_bytes"]
            and observed["private_weights_payload_bytes"] == cells * artifact["weights_bytes"],
            "actual resident Head or parameter inventory differs")
    require(observed["manifest_sha256"] == artifact["manifest_sha256"]
            and observed["weights_sha256"] == artifact["weights_sha256"]
            and observed["request_stream_sha256"] == request_sha and observed["input_rows"] == 256,
            "native input/artifact identity differs")
    dispatch_counts = observed["dispatch_calls_per_head"]
    require(type(dispatch_counts) is list and len(dispatch_counts) == cells
            and all(type(v) is int for v in dispatch_counts),
            "per-Head dispatch counts must be exact integers")
    require(observed["warmup_calls"] == cells
            and dispatch_counts == [4096 // cells] * cells
            and observed["fanout_predictions_per_sample"] == cells
            and observed["validation_extra_reference_calls"] == 272
            and observed["reference_validation_outside_measurement"] is True,
            "actual dispatch/warmup/fanout call inventory differs")
    for key in ("task_admission_allowed", "action_execution_allowed", "native_encoder_executed",
                "new_training_or_calibration", "new_independent_quality_trial", "target_device_qualified"):
        require(observed[key] is False, "pool execution exceeds research scope")
    require(observed["mode"] == "SHADOW_ONLY" and observed["authority"] == "DENY_ALL"
            and observed["energy_joules"] is None
            and observed["rss_budget_bytes"] == observed["address_space_hard_limit_bytes"] == MEMORY_BYTES,
            "native posture or memory budget differs")
    peaks, pids = [], set()
    for name in ("baseline", "post_load", "post_warmup", "post_measurement"):
        value = observed[name]
        require(value["source"] == "native /proc/self/status"
                and all(type(value[key]) is int for key in ("proc_self_pid", "getpid", "rss_bytes", "rss_anon_bytes", "post_exec_peak_rss_bytes", "virtual_bytes"))
                and value["proc_self_pid"] > 0 and value["getpid"] > 0 and value["rss_bytes"] > 0
                and 0 <= value["rss_anon_bytes"] <= value["rss_bytes"] <= value["post_exec_peak_rss_bytes"] <= MEMORY_BYTES
                and 0 < value["virtual_bytes"] <= MEMORY_BYTES, "invalid native resident observation")
        peaks.append(value["post_exec_peak_rss_bytes"])
        pids.add((value["proc_self_pid"], value["getpid"]))
    require(peaks == sorted(peaks) and len(pids) == 1, "native process observation changed")
    predictions = observed["reference_predictions"]
    require(len(predictions) == len(reference) == 256 and observed["reference_source_record_digests"]
            == [row["source_record_digest"] for row in reference], "reference/source row order differs")
    max_error = 0.0
    for actual, row in zip(predictions, reference):
        expected = row["prediction"]
        require(set(actual) == set(expected), "native prediction shape differs")
        require(type(actual["accepted"]) is bool and type(actual["predicted_class"]) is int,
                "native decision types differ")
        for key in ("predicted_class", "accepted", "mode", "authority"):
            require(actual[key] == expected[key], "native prediction decision differs from P40")
        for key in ("task_logits", "task_probabilities", "gate"):
            first, second = (actual[key], expected[key]) if key != "gate" else ([actual[key]], [expected[key]])
            require(len(first) == len(second), "native prediction width differs")
            for left, right in zip(first, second):
                require(type(left) in (int, float) and math.isfinite(left) and abs(left - right) <= TOLERANCE,
                        "native prediction differs beyond fixed tolerance")
                max_error = max(max_error, abs(left - right))
    timings = {}
    for name, count in (("dispatch", 4096), ("fanout", 16)):
        raw = observed[name + "_nanoseconds"]
        require(len(raw) == count and all(type(v) is int and 0 < v < CHILD_SECONDS * 10**9 for v in raw),
                "invalid raw native timing inventory")
        timings[name] = {"samples": count, "median_ms": statistics.median(raw) / 1e6,
                         "max_ms": max(raw) / 1e6, "raw_nanoseconds_sha256": sha(canonical(raw))}
        if name == "dispatch":
            ordered = sorted(raw)
            timings[name].update({f"p{p}_ms": ordered[math.ceil(count * p / 100) - 1] / 1e6 for p in (50, 95, 99)})
    require(all(type(observed[key]) is int and 0 < observed[key] < CHILD_SECONDS * 10**9
                for key in ("elapsed_nanoseconds", "allocation_nanoseconds", "warmup_nanoseconds"))
            and observed["allocation_nanoseconds"] + observed["warmup_nanoseconds"]
            + sum(observed["dispatch_nanoseconds"]) + sum(observed["fanout_nanoseconds"]) <= observed["elapsed_nanoseconds"],
            "native wall-time accounting differs")
    return {"cells": cells, "private_weights_payload_bytes": observed["private_weights_payload_bytes"],
        "weights_bytes_per_head": artifact["weights_bytes"], "baseline": observed["baseline"],
        "post_load": observed["post_load"], "post_warmup": observed["post_warmup"],
        "post_measurement": observed["post_measurement"], "timings": timings,
        "reference_predictions_sha256": sha(canonical(predictions)), "max_prediction_error_vs_p40": max_error,
        "allocation_ms": observed["allocation_nanoseconds"] / 1e6,
        "warmup_ms": observed["warmup_nanoseconds"] / 1e6,
        "native_elapsed_ms": observed["elapsed_nanoseconds"] / 1e6}


def execute_child(command, stdout_path, stderr_path, timeout):
    """Output is capped by the child's FSIZE hard limit; failures never score PASS."""
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        completed = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=timeout, check=False)
    require(completed.returncode == 0, "native pool child failed; inspect retained stderr")
    return json.loads(read_pinned(stdout_path))


def run_pool(directory, binary, output, *, expected_report, expected_binary, expected_source):
    started = time.monotonic()
    require(platform.system() == "Linux", "Linux native pool resource experiment required")
    binary, target = Path(binary).resolve(), Path(output).resolve()
    require(not target.exists() and target.parent.is_dir() and not target.is_relative_to(ROOT)
            and not target.is_relative_to(Path(directory).resolve()), "new external output directory required")
    read_pinned(binary, expected_binary, 512 * 1024 * 1024)
    identity = source_identity(expected_source)
    limiter = Path(shutil.which("prlimit") or "/missing-prlimit")
    limiter_digest = sha(read_pinned(limiter, limit=1024 * 1024))
    target.mkdir(mode=0o700)
    original, requests, request_sha, artifacts, references = prepare_inputs(directory, expected_report, target)
    metadata = {"schema": "hepta.native-task-head-pool-plan.v1", "source_identity": identity,
        "native_binary_sha256": expected_binary, "p40_report_sha256": expected_report,
        "request_stream_sha256": request_sha, "input_stream_bytes": len(requests), "counts": COUNTS,
        "template_modes": MODES, "dispatch_samples": 4096, "fanout_samples": 16,
        "child_seconds": CHILD_SECONDS, "total_seconds": TOTAL_SECONDS, "memory_bytes": MEMORY_BYTES,
        "prlimit_path": str(limiter), "prlimit_sha256": limiter_digest, "absolute_tolerance": TOLERANCE,
        "platform": {"system": platform.system(), "machine": platform.machine(), "kernel": platform.release()},
        "python_version": platform.python_version()}
    plan = canonical(metadata)
    (target / "plan.json").write_bytes(plan)
    results, retained, reference_hash = {}, {}, {}
    for mode in MODES:
        artifact = artifacts[mode]
        for cells in COUNTS:
            remaining = TOTAL_SECONDS - (time.monotonic() - started)
            require(remaining > 0, "total experiment wall-time budget exhausted")
            name = f"{mode}-{cells}"
            command = [str(limiter), f"--as={MEMORY_BYTES}:{MEMORY_BYTES}",
                f"--fsize={MAX_REPORT_BYTES}:{MAX_REPORT_BYTES}", f"--cpu={CHILD_SECONDS}:{CHILD_SECONDS}", "--",
                str(binary), str(Path(artifact["directory"]) / "manifest.json"),
                str(Path(artifact["directory"]) / "weights.f32le"), artifact["manifest_sha256"],
                str(target / "requests.jsonl"), request_sha, str(cells)]
            path, stderr = target / (name + ".json"), target / (name + ".stderr")
            observed = execute_child(command, path, stderr, min(CHILD_SECONDS, remaining))
            result = summarize(observed, cells, artifact, request_sha, references[mode])
            reference_hash.setdefault(mode, result["reference_predictions_sha256"])
            require(reference_hash[mode] == result["reference_predictions_sha256"], "pool size changes frozen predictions")
            result.update({"raw_file": path.name, "raw_file_sha256": sha(read_pinned(path)),
                           "stderr_file": stderr.name, "command": command})
            results[name] = result
            retained[path.name] = result["raw_file_sha256"]
            retained[stderr.name] = sha(read_pinned(stderr))
            print(json.dumps({"completed": name, "resident_heads": cells,
                "post_load_rss_bytes": result["post_load"]["rss_bytes"]}), flush=True)
    require(time.monotonic() - started <= TOTAL_SECONDS, "total wall-time exceeded")
    require(source_identity(expected_source) == identity, "source changed during measurement")
    read_pinned(binary, expected_binary, 512 * 1024 * 1024)
    read_pinned(limiter, limiter_digest, 1024 * 1024)
    read_pinned(target / "requests.jsonl", request_sha, 32 * 1024 * 1024)
    read_pinned(Path(directory) / "native-results/report.json", expected_report)
    for artifact in artifacts.values():
        read_pinned(Path(artifact["directory"]) / "manifest.json", artifact["manifest_sha256"])
        read_pinned(Path(artifact["directory"]) / "weights.f32le", artifact["weights_sha256"])
    report = {"schema": "hepta.native-task-head-pool-replay.v1", "status": "PASS",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(), "plan_sha256": sha(plan),
        "source_identity": identity, "native_binary_sha256": expected_binary,
        "p40_report_sha256": expected_report, "p40_source_identity": original["source_identity"],
        "request_stream_sha256": request_sha, "artifacts": artifacts, "experiments": results,
        "retained_file_sha256": retained, "independently_trained_templates_total": 2,
        "total_wall_seconds": time.monotonic() - started, "execution_order": list(results),
        "scope": "sequential Linux shared-host measurements; N private copies of one of two frozen task Heads",
        "timing_scope": "native indexed dispatch or full fanout with result collection; excludes IO and reference validation",
        "memory_scope": "self proc resident/anonymous pages, including inputs, raw artifacts, private Heads and allocator",
        "wait4_memory_used_as_resident": False, "mode": "SHADOW_ONLY", "authority": "DENY_ALL",
        "task_admission_allowed": False, "action_execution_allowed": False, "production_activation_allowed": False,
        "native_encoder_executed": False, "new_training_or_calibration": False,
        "new_independent_quality_trial": False, "full_policy_learning_qualified": False,
        "independent_tasks_demonstrated": False, "encoder_sharing_cost_measured": False,
        "architecture_cost_ranking_established": False,
        "target_device_qualified": False, "energy_joules": None}
    with (target / "report.json").open("xb") as stream:
        stream.write(canonical(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("p40-directory", "binary", "output", "expected-report", "expected-binary", "expected-source"):
        parser.add_argument("--" + key, required=True)
    args = parser.parse_args()
    report = run_pool(args.p40_directory, args.binary, args.output, expected_report=args.expected_report,
                      expected_binary=args.expected_binary, expected_source=args.expected_source)
    print(json.dumps({"status": report["status"], "experiments": len(report["experiments"]),
                      "report_path": str(Path(args.output) / "report.json")}))


if __name__ == "__main__":
    main()
