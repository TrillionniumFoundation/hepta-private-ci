#!/usr/bin/env python3
"""Paired research-scale resource budget guard; no production promotion.

Operates only on measured, clean-reopened Jina research backend summaries.
Requires an explicit caller-selected hardware budget. Does not substitute
the result for real Rust inference worker microbatch, crash-recovery, or NDU.
"""
import argparse
import json
import math
from pathlib import Path

from jina_v5 import sha256_record
from qualified_eval import strict_json_loads

SCHEMA = "hepta.jina-v5-shadow-scale-probe.v1"
WORKLOAD_FIELDS = (
    "total_logical_cells", "actual_active_heads", "total_requests", "seed",
    "head_type", "head_parameter_ceiling", "feature_dimension",
    "context_token_budget", "representation", "requested_batch_size",
    "task_similarity", "input_repeat_fraction", "active_fraction",
)
TARGET_FIELDS = ("os", "machine_arch", "logical_cpu_count", "python",
                 "dependency_versions")


def finite_positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def verify_summary(summary):
    if not isinstance(summary, dict) or summary.get("schema") != SCHEMA:
        raise ValueError("resource evidence must come from Jina real-backend scale probe")
    if summary.get("status") != "real_backend_research_only":
        raise ValueError("synthetic, inactive, or promoted result prohibited")
    census = summary.get("local_snapshot_census_sha256")
    if (type(census) is not str or len(census) != 64
            or census == "0" * 64
            or any(ch not in "0123456789abcdef" for ch in census)):
        raise ValueError("resource evidence lacks approved real Jina snapshot file census")
    if (summary.get("local_snapshot_attested_twice") is not True
            or summary.get("model_code_and_adapter_bytes_hashed") is not True):
        raise ValueError("resource evidence lacks pre/post local model artifact verification")
    if not finite_positive(summary.get("local_snapshot_attestation_ms")):
        raise ValueError("resource report omitted actual model byte verification cost")
    if summary.get("production_promotion_permitted") is not False:
        raise ValueError("production authority is not allowed")
    if summary.get("production_worker_microbatch_verified") is not False:
        raise ValueError("research cannot claim verified production microbatch")
    if summary.get("sqlite_clean_reopen_ok") is not True:
        raise ValueError("SQLite reopen evidence missing")
    if summary.get("sqlite_unclean_crash_recovery_verified") is not False:
        raise ValueError("unclean crash claims unsupported")
    if summary.get("ndu_signed_verified") is not False:
        raise ValueError("signed NDU claims unsupported")
    if summary.get("heads_initialized_not_learned") is not True:
        raise ValueError("this is not the declared initialized-Head cost experiment")
    if summary.get("full_active_cell_coverage") is not True:
        raise ValueError("active Cell set is not actually covered by measured ticks")
    if summary.get("distinct_ticked_cells") != summary.get("actual_active_heads"):
        raise ValueError("observed Cell coverage differs from declared active Heads")
    for key in ("process_wall_seconds", "process_cpu_seconds",
                "aggregate_throughput_rps", "max_observed_rss_bytes"):
        if not finite_positive(summary.get(key)):
            raise ValueError("missing or invalid observed metric: " + key)
    if summary["total_requests"] < summary["distinct_ticked_cells"]:
        raise ValueError("insufficient requests for Cell coverage")
    if summary.get("actual_encoder_batch_calls", 0) <= 0:
        raise ValueError("no observed real Encoder batch calls")
    if not isinstance(summary.get("dataset"), dict) or not summary["dataset"].get("dataset_digest"):
        raise ValueError("audited dataset identity required")
    env = summary.get("environment")
    if not isinstance(env, dict) or not all(k in env for k in TARGET_FIELDS):
        raise ValueError("missing reproducible target environment")
    if not finite_positive(summary.get("observed_total_physical_ram_bytes")):
        raise ValueError("missing physical host RAM observation")
    groups = summary.get("scales", [])
    if not groups or len(groups) != 1:
        raise ValueError("exactly one scale/workload cohort per output required")
    entry = groups[0]
    if entry.get("observed_records") != summary["total_requests"]:
        raise ValueError("observed request count mismatch")
    paths = entry.get("latency_paths", {})
    if not paths:
        raise ValueError("no measured per-stage latency paths")
    p99 = []
    for stage, record in paths.items():
        if stage not in ("backend_batch", "cache_hit_head", "encoder_warm"):
            raise ValueError("unsupported latency stage")
        if not isinstance(record, dict) or record.get("n", 0) <= 0:
            raise ValueError("invalid nonempty stage count")
        latency = record.get("p99_ms")
        if type(latency) not in (int, float) or not math.isfinite(latency) or latency < 0:
            raise ValueError("missing true observed p99")
        p99.append(latency)
    if sum(p["n"] for p in paths.values()) != summary["total_requests"]:
        raise ValueError("stage observations do not cover all submitted requests")
    return max(p99)


def paired_resource_gate(reference, candidate, budget):
    reference_p99 = verify_summary(reference)
    candidate_p99 = verify_summary(candidate)
    if not isinstance(budget, dict) or budget.get("schema") != "hepta.neuron-research-resource-budget.v1":
        raise ValueError("explicit frozen budget schema required")
    if budget.get("signed_production_budget") is not False:
        raise ValueError("research budget cannot issue production resource authority")
    for field in ("max_peak_rss_bytes", "max_request_p99_ms", "min_throughput_rps",
                  "max_cpu_seconds_ratio"):
        if not finite_positive(budget.get(field)):
            raise ValueError("missing explicit resource threshold: " + field)
    for field in WORKLOAD_FIELDS:
        if reference.get(field) != candidate.get(field):
            raise ValueError("workload mismatch: " + field)
    if reference["dataset"]["dataset_digest"] != candidate["dataset"]["dataset_digest"]:
        raise ValueError("different data evidence cannot be paired")
    for field in TARGET_FIELDS:
        if reference["environment"][field] != candidate["environment"][field]:
            raise ValueError("not comparable measured host environment: " + field)
    if reference["observed_total_physical_ram_bytes"] != candidate["observed_total_physical_ram_bytes"]:
        raise ValueError("different host physical RAM")
    for field in ("input_repeat_fraction", "active_fraction", "task_similarity"):
        if reference["scales"][0][field] != candidate["scales"][0][field]:
            raise ValueError("scale cohort mismatch: " + field)
    if reference["model"] == candidate["model"] and reference["revision"] == candidate["revision"]:
        raise ValueError("reference and candidate should test distinct registered Stems")
    candidate_cpu_ratio = candidate["process_cpu_seconds"] / reference["process_cpu_seconds"]
    guards = {
        "peak_rss": candidate["max_observed_rss_bytes"] <= budget["max_peak_rss_bytes"],
        "p99": candidate_p99 <= budget["max_request_p99_ms"],
        "throughput": candidate["aggregate_throughput_rps"] >= budget["min_throughput_rps"],
        "cpu_regression": candidate_cpu_ratio <= budget["max_cpu_seconds_ratio"],
        "full_active_cell_coverage": candidate["full_active_cell_coverage"],
    }
    return {
        "schema": "hepta.neuron-research-paired-resource-gate.v1",
        "status": "research_budget_pass" if all(guards.values()) else "research_budget_failed",
        "research_resource_gate_passed": all(guards.values()),
        "checks": guards,
        "reference_model": reference["model"],
        "reference_revision": reference["revision"],
        "candidate_model": candidate["model"],
        "candidate_revision": candidate["revision"],
        "reference_local_snapshot_census_sha256": reference["local_snapshot_census_sha256"],
        "candidate_local_snapshot_census_sha256": candidate["local_snapshot_census_sha256"],
        "research_artifact_census_signed": False,
        "scale": {
            "logical_cells": candidate["total_logical_cells"],
            "active_heads": candidate["actual_active_heads"],
            "distinct_ticked_cells": candidate["distinct_ticked_cells"],
            "actual_requests": candidate["total_requests"],
            "measured_active_cell_coverage": candidate["full_active_cell_coverage"],
        },
        "metrics": {
            "reference_max_stage_p99_ms": reference_p99,
            "candidate_max_stage_p99_ms": candidate_p99,
            "reference_rss_bytes": reference["max_observed_rss_bytes"],
            "candidate_rss_bytes": candidate["max_observed_rss_bytes"],
            "reference_throughput_rps": reference["aggregate_throughput_rps"],
            "candidate_throughput_rps": candidate["aggregate_throughput_rps"],
            "candidate_cpu_seconds_ratio": candidate_cpu_ratio,
            "candidate_covered_cells": candidate["distinct_ticked_cells"],
        },
        "budget": budget,
        "budget_digest": sha256_record(budget),
        "reference_evidence_digest": sha256_record(reference),
        "candidate_evidence_digest": sha256_record(candidate),
        "same_physical_host_attested": False,
        "production_microbatch_qualified": False,
        "production_recovery_qualified": False,
        "production_promotion_permitted": False,
        "independent_ndu_signature_verified": False,
        "limitations": [
            "Hardware metadata match is not a cryptographic same-host attestation",
            "Batch total latency is conservatively assigned to every request in batch",
            "Reference is a real Jina research probe, not an independent no-change policy",
            "No target-host or production-Worker acceptance is implied",
        ],
    }


MAX_RESOURCE_EVIDENCE_BYTES = 16 * 1024 * 1024


def load_strict_resource_evidence(path):
    """Only bounded unambiguous JSON objects are comparable."""
    source = Path(path)
    if not source.is_file() or source.stat().st_size > MAX_RESOURCE_EVIDENCE_BYTES:
        raise ValueError("missing or oversized immutable resource evidence")
    document = strict_json_loads(source.read_text(encoding="utf-8"))
    if type(document) is not dict:
        raise ValueError("resource evidence must contain a JSON object")
    return document


def write_immutable_resource_gate(path, report):
    """No previous resource assessment can be silently replaced by a rerun."""
    raw = json.dumps(report, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False) + "\n"
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        stream.write(raw)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reference", required=True, help="Nano or other measured Jina research reference")
    p.add_argument("--candidate", required=True)
    p.add_argument("--budget", required=True, help="explicit precommitted external JSON budget")
    p.add_argument("--out", required=True)
    a = p.parse_args()
    verdict = paired_resource_gate(
        load_strict_resource_evidence(a.reference),
        load_strict_resource_evidence(a.candidate),
        load_strict_resource_evidence(a.budget))
    write_immutable_resource_gate(a.out, verdict)


if __name__ == "__main__":
    main()
