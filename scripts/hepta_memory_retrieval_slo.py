#!/usr/bin/env python3
"""Validate real Agentd E2E samples; never turn microbenchmarks into product evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import subprocess

STAGES = (
    "sqlite_observation", "snapshot_binding", "candidate_adaptation", "hnmf_settling",
    "downstream_ranker", "final_revalidation", "text_materialization", "context_plan",
    "learning_assignment_append",
)
CASE_FIELDS = ("cache", "concurrency", "owner_write_contention", "provider_rotation_contention")
COUNTERS = ("cpu_us", "peak_rss_bytes", "allocation_count", "sqlite_read_count",
            "candidate_count", "node_count", "synapse_count", "traversed_synapses")
SHA = re.compile(r"[0-9a-f]{40}\Z")


class SloError(ValueError):
    pass


def integer(value, name, minimum=0):
    if type(value) is not int or not minimum <= value <= (1 << 63) - 1:
        raise SloError(f"{name} must be a measured bounded integer >= {minimum}")
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SloError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def object_value(value, name):
    if not isinstance(value, dict):
        raise SloError(f"{name} must be an object")
    return value


def exact_sha(value, name):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise SloError(f"{name} must be an exact lowercase Git SHA")
    return value


def bind_source(root, head):
    """Observe the actual clean checkout, not a caller-provided tree label."""
    exact_sha(head, "head")

    def git(*args):
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                                text=True, timeout=30, check=False)
        if result.returncode:
            raise SloError(f"source observation failed: git {args[0]}")
        return result.stdout.strip()

    if git("rev-parse", "HEAD") != head:
        raise SloError("SLO source head is not the current checkout")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise SloError("SLO source checkout is not clean")
    tree = exact_sha(git("rev-parse", "HEAD^{tree}"), "tree")
    parents = git("show", "-s", "--format=%P", "HEAD").split()
    for parent in parents:
        exact_sha(parent, "parent")
    return {"commit": head, "tree": tree, "parents": parents}


def load(path):
    with Path(path).open("rb") as stream:
        data = stream.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024:
        raise SloError("sample input exceeds 64 MiB")
    def invalid_constant(value):
        raise SloError(f"invalid JSON number: {value}")
    return json.loads(data, object_pairs_hook=unique_object, parse_constant=invalid_constant)


def percentiles(values):
    values = sorted(values)
    if not values:
        raise SloError("no measurements")
    return {f"p{p}_us": values[max(0, math.ceil(len(values) * p / 100) - 1)]
            for p in (50, 95, 99)} | {"max_us": values[-1]}


def case_key(case):
    object_value(case, "workload")
    if case.get("cache") not in ("cold", "warm"):
        raise SloError("cache must be explicitly cold or warm")
    integer(case.get("concurrency"), "concurrency", 1)
    for field in CASE_FIELDS[2:]:
        if type(case.get(field)) is not bool:
            raise SloError(f"missing contention dimension: {field}")
    return tuple(case[field] for field in CASE_FIELDS)


def validate(document, policy, head, tree):
    object_value(document, "samples document")
    object_value(policy, "SLO policy")
    exact_sha(head, "head")
    exact_sha(tree, "tree")
    if document.get("source_tree") != tree:
        raise SloError("samples do not bind the observed source tree")
    if document.get("source_head") != head:
        raise SloError("samples do not bind the requested exact source head")
    if document.get("schema") != "hepta.memory-retrieval.e2e-samples.v2":
        raise SloError("not an E2E sample document")
    if policy.get("schema") != "hepta.memory-retrieval.slo-policy.v1":
        raise SloError("unknown SLO policy schema")
    if document.get("producer") != "agentd-product" or document.get("synthetic_fixture") is not False:
        raise SloError("fixtures and standalone microbenchmarks are not product samples")
    for field in ("host_profile", "measurement_run_id", "clock", "allocator_instrumentation", "sqlite_instrumentation"):
        if not isinstance(document.get(field), str) or not document[field].strip():
            raise SloError(f"missing measurement provenance: {field}")
    if document["host_profile"] != policy.get("host_profile"):
        raise SloError("measurements use another target host profile")
    if document.get("ranker_enabled") is not True or document.get("learning_sink_enabled") is not True:
        raise SloError("full-chain qualification requires the ranker and durable learning sink")
    cases = policy.get("required_cases")
    if not isinstance(cases, list):
        raise SloError("required_cases must be an array")
    required = {case_key(case) for case in cases}
    if len(required) != len(cases):
        raise SloError("duplicate required workload")
    if not required:
        raise SloError("SLO policy must declare its workload matrix")
    minimum = integer(policy.get("minimum_samples_per_case"), "minimum_samples_per_case", 100)
    limits = object_value(policy.get("limits"), "limits")
    for metric in ("p95_us", "p99_us", "max_us", "peak_rss_bytes", "abstention_ppm", "stale_rejection_ppm"):
        integer(limits.get(metric), f"limit.{metric}")
    allowed_limits = {"p95_us", "p99_us", "max_us", "peak_rss_bytes", "abstention_ppm",
                      "stale_rejection_ppm", "cpu_us", "allocation_count", "sqlite_read_count"}
    for metric, limit in limits.items():
        if metric not in allowed_limits:
            raise SloError(f"unsupported SLO limit: {metric}")
        integer(limit, f"limit.{metric}")
        if metric.endswith("_ppm") and limit > 1_000_000:
            raise SloError(f"rate limit exceeds one million ppm: {metric}")
    samples = document.get("samples")
    if not isinstance(samples, list) or not 1 <= len(samples) <= 1_000_000:
        raise SloError("bounded nonempty raw samples are required")
    groups, identities = {}, set()
    for sample in samples:
        object_value(sample, "sample")
        sample_id = sample.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id or sample_id in identities:
            raise SloError("sample identities must be present and unique")
        identities.add(sample_id)
        key = case_key(sample)
        stages = object_value(sample.get("stages_us"), "stages_us")
        if set(stages) != set(STAGES):
            raise SloError("all nine exclusive pipeline stage measurements are required")
        total = integer(sample.get("total_us"), "total_us", 1)
        for stage in STAGES:
            integer(stages[stage], stage)
        if sum(stages.values()) > total:
            raise SloError("exclusive stage time exceeds end-to-end wall time")
        for counter in COUNTERS:
            integer(sample.get(counter), counter, 1 if counter == "peak_rss_bytes" else 0)
        for name, ceiling in (("candidate_count", 512), ("node_count", 4096),
                              ("synapse_count", 32768), ("traversed_synapses", 131072)):
            if sample[name] > ceiling:
                raise SloError(f"resource bound exceeded: {name}")
        for field in ("abstained", "stale_rejected"):
            if type(sample.get(field)) is not bool:
                raise SloError(f"missing observed outcome: {field}")
        groups.setdefault(key, []).append(sample)
    if not required.issubset(groups):
        raise SloError("required cold/warm, concurrency or contention case is missing")
    summaries, failures = [], []
    for key, rows in sorted(groups.items()):
        if len(rows) < minimum:
            raise SloError(f"insufficient observations for workload {key}")
        summary = dict(zip(CASE_FIELDS, key)) | percentiles([row["total_us"] for row in rows])
        summary.update({"samples": len(rows), "cpu_us": sum(row["cpu_us"] for row in rows),
                        "peak_rss_bytes": max(row["peak_rss_bytes"] for row in rows),
                        "allocation_count": sum(row["allocation_count"] for row in rows),
                        "sqlite_read_count": sum(row["sqlite_read_count"] for row in rows),
                        "abstention_ppm": (sum(row["abstained"] for row in rows) * 1_000_000 + len(rows) - 1) // len(rows),
                        "stale_rejection_ppm": (sum(row["stale_rejected"] for row in rows) * 1_000_000 + len(rows) - 1) // len(rows),
                        "stages": {stage: percentiles([row["stages_us"][stage] for row in rows]) for stage in STAGES},
                        "resource_maxima": {field: max(row[field] for row in rows) for field in COUNTERS[4:]}})
        for metric, limit in limits.items():
            if metric not in summary or type(summary[metric]) is not int:
                raise SloError(f"unsupported SLO limit: {metric}")
            if summary[metric] > limit:
                failures.append({"case": list(key), "metric": metric, "observed": summary[metric], "limit": limit})
        summaries.append(summary)
    return {
        "schema": "hepta.memory-retrieval.slo-receipt.v2", "source_head": head,
        "source_tree": tree, "rate_rounding": "ceiling_ppm",
        "host_profile": document["host_profile"], "measurement_run_id": document["measurement_run_id"],
        "sample_sha256": hashlib.sha256(canonical(document)).hexdigest(),
        "policy_sha256": hashlib.sha256(canonical(policy)).hexdigest(),
        "status": "failed" if failures else "passed", "failures": failures,
        "workloads": summaries, "sample_count": len(samples),
        "independentAcceptance": False, "productionImplementation": False,
        "activation": False, "release": False,
    }


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def retain(receipt, directory):
    """Content-addressed exclusive write; external retention remains an owner duty."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    data = canonical(receipt)
    path = directory / (hashlib.sha256(data).hexdigest() + ".json")
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_bytes() != data:
            raise SloError("existing content-addressed receipt differs") from None
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        source = bind_source(args.root, args.head)
        receipt = validate(load(args.samples), load(args.policy), args.head, source["tree"])
        if bind_source(args.root, args.head) != source:
            raise SloError("source changed during SLO validation")
        receipt["source_observation"] = source
        print(retain(receipt, args.output_dir))
        return 0 if receipt["status"] == "passed" else 1
    except (SloError, OSError, KeyError, TypeError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"memory.retrieval SLO refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
