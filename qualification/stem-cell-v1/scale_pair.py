"""Read-only, paired, same-host Stem Cell resource/latency comparison.

Never authenticates user-supplied native traces, owner identity, model weights,
WAL durability or an independent learning outcome. Every report denies any
production admission, even when an apparent speedup is statistically positive.
"""

import argparse
from collections import defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path
import random
import statistics

from scale import file_sha256, trace_report
from study import load_jsonl, quantile

SCHEMA = "hepta.stem-cell-paired-scale-precheck.v1"
RUN_SCHEMA = "hepta.stem-cell-run-provenance.v1"
REQUIRED_HOST = frozenset({
    "schema", "arm", "hardware_digest", "binary_digest", "dataset_digest",
    "model_digest", "run_id", "execution_profile", "capture_kind",
})
ARMS = ("no_change", "candidate")
MAX_GROUPS = 4096
MIN_GROUPS_FOR_CI = 30
BOOTSTRAP_REPLICATES = 2000


def _digest(value):
    return (type(value) is str and len(value) == 64 and
            all(c in "0123456789abcdef" for c in value))


def _canonical_digest(value):
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


def _check_manifest(value, arm):
    if type(value) is not dict or set(value) != REQUIRED_HOST or value["schema"] != RUN_SCHEMA:
        raise ValueError("incomplete or unregistered host provenance")
    if value["arm"] != arm or value["capture_kind"] != "native_owner_trace_unattested":
        raise ValueError("unknown or falsely attested trace arm")
    for key in ("hardware_digest", "binary_digest", "dataset_digest", "model_digest"):
        if not _digest(value[key]):
            raise ValueError("invalid host, binary, data or model digest")
    if type(value["run_id"]) is not str or not 0 < len(value["run_id"]) <= 128:
        raise ValueError("unbounded or missing run ID")
    profile = value["execution_profile"]
    if (type(profile) is not dict or set(profile) != {
            "device", "threads", "governor", "warmup_policy", "measurement_policy"} or
            type(profile["threads"]) is not int or not 1 <= profile["threads"] <= 4096 or
            any(type(profile[key]) is not str or not 0 < len(profile[key]) <= 128 for key in
                ("device", "governor", "warmup_policy", "measurement_policy"))):
        raise ValueError("invalid or non-comparable execution profile")
    return value


def _request_index(workload):
    if type(workload) is not list or not workload:
        raise ValueError("empty workload")
    index = {}
    for r in workload:
        if type(r) is not dict or type(r.get("request_id")) is not str:
            raise ValueError("invalid request identity")
        if r["request_id"] in index:
            raise ValueError("duplicate request")
        index[r["request_id"]] = r
    return index


def _request_trace(trace):
    indexed = {}
    for event in trace:
        if type(event) is not dict or "kind" not in event:
            raise ValueError("invalid trace event")
        if event["kind"] == "request":
            rid = event.get("request_id")
            if type(rid) is not str or rid in indexed:
                raise ValueError("duplicate or invalid request trace")
            indexed[rid] = event
    return indexed


def _arm_stats(observations):
    # These are only request-reported numbers, NOT process CPU/RSS attestation.
    records = list(observations.values())
    latencies = [(v["end_us"] - v["enqueued_us"]) / 1000 for v in records]
    start = min(v["enqueued_us"] for v in records)
    end = max(v["end_us"] for v in records)
    elapsed = end - start
    return {
        "p50_e2e_ms": quantile(latencies, .5),
        "p95_e2e_ms": quantile(latencies, .95),
        "p99_e2e_ms": quantile(latencies, .99),
        "mean_e2e_ms": statistics.fmean(latencies),
        "request_attributed_cpu_seconds": sum(v["cpu_us"] for v in records) / 1_000_000,
        "peak_reported_rss_bytes": max(v["rss_bytes"] for v in records),
        "trace_window_s": elapsed / 1_000_000,
        "requests_per_second_unattested": (len(records) * 1_000_000 / elapsed)
                                         if elapsed else None,
    }


def _cluster_ci(workload_index, baseline, candidate, seed, replicates):
    clusters = defaultdict(list)
    for request_id in sorted(workload_index):
        r = workload_index[request_id]
        key = (r["scope"], r["generation"], r["family"], r["input_key"])
        before, after = baseline[request_id], candidate[request_id]
        delta = ((before["end_us"] - before["enqueued_us"]) -
                 (after["end_us"] - after["enqueued_us"])) / 1000
        clusters[key].append(delta)
    count = len(clusters)
    if count > MAX_GROUPS:
        raise ValueError("too many distinct source clusters")
    if count < MIN_GROUPS_FOR_CI:
        return {"source_groups": count, "bootstrap_lcb_ms": None,
                "bootstrap_ucb_ms": None, "reliable_paired_ci_available": False}
    means = [statistics.fmean(values) for _, values in sorted(clusters.items())]
    rng = random.Random(seed)
    results = []
    for _ in range(replicates):
        results.append(sum(means[rng.randrange(count)] for _ in range(count)) / count)
    results.sort()
    return {"source_groups": count, "group_weighted_mean_gain_ms": statistics.fmean(means),
            "bootstrap_lcb_ms": quantile(results, .025),
            "bootstrap_ucb_ms": quantile(results, .975),
            "reliable_paired_ci_available": True}


def compare(baseline_workload, candidate_workload, baseline_trace, candidate_trace,
            baseline_manifest, candidate_manifest, *, replicates=BOOTSTRAP_REPLICATES):
    """Compare two complete and identically scoped workloads, never a promotion."""
    if type(replicates) is not int or not 1000 <= replicates <= 10000:
        raise ValueError("bootstrap resolution outside frozen bounds")
    left, right = (_check_manifest(baseline_manifest, ARMS[0]),
                   _check_manifest(candidate_manifest, ARMS[1]))
    if left["run_id"] == right["run_id"]:
        raise ValueError("same run ID could replay the baseline trace")
    for key in ("hardware_digest", "binary_digest", "dataset_digest", "execution_profile"):
        if left[key] != right[key]:
            raise ValueError("baseline and candidate have incomparable host or run profiles")
    old, new = _request_index(baseline_workload), _request_index(candidate_workload)
    if old.keys() != new.keys():
        raise ValueError("unpaired request IDs")
    for rid in old:
        first, second = old[rid], new[rid]
        for item in (first, second):
            if not _digest(item.get("model_digest")):
                raise ValueError("unbound request model")
        if first["model_digest"] != left["model_digest"] or second["model_digest"] != right["model_digest"]:
            raise ValueError("workload model mismatches frozen run provenance")
        if {k: v for k, v in first.items() if k != "model_digest"} != {
                k: v for k, v in second.items() if k != "model_digest"}:
            raise ValueError("baseline/candidate workload drift")
    # Call the strict native-v2 internal consistency validator for EACH arm.
    old_report = trace_report(baseline_workload, baseline_trace)
    new_report = trace_report(candidate_workload, candidate_trace)
    if (old_report["schema"] != "hepta.stem-cell-scale-observation.v2" or
            new_report["schema"] != old_report["schema"] or
            old_report["native_worker_attested"] is not False or
            new_report["native_worker_attested"] is not False or
            old_report["production_authorized"] is not False or
            new_report["production_authorized"] is not False):
        raise ValueError("untrusted trace analyzer schema or authority escalation")
    before, after = _request_trace(baseline_trace), _request_trace(candidate_trace)
    if before.keys() != old.keys() or after.keys() != old.keys():
        raise ValueError("incomplete paired native trace")
    if any(event["status"] != "ok" for event in (*before.values(), *after.values())):
        raise ValueError("failed or rejected requests cannot disappear from the paired comparison")
    pair_seed = int(_canonical_digest({"baseline": baseline_workload,
                                       "candidate": candidate_workload})[:16], 16)
    ci = _cluster_ci(old, before, after, pair_seed, replicates)
    before_stats, after_stats = _arm_stats(before), _arm_stats(after)
    return {
        "schema": SCHEMA, "kind": "read_only_paired_diagnostic",
        "baseline_run_id": left["run_id"], "candidate_run_id": right["run_id"],
        "scenario": baseline_workload[0]["scenario"],
        "baseline_model_digest": left["model_digest"],
        "candidate_model_digest": right["model_digest"],
        "hardware_digest_unverified": left["hardware_digest"],
        "baseline": before_stats, "candidate": after_stats,
        "baseline_trace_diagnostic": old_report,
        "candidate_trace_diagnostic": new_report,
        "paired_bootstrap": ci,
        "p99_e2e_gain_ms_unattested": (before_stats["p99_e2e_ms"] - after_stats["p99_e2e_ms"]),
        "request_cpu_saving_seconds_unattested": (before_stats["request_attributed_cpu_seconds"] -
                                                   after_stats["request_attributed_cpu_seconds"]),
        "peak_rss_saving_bytes_unattested": (before_stats["peak_reported_rss_bytes"] -
                                            after_stats["peak_reported_rss_bytes"]),
        "source_manifest_sha256": [_canonical_digest(left), _canonical_digest(right)],
        "source_workload_sha256": [_canonical_digest(baseline_workload),
                                   _canonical_digest(candidate_workload)],
        "source_trace_sha256": [_canonical_digest(baseline_trace), _canonical_digest(candidate_trace)],
        "independently_verified_native_execution": False,
        "hardware_observer_authenticated": False,
        "wal_and_crash_recovery_independently_verified": False,
        "independent_ndu_or_negative_transfer_available": False,
        "production_authorized": False,
        "shadow_eligible": False,
    }


def _read_json(path):
    with Path(path).open("rb") as source:
        raw = source.read(64 * 1024 + 1)
    if not raw or len(raw) > 64 * 1024:
        raise ValueError("missing or oversized host run manifest")
    try:
        raw = raw.decode("utf-8")
    except UnicodeError as error:
        raise ValueError("invalid run manifest UTF-8") from error
    def unique(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError("duplicate JSON object key")
            result[name] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pair real owner traces without granting authority")
    for arm in ARMS:
        parser.add_argument(f"--{arm.replace('_', '-')}-workload", required=True)
        parser.add_argument(f"--{arm.replace('_', '-')}-trace", required=True)
        parser.add_argument(f"--{arm.replace('_', '-')}-manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    inputs = [getattr(args, f"{arm}_{kind}") for arm in ARMS
              for kind in ("workload", "trace", "manifest")]
    hashes = [file_sha256(p) for p in inputs]
    first, second = ((list(load_jsonl(args.no_change_workload)), list(load_jsonl(args.no_change_trace)),
                      _read_json(args.no_change_manifest)),
                     (list(load_jsonl(args.candidate_workload)), list(load_jsonl(args.candidate_trace)),
                      _read_json(args.candidate_manifest)))
    if any(file_sha256(path) != digest for path, digest in zip(inputs, hashes)):
        raise ValueError("paired sources changed during read")
    report = compare(first[0], second[0], first[1], second[1], first[2], second[2])
    report["source_file_sha256"] = hashes
    content = json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n"
    with Path(args.output).open("x", encoding="utf-8") as writer:
        writer.write(content)
    print("paired trace diagnostic only: production_authorized=false")


if __name__ == "__main__":
    main()
