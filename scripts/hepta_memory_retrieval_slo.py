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


def load(path):
    with Path(path).open("rb") as stream:
        data = stream.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024:
        raise SloError("sample input exceeds 64 MiB")
    return json.loads(data, object_pairs_hook=unique_object)


def percentiles(values):
    values = sorted(values)
    if not values:
        raise SloError("no measurements")
    return {f"p{p}_us": values[max(0, math.ceil(len(values) * p / 100) - 1)]
            for p in (50, 95, 99)} | {"max_us": values[-1]}


def case_key(case):
    if case.get("cache") not in {"cold", "warm"}:
        raise SloError("cache must be explicitly cold or warm")
    integer(case.get("concurrency"), "concurrency", 1)
    for field in CASE_FIELDS[2:]:
        if type(case.get(field)) is not bool:
            raise SloError(f"missing contention dimension: {field}")
    return tuple(case[field] for field in CASE_FIELDS)


def validate(document, policy, head):
    if not SHA.fullmatch(head) or document.get("source_head") != head:
        raise SloError("samples do not bind the requested exact source head")
    if document.get("schema") != "hepta.memory-retrieval.e2e-samples.v1":
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
    required = {case_key(case) for case in policy.get("required_cases", [])}
    if not required:
        raise SloError("SLO policy must declare its workload matrix")
    minimum = integer(policy.get("minimum_samples_per_case"), "minimum_samples_per_case", 100)
    limits = policy.get("limits", {})
    for metric in ("p95_us", "p99_us", "max_us", "peak_rss_bytes", "abstention_ppm", "stale_rejection_ppm"):
        integer(limits.get(metric), f"limit.{metric}")
    samples = document.get("samples")
    if not isinstance(samples, list) or not 1 <= len(samples) <= 1_000_000:
        raise SloError("bounded nonempty raw samples are required")
    groups, identities = {}, set()
    for sample in samples:
        sample_id = sample.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id or sample_id in identities:
            raise SloError("sample identities must be present and unique")
        identities.add(sample_id)
        key = case_key(sample)
        stages = sample.get("stages_us", {})
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
                        "abstention_ppm": sum(row["abstained"] for row in rows) * 1_000_000 // len(rows),
                        "stale_rejection_ppm": sum(row["stale_rejected"] for row in rows) * 1_000_000 // len(rows),
                        "stages": {stage: percentiles([row["stages_us"][stage] for row in rows]) for stage in STAGES},
                        "resource_maxima": {field: max(row[field] for row in rows) for field in COUNTERS[4:]}})
        for metric, limit in limits.items():
            if metric not in summary or type(summary[metric]) is not int:
                raise SloError(f"unsupported SLO limit: {metric}")
            if summary[metric] > limit:
                failures.append({"case": list(key), "metric": metric, "observed": summary[metric], "limit": limit})
        summaries.append(summary)
    return {
        "schema": "hepta.memory-retrieval.slo-receipt.v1", "source_head": head,
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
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = validate(load(args.samples), load(args.policy), args.head)
        print(retain(receipt, args.output_dir))
        return 0 if receipt["status"] == "passed" else 1
    except (SloError, OSError, KeyError, TypeError, ValueError) as error:
        print(f"memory.retrieval SLO refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
