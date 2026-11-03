#!/usr/bin/env python3
"""Self-consistency verifier for three serial CPU diagnostic JSON observations.

It never loads weights or grants host attestation, NDU choice or production use.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import statistics

from hepta_neuron_artifact_preflight import verify_catalog
from hepta_neuron_cpu_benchmark import SCHEMA, EXPECTED_PARAMETERS, nearest_rank
from hepta_neuron_model_trials import (
    InvalidTrial, MODEL_IDS, is_sha, read_json, require, sha_file, write_new,
)

REPORT = "hepta.neuron.matched-three-arm-cpu-replay.diagnostic.v1"
ARMS = ("laya", "typed", "multilingual")
FALSE_ONLY = (
    "backend_batch_throughput_measured", "actual_hepta_data_used",
    "independent_host_attestation", "production_p99_sla_established",
    "future_window_effectiveness_evaluated", "ndu_net_gain_verified",
    "ndu_selection_authorized", "production_evidence_verified", "promotion_authorized",
)


def close_number(actual, expected, epsilon=1.1e-5):
    return (type(actual) in (float,int) and math.isfinite(actual) and
            abs(actual-expected) <= epsilon)


def verify_one(path: Path, catalog: dict, catalog_sha: str,
               sdk_sha: str, arm: str):
    require(path.is_file() and not path.is_symlink(), "missing/aliased diagnostic file")
    p = read_json(path)
    require(type(p) is dict and p.get("schema") == SCHEMA and p.get("arm") == arm,
            "wrong benchmark receipt schema/arm")
    require(p.get("model_id") == MODEL_IDS[arm] and
            p.get("source_revision") == catalog["revision"] and
            p.get("source_catalog_sha256") == catalog_sha and
            p.get("weights_sha256") == catalog["variants"][arm]["weights_sha256"] and
            p.get("installed_sdk_python_sha256") == sdk_sha and
            is_sha(p.get("physical_artifact_tree_sha256")),
            "model source, tokenizer/SDK or weight identity mismatch")
    require(p.get("device") == "cpu" and type(p.get("cpu_threads")) is int and
            p["cpu_threads"] == 2 and
            p.get("parameters") == EXPECTED_PARAMETERS[arm] and
            p.get("effective_context") == 512 and p.get("effective_head_budget") == 192,
            "physical configuration/parameter budget mismatch")
    require(p.get("warmup_count") == 5 and p.get("sample_count") == 100 and
            type(p.get("input_tokens")) is int and 0 < p["input_tokens"] <= 512,
            "wrong number of serial repeated model invocations")
    for name in FALSE_ONLY:
        require(p.get(name) is False, f"diagnostic must deny {name}")
    require(p.get("measurement_scope") ==
            "serial single CPU process, synthetic repeated identical prompt",
            "unexpected measurement scope")
    timings = p.get("timing_samples_ms")
    require(type(timings) is list and len(timings) == 100 and
            all(type(t) in (float,int) and math.isfinite(t) and t > 0 for t in timings),
            "missing/nonfinite raw samples")
    mean = statistics.mean(timings)
    for pc in (50,95,99):
        require(close_number(p.get(f"p{pc}_ms"), nearest_rank(timings,pc)),
                f"unverifiable p{pc} reported from samples")
    require(close_number(p.get("mean_ms"), mean) and
            close_number(p.get("serial_invocations_per_second"), 1000/mean),
            "mean/serial throughput inconsistent with observations")
    require(type(p.get("load_ms")) in (float,int) and math.isfinite(p["load_ms"]) and p["load_ms"] > 0,
            "physical model load time missing")
    for key in ("rss_before_model_load", "rss_after_model_load", "rss_after_forwards"):
        v = p.get(key)
        require(type(v) is dict and
                type(v.get("rss_bytes")) is int and type(v.get("peak_rss_bytes")) is int and
                0 < v["rss_bytes"] <= v["peak_rss_bytes"],
                "unverifiable RSS measurement")
    require(p["rss_after_model_load"]["peak_rss_bytes"] >= p["rss_before_model_load"]["peak_rss_bytes"] and
            p["rss_after_forwards"]["peak_rss_bytes"] >= p["rss_after_model_load"]["peak_rss_bytes"],
            "process peak RSS regressed impossibly")
    return {"arm":arm,"source_file_sha256":sha_file(path),"parameters":p["parameters"],
            "input_tokens":p["input_tokens"],"p50_ms":p["p50_ms"],
            "p95_ms":p["p95_ms"],"p99_ms":p["p99_ms"],
            "mean_ms":p["mean_ms"],"load_ms":p["load_ms"],
            "peak_process_rss_bytes":p["rss_after_forwards"]["peak_rss_bytes"]}


def verify_bundle(directory: Path, catalog_path: Path, sdk_sha: str) -> dict:
    require(is_sha(sdk_sha),"pin exact installed SDK Python-source digest")
    directory = Path(directory)
    require(directory.is_absolute() and directory.is_dir() and not directory.is_symlink(),
            "absolute trusted diagnostic directory required")
    entries = list(directory.iterdir())
    expected_names = {f"{arm}-cpu-diagnostic.json" for arm in ARMS}
    require({x.name for x in entries} == expected_names and
            all(x.is_file() and not x.is_symlink() for x in entries),
            "unexpected/aliased diagnostic receipt set")
    catalog = verify_catalog(read_json(catalog_path))
    digest = sha_file(catalog_path)
    rows = [verify_one(directory/f"{arm}-cpu-diagnostic.json", catalog,digest,sdk_sha,arm)
            for arm in ARMS]
    return {"schema":REPORT,"source_catalog_sha256":digest,
            "source_revision":catalog["revision"],
            "sdk_python_sha256":sdk_sha, "arms":rows,
            "sample_count_each":100, "warmup_each":5, "cpu_threads_each":2,
            "matched_512_192_token_caps":True,"real_weights_rechecked_by_runner":True,
            "observations_self_consistent":True,
            "independent_host_attestation":False,"real_hepta_task_data":False,
            "production_p99_sla_established":False,
            "backend_batch_throughput_measured":False,
            "future_window_effectiveness_evaluated":False,
            "ndu_net_gain_verified":False,"ndu_selection_authorized":False,
            "production_evidence_verified":False,"promotion_authorized":False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory",type=Path,required=True)
    parser.add_argument("--catalog",type=Path,required=True)
    parser.add_argument("--sdk-python-sha256",required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    try:
        require(args.output.is_absolute() and not args.output.exists() and
                args.output.parent != args.directory,
                "summary must be a fresh file outside input directory")
        write_new(args.output,verify_bundle(args.directory,args.catalog,args.sdk_python_sha256))
    except (InvalidTrial,ValueError,TypeError,KeyError,OSError) as exc:
        parser.exit(2,f"blocked: {exc}\n")

if __name__=="__main__":
    main()
