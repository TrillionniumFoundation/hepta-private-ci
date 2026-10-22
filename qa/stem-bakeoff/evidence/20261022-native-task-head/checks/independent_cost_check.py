#!/usr/bin/env python3
"""Recompute retained native cost statistics; no benchmark is rerun."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pinned(path, digest):
    with path.open("rb") as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    require(len(raw) <= 2 * 1024 * 1024 and sha(raw) == digest, "file pin/budget differs: " + str(path))
    return raw


def audit(args):
    root = Path(args.directory).resolve(strict=True) / "native-results"
    repository = Path(args.repository).resolve(strict=True)
    report_raw = pinned(root / "report.json", args.expected_report_sha256)
    report = json.loads(report_raw)
    source = report["source_identity"]
    require(source["git_head_sha"] == args.expected_source_sha
            and source["git_tree_sha"] == args.expected_tree_sha
            and source["working_tree_clean"] is True,
            "final report source identity differs")
    require(report["binary_sha256"] == args.expected_binary_sha256,
            "final report binary differs")
    git = lambda *tail: subprocess.check_output(["git", "-C", str(repository), *tail])
    require(git("rev-parse", args.expected_source_sha + "^{tree}").decode().strip() == args.expected_tree_sha,
            "local committed source/tree object differs")
    committed_sources = {}
    for name, expected in source["native_source_sha256"].items():
        path = "codex-rs/hepta-neuron/" + name
        raw = git("show", args.expected_source_sha + ":" + path)
        require(sha(raw) == expected, "committed native source differs")
        committed_sources[path] = sha(raw)
    for name, field in (("export_native_task_head_v1.py", "exporter_source_sha256"),
                        ("replay_native_task_head_v1.py", "replay_source_sha256")):
        path = "qa/stem-bakeoff/" + name
        raw = git("show", args.expected_source_sha + ":" + path)
        require(sha(raw) == source[field], "committed native bridge source differs")
        committed_sources[path] = sha(raw)
    path = "qa/stem-bakeoff/native_task_head_cost.py"
    cost_source_digest = sha(git("show", args.expected_source_sha + ":" + path))
    committed_sources[path] = cost_source_digest
    observation_raw = pinned(Path(args.parity_observation), args.expected_parity_observation_sha256)
    observation = json.loads(observation_raw)
    require(observation["status"] == "PASS" and observation["native_report_sha256"] == args.expected_report_sha256
            and observation["retained_file_count"] == 16 and observation["response_rows_verified"] == 2560
            and observation["native_binary_independently_hashed"]["sha256"] == args.expected_binary_sha256,
            "independent parity observation is not for this final release")
    summaries = {}
    for mode in ("gated", "linear"):
        name = mode + "-cost.json"
        raw = pinned(root / name, report["retained_file_sha256"][name])
        cost = json.loads(raw)
        manifest_name = mode + "-head/manifest.json"
        manifest_raw = pinned(root / manifest_name, report["retained_file_sha256"][manifest_name])
        manifest = json.loads(manifest_raw)
        require(cost["schema"] == "hepta.native-task-head-cost.v1"
                and cost["status"] == "MEASURED_RESEARCH_ONLY", "cost schema/status differs")
        require(cost["source_identity"] == source and cost["cost_source_sha256"] == cost_source_digest,
                "cost executed source differs from final source")
        require(cost["native_binary_sha256"] == args.expected_binary_sha256
                and cost["manifest_sha256"] == sha(manifest_raw)
                and cost["weights_sha256"] == manifest["weights_sha256"]
                and cost["feature_identity"] == manifest["feature_identity"]
                and cost["requests_sha256"] == report["cases"][mode + "-paired"]["request_stream_sha256"],
                "cost binary/artifact/input binding differs")
        require(cost["warmup_rows"] == 20 and cost["measured_rows"] == 1000
                and cost["input_rows"] == cost["complete_input_rows"] == cost["distinct_executed_requests"] == 256
                and cost["missing_input_rows_excluded_before_measurement"] == 0,
                "warmup, input, or measurement inventory differs")
        response_name = mode + "-paired.jsonl"
        paired_raw = pinned(root / response_name, report["retained_file_sha256"][response_name])
        paired = [json.loads(line) for line in paired_raw.splitlines()]
        request_sequence = b"".join(bytes.fromhex(paired[index % 256]["request_sha256"])
                                     for index in range(20, 1020))
        require(sha(request_sequence) == cost["measured_ordered_request_digests_sha256"],
                "cost request order differs from retained parity input order")
        latency = cost["latency"]
        ns = latency["raw_nanoseconds"]
        require(len(ns) == 1000 and all(type(value) is int and value > 0 for value in ns),
                "raw latency sample inventory differs")
        ordered = sorted(ns)
        recomputed = {f"p{p}_ms": ordered[math.ceil(1000 * p / 100) - 1] / 1e6 for p in (50, 95, 99)}
        recomputed["mean_ms"] = sum(ns) / 1000 / 1e6
        require(latency["quantile_method"] == "nearest_rank"
                and all(abs(latency[key] - value) <= 1e-12 for key, value in recomputed.items()),
                "reported latency statistics differ from raw samples")
        require(cost["measurement_loop_wall_ms_including_validation"] >= sum(ns) / 1e6,
                "measurement loop wall duration is smaller than timed work")
        require(cost["native_rss_source"] == "proc status verified by PPid/NSpid/exe/starttime; Linux kB times 1024",
                "RSS source was relabelled")
        for key in ("native_rss_after_warmup", "native_rss_after_measurement"):
            sample = cost[key]
            require(sample["reason"] is None and type(sample["rss_bytes"]) is int
                    and 0 < sample["rss_bytes"] <= sample["post_exec_peak_rss_bytes"]
                    and sample["rss_bytes"] % 1024 == sample["post_exec_peak_rss_bytes"] % 1024 == 0,
                    "RSS sample/units or proc identity result differs")
        require(cost["native_rss_after_measurement"]["post_exec_peak_rss_bytes"]
                >= cost["native_rss_after_warmup"]["post_exec_peak_rss_bytes"], "post-exec peak decreased")
        require(cost["wait4_peak_may_include_pre_exec_parent_memory"] is True
                and cost["wait4_peak_is_native_resident_memory"] is False,
                "wait4 lifetime peak misrepresented as native resident memory")
        require(cost["target_device_qualified"] is False and cost["energy_joules"] is None
                and cost["production_activation_allowed"] is False
                and cost["task_admission_allowed"] is False and cost["action_execution_allowed"] is False
                and cost["authority"] == "DENY_ALL" and cost["mode"] == "SHADOW_ONLY"
                and cost["encoder_calls"] == 0 and cost["policy_actions_measured"] is False
                and cost["source_metadata_is_compiler_attestation"] is False,
                "cost scope/authority exceeds research task-only measurement")
        summaries[mode] = {"cost_file_sha256": sha(raw), "raw_samples": len(ns),
            "raw_sample_list_sha256": sha(json.dumps(ns, separators=(",", ":")).encode()),
            "recomputed_latency": recomputed,
            "ordered_request_sequence_digest_verified": sha(request_sequence),
            "native_rss_after_warmup": cost["native_rss_after_warmup"],
            "native_rss_after_measurement": cost["native_rss_after_measurement"],
            "wait4_lifetime_peak_not_native_resident_bytes": cost["wait4_process_lifetime_peak_rss_bytes"],
            "measurement_loop_wall_ms": cost["measurement_loop_wall_ms_including_validation"]}
    return {"schema": "hepta.native-task-independent-cost-observation.v1", "status": "PASS",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(), "read_only": True,
        "benchmark_rerun": False, "new_training_or_quality_trial": False,
        "native_report_sha256": args.expected_report_sha256, "native_binary_sha256": args.expected_binary_sha256,
        "source_commit": args.expected_source_sha, "source_tree": args.expected_tree_sha,
        "committed_source_file_sha256_verified": committed_sources,
        "parity_observation_sha256": args.expected_parity_observation_sha256,
        "parity_observation_path": args.parity_observation, "costs": summaries,
        "closed_child_process_identity_reobserved_by_auditor": False,
        "rss_evidence": "recorded observations from the hash-bound PPid/NSpid/exe/starttime-checked code path",
        "scope": "descriptive round-trip measurement of one resident native task Head on this shared Linux host",
        "target_device_qualified": False, "energy_joules": None,
        "full_encoder_or_policy_cost_measured": False,
        "architecture_cost_ranking_established": False,
        "compiler_attestation_independently_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("directory", "repository", "expected-report-sha256", "expected-binary-sha256",
                 "expected-source-sha", "expected-tree-sha", "parity-observation",
                 "expected-parity-observation-sha256", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    source_digest = sha(Path(__file__).read_bytes())
    receipt = audit(args)
    require(source_digest == sha(Path(__file__).read_bytes()), "checker source changed during audit")
    receipt.update({"checker_source_sha256": source_digest, "checker_path": str(Path(__file__).resolve()),
        "command_argv": [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]})
    raw = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    with Path(args.output).open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"status": "PASS", "receipt_path": args.output, "receipt_sha256": sha(raw),
                      "checker_source_sha256": source_digest, "costs": receipt["costs"]}, sort_keys=True))


if __name__ == "__main__":
    main()
