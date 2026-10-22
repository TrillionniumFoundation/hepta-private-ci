"""Independently audit retained native pool bytes, measurements and references.

This stdlib checker never imports the pool runner or executes a Head. Source
identity is not compiler attestation. Resource observations remain head-only.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys

COUNTS = (1, 32, 256, 4096)
MODES = ("gated", "linear")
MEMORY_BYTES = 800 * 1024 * 1024
TOLERANCE = 2e-5
P40_REPORT = "22e4560ca4ff2b1c604267c92aed71bbf1417e612018c6760930633ca52395e6"
SOURCE_FILES = {"codex-rs/hepta-neuron/examples/native_task_head_pool.rs",
    "codex-rs/hepta-neuron/src/task_head_native.rs", "codex-rs/hepta-neuron/src/lib.rs",
    "qa/stem-bakeoff/native_task_head_pool.py", "qa/stem-bakeoff/replay_native_task_head_v1.py"}
FALSE_CLAIMS = ("task_admission_allowed", "action_execution_allowed", "native_encoder_executed",
    "new_training_or_calibration", "new_independent_quality_trial", "target_device_qualified")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def checked(path, pin=None, limit=512 * 1024):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "regular non-symlink input required")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit and (pin is None or digest(raw) == pin), "byte bound or digest: " + str(path))
    return raw


def prediction_error(actual, reference):
    require(set(actual) == set(reference), "prediction field inventory")
    for key in ("mode", "authority", "accepted", "predicted_class"):
        require(type(actual[key]) is type(reference[key]) and actual[key] == reference[key],
                "prediction decision differs: " + key)
    error = 0.0
    for key in ("task_logits", "task_probabilities", "gate"):
        left, right = ([actual[key]], [reference[key]]) if key == "gate" else (actual[key], reference[key])
        require(len(left) == len(right), "prediction width")
        for value, prior in zip(left, right):
            require(type(value) in (int, float) and type(prior) in (int, float)
                    and math.isfinite(value) and math.isfinite(prior), "nonfinite prediction")
            error = max(error, abs(value - prior))
    require(error <= TOLERANCE, "prediction exceeds fixed absolute tolerance")
    return error


def check_samples(data, summary):
    for metric, count in (("dispatch", 4096), ("fanout", 16)):
        ns = data[metric + "_nanoseconds"]
        require(len(ns) == count and all(type(v) is int and v > 0 for v in ns), "raw sample inventory/type")
        expected = {"samples": count, "median_ms": statistics.median(ns) / 1e6,
                    "max_ms": max(ns) / 1e6, "raw_nanoseconds_sha256": digest(canonical(ns))}
        if metric == "dispatch":
            ordered = sorted(ns)
            for quantile in (50, 95, 99):
                expected[f"p{quantile}_ms"] = ordered[math.ceil(quantile * count / 100) - 1] / 1e6
        require(summary["timings"][metric] == expected, "recomputed timing summary differs")
    elapsed = data["elapsed_nanoseconds"]
    allocation, warmup = data["allocation_nanoseconds"], data["warmup_nanoseconds"]
    require(all(type(v) is int and v > 0 for v in (elapsed, allocation, warmup)), "invalid elapsed duration")
    require(allocation + warmup + sum(data["dispatch_nanoseconds"]) + sum(data["fanout_nanoseconds"])
            <= elapsed < 90 * 10**9, "native execution duration budget")
    require((summary["allocation_ms"], summary["warmup_ms"], summary["native_elapsed_ms"])
            == (allocation / 1e6, warmup / 1e6, elapsed / 1e6), "duration units differ")


def check_child(data, summary, count, artifact, request_sha, references):
    require(data["schema"] == "hepta.native-task-head-pool.v1" and data["status"] == "PASS", "native execution incomplete")
    require(data["cells"] == data["resident_heads"] == summary["cells"] == count, "resident count differs")
    require(data["independently_trained_templates"] == 1, "replica scope differs")
    require(data["weights_bytes_per_head"] == summary["weights_bytes_per_head"] == artifact["weights_bytes"], "per-Head bytes")
    require(data["private_weights_payload_bytes"] == summary["private_weights_payload_bytes"]
            == count * artifact["weights_bytes"], "private payload differs")
    for key in ("manifest_sha256", "weights_sha256"):
        require(data[key] == artifact[key], "Head source differs")
    require(data["request_stream_sha256"] == request_sha and data["input_rows"] == 256, "input identity")
    require(data["dispatch_calls_per_head"] == [4096 // count] * count, "unvisited or uneven private Head")
    require(data["warmup_calls"] == data["fanout_predictions_per_sample"] == count, "execution schedule")
    require(data["validation_extra_reference_calls"] == 272
            and data["reference_validation_outside_measurement"] is True, "reference timing scope")
    require(len(references) == len(data["reference_predictions"]) == 256, "reference row inventory")
    require(data["reference_source_record_digests"] == [r["source_record_digest"] for r in references], "reference source ordering")
    maximum_error = max(prediction_error(pred, row["prediction"])
                        for pred, row in zip(data["reference_predictions"], references))
    require(summary["max_prediction_error_vs_p40"] == maximum_error, "reference error summary")
    require(summary["reference_predictions_sha256"] == digest(canonical(data["reference_predictions"])), "prediction digest")
    require(data["address_space_hard_limit_bytes"] == data["rss_budget_bytes"] == MEMORY_BYTES, "memory enforcement")
    prior_peak, process = 0, None
    for phase in ("baseline", "post_load", "post_warmup", "post_measurement"):
        memory = data[phase]
        require(memory == summary[phase] and memory["source"] == "native /proc/self/status", "memory source/summary")
        for key in ("proc_self_pid", "getpid", "rss_bytes", "rss_anon_bytes", "post_exec_peak_rss_bytes", "virtual_bytes"):
            require(type(memory[key]) is int and memory[key] >= 0, "memory value/units")
        observed_process = (memory["proc_self_pid"], memory["getpid"])
        require(all(p > 0 for p in observed_process) and (process is None or process == observed_process), "process identity changed")
        process = observed_process
        peak = memory["post_exec_peak_rss_bytes"]
        require(0 <= memory["rss_anon_bytes"] <= memory["rss_bytes"] <= peak <= MEMORY_BYTES
                and prior_peak <= peak and memory["virtual_bytes"] <= MEMORY_BYTES, "resident/peak/virtual budget")
        prior_peak = peak
    require(all(data[key] is False for key in FALSE_CLAIMS), "native scope or authority upgraded")
    require(data["mode"] == "SHADOW_ONLY" and data["authority"] == "DENY_ALL" and data["energy_joules"] is None, "native research scope")
    check_samples(data, summary)
    return maximum_error


def audit(args):
    root, repository, p40_root = Path(args.directory), Path(args.repository).resolve(), Path(args.p40_directory)
    raw = checked(root / "report.json", args.report_sha)
    report = json.loads(raw)
    plan_raw = checked(root / "plan.json", report["plan_sha256"])
    plan, source = json.loads(plan_raw), report["source_identity"]
    require(report["status"] == "PASS" and source == plan["source_identity"], "report/plan identity")
    require(source["git_head_sha"] == args.source and source["working_tree_clean"] is True, "measurement source")
    require(set(source["source_file_sha256"]) == SOURCE_FILES, "measurement source inventory")
    def git(*words):
        return subprocess.check_output(["git", "--no-optional-locks", "-C", str(repository), *words])
    require(git("rev-parse", args.source + "^{tree}").decode().strip() == source["git_tree_sha"], "source tree")
    for path, pin in source["source_file_sha256"].items():
        require(digest(git("show", args.source + ":" + path)) == pin, "source blob differs")
    checker_path = Path(__file__).resolve()
    checker_relative = checker_path.relative_to(repository).as_posix()
    checker_head = git("rev-parse", "HEAD").decode().strip()
    require(not git("status", "--porcelain").strip(), "checker checkout must be clean")
    checker_sha = digest(checked(checker_path))
    require(digest(git("show", checker_head + ":" + checker_relative)) == checker_sha, "checker source blob")
    binary = checked(args.binary, report["native_binary_sha256"], 32 * 1024 * 1024)
    require(report["native_binary_sha256"] == plan["native_binary_sha256"], "binary plan identity")
    p40 = json.loads(checked(p40_root / "native-results/report.json", P40_REPORT))
    require(report["p40_report_sha256"] == plan["p40_report_sha256"] == P40_REPORT, "original P40 reference")
    stream = checked(root / "requests.jsonl", report["request_stream_sha256"], 32 * 1024 * 1024)
    request_sha = digest(stream)
    require(plan["request_stream_sha256"] == request_sha and plan["input_stream_bytes"] == len(stream), "request stream plan")
    lines = stream.splitlines(keepends=True)
    require(len(lines) == 256 and all(line.endswith(b"\n") and len(line) <= 256 * 1024 for line in lines), "request row bounds")
    requests = [json.loads(line) for line in lines]
    order = [f"{mode}-{count}" for mode in MODES for count in COUNTS]
    retained = {name + suffix for name in order for suffix in (".json", ".stderr")}
    expected_files = retained | {f"{mode}-head/{part}" for mode in MODES for part in ("manifest.json", "weights.f32le")}
    expected_files |= {"plan.json", "report.json", "requests.jsonl"}
    if (root / "native_task_head_pool.bin").exists():
        checked(root / "native_task_head_pool.bin", digest(binary), 32 * 1024 * 1024)
        expected_files.add("native_task_head_pool.bin")
    require({p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} == expected_files, "unindexed or missing pool artifact")
    require(report["execution_order"] == order and set(report["experiments"]) == set(order)
            and set(report["retained_file_sha256"]) == retained, "eight-case inventory/order")
    require((plan["counts"], plan["template_modes"], plan["dispatch_samples"], plan["fanout_samples"])
            == (list(COUNTS), list(MODES), 4096, 16), "fixed sample plan")
    require(plan["child_seconds"] == 90 and plan["total_seconds"] == 720 and plan["memory_bytes"] == MEMORY_BYTES
            and plan["absolute_tolerance"] == TOLERANCE and 0 < report["total_wall_seconds"] <= 720, "fixed execution budgets")
    records = {}
    for mode in MODES:
        artifact = report["artifacts"][mode]
        manifest = json.loads(checked(root / f"{mode}-head/manifest.json", artifact["manifest_sha256"]))
        weights = checked(root / f"{mode}-head/weights.f32le", manifest["weights_sha256"])
        for part in ("manifest.json", "weights.f32le"):
            name = f"{mode}-head/{part}"
            require(checked(root / name) == checked(p40_root / "native-results" / name, p40["retained_file_sha256"][name]), "Head changed from P40")
        require(len(weights) == manifest["weights_bytes"] == artifact["weights_bytes"] == 135256, "frozen Head layout")
        require(manifest["temperature"] == 0.25 and manifest["confidence_threshold"] == 0.7
                and manifest["required_present_mask"] == 3 and manifest["state_contract"] == "zero_state_only", "frozen Head contract")
        paired_name = f"{mode}-paired.jsonl"
        paired = [json.loads(line) for line in checked(p40_root / "native-results" / paired_name,
                  p40["retained_file_sha256"][paired_name]).splitlines()]
        require(len(paired) == 256 and p40["cases"][mode + "-paired"]["request_stream_sha256"] == request_sha, "reference stream")
        for row, line, request in zip(paired, lines, requests):
            require(row["request_sha256"] == digest(line) and row["source_record_digest"] == request["source_record_digest"], "per-row request binding")
            require(request["identity"] == manifest["feature_identity"] and request["present_mask"] == 3
                    and len(request["features"]) == 3073 and all(math.isfinite(v) for v in request["features"]), "paired feature contract")
        prior_predictions = None
        for count in COUNTS:
            name = f"{mode}-{count}"
            summary = report["experiments"][name]
            require(summary["raw_file"] == name + ".json" and summary["stderr_file"] == name + ".stderr", "raw artifact names")
            data_raw = checked(root / summary["raw_file"], report["retained_file_sha256"][summary["raw_file"]])
            require(digest(data_raw) == summary["raw_file_sha256"], "raw summary digest")
            require(checked(root / summary["stderr_file"], report["retained_file_sha256"][summary["stderr_file"]]) == b"", "native stderr")
            data = json.loads(data_raw)
            error = check_child(data, summary, count, artifact, request_sha, paired)
            require(data["input_stream_bytes"] == len(stream), "native input byte count")
            require(prior_predictions is None or data["reference_predictions"] == prior_predictions, "pool size changed predictions")
            prior_predictions = data["reference_predictions"]
            records[name] = {"raw_sha256": digest(data_raw), "resident_heads": count,
                "max_prediction_error_vs_p40": error, "dispatch_samples": 4096, "fanout_samples": 16,
                "private_payload_bytes": count * len(weights), "post_load": data["post_load"]}
    require(all(report[key] is False for key in FALSE_CLAIMS + ("production_activation_allowed",
        "full_policy_learning_qualified", "independent_tasks_demonstrated", "encoder_sharing_cost_measured",
        "architecture_cost_ranking_established", "wait4_memory_used_as_resident")), "report scope upgraded")
    require(report["mode"] == "SHADOW_ONLY" and report["authority"] == "DENY_ALL"
            and report["energy_joules"] is None and report["independently_trained_templates_total"] == 2, "report research scope")
    return {"schema": "hepta.native-pool-ci-audit.v1", "status": "PASS", "report_sha256": digest(raw),
        "plan_sha256": digest(plan_raw), "measurement_source_identity": source,
        "checker_source_identity": {"git_head_sha": checker_head, "git_tree_sha": git("rev-parse", "HEAD^{tree}").decode().strip(),
            "working_tree_clean": True, "path": checker_relative, "sha256": checker_sha},
        "binary_sha256": digest(binary), "compiler_attestation_independently_verified": False,
        "p40_report_sha256": P40_REPORT, "request_stream_sha256": request_sha, "request_rows_rehashed": 256,
        "reference_predictions_compared": 2048, "absolute_tolerance": TOLERANCE,
        "raw_dispatch_samples_checked": 32768, "raw_fanout_samples_checked": 128, "experiments": records,
        "total_native_prediction_calls": sum(256 + n + 4096 + 16 * n + 16 for n in COUNTS) * 2,
        "audit_reran_measurement": False, "head_only": True, "target_device_qualified": False,
        "energy_joules": None, "new_independent_quality_trial": False, "authority": "DENY_ALL",
        "command_argv": [sys.executable, str(checker_path), *sys.argv[1:]]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("directory", "report-sha", "repository", "source", "binary", "p40-directory", "output"):
        parser.add_argument("--" + key, required=True)
    args = parser.parse_args()
    result = audit(args)
    with Path(args.output).open("xb") as stream:
        stream.write(canonical(result))
    print(json.dumps({"status": result["status"], "receipt": args.output,
                      "sha256": digest(canonical(result)), "head_only": True}))
