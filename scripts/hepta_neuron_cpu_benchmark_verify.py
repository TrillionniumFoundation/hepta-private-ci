#!/usr/bin/env python3
"""Recompute three-arm repeated-CPU summary from raw diagnostic observations.
Not independent host attestation, model efficacy, NDU selection or production authorization.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import statistics

from hepta_neuron_artifact_preflight import verify_catalog
from hepta_neuron_cpu_benchmark import SCHEMA, EXPECTED_PARAMETERS, nearest_rank
from hepta_neuron_model_trials import (
    MODEL_IDS,
    InvalidTrial,
    is_sha,
    read_json,
    require,
    sha_file,
    write_new,
)

REPORT = "hepta.neuron.matched-three-arm-cpu-replay.diagnostic.v1"
ARMS = ("laya", "typed", "multilingual")
FALSE_ONLY = (
    "backend_batch_throughput_measured",
    "actual_hepta_data_used",
    "independent_host_attestation",
    "production_p99_sla_established",
    "future_window_effectiveness_evaluated",
    "ndu_net_gain_verified",
    "ndu_selection_authorized",
    "production_evidence_verified",
    "promotion_authorized",
)


def close_number(actual, expected, tolerance=1.1e-5):
    return (
        type(actual) in (int, float)
        and math.isfinite(actual)
        and abs(actual - expected) <= tolerance
    )


def verify_one(path, catalog, catalog_sha, sdk_sha, arm):
    require(path.is_file() and not path.is_symlink(), "missing/aliased diagnostic file")
    p = read_json(path)
    require(
        type(p) is dict and p.get("schema") == SCHEMA and p.get("arm") == arm,
        "wrong benchmark receipt schema or arm",
    )
    require(
        p.get("model_id") == MODEL_IDS[arm]
        and p.get("source_revision") == catalog["revision"]
        and p.get("source_catalog_sha256") == catalog_sha
        and p.get("weights_sha256") == catalog["variants"][arm]["weights_sha256"]
        and p.get("installed_sdk_python_sha256") == sdk_sha
        and is_sha(p.get("physical_artifact_tree_sha256")),
        "model source/SDK or weights identity mismatch",
    )
    require(
        p.get("device") == "cpu"
        and type(p.get("cpu_threads")) is int
        and p["cpu_threads"] == 2
        and type(p.get("parameters")) is int
        and p["parameters"] == EXPECTED_PARAMETERS[arm]
        and p.get("effective_context") == 512
        and p.get("effective_head_budget") == 192,
        "model parameters, resource limits or token budgets drifted",
    )
    require(
        p.get("warmup_count") == 5
        and p.get("sample_count") == 100
        and type(p.get("input_tokens")) is int
        and 0 < p["input_tokens"] <= 512,
        "not one hundred genuine matched CPU samples",
    )
    require(
        p.get("measurement_scope")
        == "serial single CPU process, synthetic repeated identical prompt",
        "not a matched diagnostic measurement",
    )
    for field in FALSE_ONLY:
        require(p.get(field) is False, f"non-production diagnostic must deny {field}")
    times = p.get("timing_samples_ms")
    require(
        type(times) is list
        and len(times) == 100
        and all(type(t) in (int, float) and math.isfinite(t) and t > 0 for t in times),
        "nonfinite or absent raw CPU timings",
    )
    mean = statistics.mean(times)
    for pc in (50, 95, 99):
        require(
            close_number(p.get(f"p{pc}_ms"), nearest_rank(times, pc)),
            f"p{pc} did not match raw timings",
        )
    require(
        close_number(p.get("mean_ms"), mean)
        and close_number(p.get("serial_invocations_per_second"), 1000 / mean),
        "mean or serial-only throughput inconsistent",
    )
    require(
        type(p.get("load_ms")) in (int, float)
        and math.isfinite(p["load_ms"])
        and p["load_ms"] > 0,
        "no physical model load time",
    )
    for field in (
        "rss_before_model_load",
        "rss_after_model_load",
        "rss_after_forwards",
    ):
        value = p.get(field)
        require(
            type(value) is dict
            and type(value.get("rss_bytes")) is int
            and type(value.get("peak_rss_bytes")) is int
            and 0 < value["rss_bytes"] <= value["peak_rss_bytes"],
            "missing real process RSS",
        )
    require(
        p["rss_after_model_load"]["peak_rss_bytes"]
        >= p["rss_before_model_load"]["peak_rss_bytes"]
        and p["rss_after_forwards"]["peak_rss_bytes"]
        >= p["rss_after_model_load"]["peak_rss_bytes"],
        "impossible peak RSS regression",
    )
    return {
        "arm": arm,
        "source_file_sha256": sha_file(path),
        "parameters": p["parameters"],
        "input_tokens": p["input_tokens"],
        "p50_ms": p["p50_ms"],
        "p95_ms": p["p95_ms"],
        "p99_ms": p["p99_ms"],
        "mean_ms": p["mean_ms"],
        "load_ms": p["load_ms"],
        "peak_process_rss_bytes": p["rss_after_forwards"]["peak_rss_bytes"],
    }


def verify_bundle(directory, catalog_path, sdk_sha):
    require(is_sha(sdk_sha), "pinned SDK digest required")
    directory = Path(directory)
    require(
        directory.is_absolute() and directory.is_dir() and not directory.is_symlink(),
        "absolute trusted diagnostic directory required",
    )
    entries = list(directory.iterdir())
    names = {f"{arm}-cpu-diagnostic.json" for arm in ARMS}
    require(
        {x.name for x in entries} == names
        and all(x.is_file() and not x.is_symlink() for x in entries),
        "unexpected/aliased diagnostic receipt set",
    )
    catalog = verify_catalog(read_json(catalog_path))
    digest = sha_file(catalog_path)
    arms = [
        verify_one(
            directory / f"{arm}-cpu-diagnostic.json", catalog, digest, sdk_sha, arm
        )
        for arm in ARMS
    ]
    return {
        "schema": REPORT,
        "source_catalog_sha256": digest,
        "source_revision": catalog["revision"],
        "sdk_python_sha256": sdk_sha,
        "arms": arms,
        "sample_count_each": 100,
        "warmup_each": 5,
        "cpu_threads_each": 2,
        "observations_self_consistent": True,
        "independent_host_attestation": False,
        "real_hepta_task_data": False,
        "production_p99_sla_established": False,
        "backend_batch_throughput_measured": False,
        "future_window_effectiveness_evaluated": False,
        "ndu_net_gain_verified": False,
        "ndu_selection_authorized": False,
        "production_evidence_verified": False,
        "promotion_authorized": False,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--directory", type=Path, required=True)
    ap.add_argument("--catalog", type=Path, required=True)
    ap.add_argument("--sdk-python-sha256", required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        require(
            args.output.is_absolute()
            and not args.output.exists()
            and args.output.parent != args.directory,
            "fresh summary must be outside input directory",
        )
        write_new(
            args.output,
            verify_bundle(args.directory, args.catalog, args.sdk_python_sha256),
        )
    except (InvalidTrial, ValueError, TypeError, KeyError, OSError) as exc:
        ap.exit(2, f"blocked: {exc}\n")


if __name__ == "__main__":
    main()
