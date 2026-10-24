#!/usr/bin/env python3
"""Run isolated, native same-trace mechanism probes; never produce NDU evidence.

Each arm/scale is a fresh Rust process: per-process VmHWM is comparable only
within the same runner and workload. All candidate config weights here are
UNTRAINED FIXTURES. This tool does not authenticate signed host deployment,
training artifacts, selected models, migration, source CI or future labels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

ARMS = ("v1", "v2", "v3", "ssm")
SCALES = (64, 256, 1024, 4096)
REPORT_SCHEMA = "hepta.neuron.mechanism-resource-probe.v1"
EVIDENCE_KIND = "UNVERIFIED_KERNEL_ONLY_NOT_TARGET_HOST_ACCEPTANCE"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_probe(
    value: Any, *,
    arm: str,
    cells: int,
    digest: str,
    events: int,
) -> dict[str, Any]:
    require(isinstance(value, dict), "probe did not produce a JSON object")
    require(value.get("schema") == REPORT_SCHEMA, "invalid probe report schema")
    require(value.get("evidence_kind") == EVIDENCE_KIND, "synthetic probe kind mislabeled")
    for key in (
        "production_qualification", "ndu_eligible", "trained_model",
        "state_persistence_measured", "microbatch_and_gpu_measured",
        "artifact_provenance_verified",
    ):
        require(value.get(key) is False, f"{key}: mechanism probe cannot claim success")
    require(value.get("arm") == arm, "arm mismatch")
    require(value.get("cells") == cells, "Cell count mismatch")
    require(value.get("trace_sha256") == digest, "input trace hash mismatch")
    require(value.get("logical_tick_count") == events * cells, "event count mismatch")
    require(
        isinstance(value.get("frontier_digest"), str)
        and len(value["frontier_digest"]) == 64
        and value["frontier_digest"] != "0" * 64,
        "invalid checkpoint frontier digest",
    )
    require(
        type(value.get("process_wall_micros")) is int
        and value["process_wall_micros"] >= 0,
        "missing observed wall-clock cost",
    )
    for key in ("p50_tick_nanos", "p95_tick_nanos", "p99_tick_nanos"):
        require(type(value.get(key)) is int and value[key] >= 0, f"{key}: invalid")
    require(value["p50_tick_nanos"] <= value["p95_tick_nanos"]
            <= value["p99_tick_nanos"], "invalid latency ordering")
    require(
        type(value.get("process_peak_rss_bytes")) is int
        and value["process_peak_rss_bytes"] > 0,
        "missing Linux VmHWM peak RSS",
    )
    return value


def run(binary: Path, trace_file: Path) -> dict[str, Any]:
    trace_bytes = trace_file.read_bytes()
    trace = json.loads(trace_bytes)
    require(trace.get("schema") == "hepta.neuron.mechanism-probe-trace.q24.v1",
            "fixture trace schema mismatch")
    events = trace.get("events")
    require(isinstance(events, list) and len(events) > 0, "empty fixture trace")
    digest = hashlib.sha256(trace_bytes).hexdigest()
    results: list[dict[str, Any]] = []
    for cells in SCALES:
        for arm in ARMS:
            argv = [
                str(binary.resolve()), "--arm", arm,
                "--cells", str(cells), "--trace", str(trace_file.resolve()),
            ]
            result = subprocess.run(
                argv, capture_output=True, text=True, check=False, timeout=180
            )
            require(result.returncode == 0,
                    f"{arm} {cells} native probe failed: {result.stderr[-3000:]}")
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{arm} {cells} emitted invalid JSON: {exc}") from exc
            results.append(validate_probe(
                payload, arm=arm, cells=cells, digest=digest, events=len(events)
            ))
    return {
        "schema": "hepta.neuron.mechanism-only-matrix.v1",
        "source_evidence_kind": EVIDENCE_KIND,
        "target_host_qualified": False,
        "trained_artifacts_qualified": False,
        "ndu_eligible": False,
        "trace_sha256": digest,
        "arms": list(ARMS),
        "scales": list(SCALES),
        "results": results,
        "warning": (
            "CI fixture measurements are not target-host deployment, "
            "resource acceptance, future utility, or evidence to replace V1"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        require(args.binary.exists() and args.binary.is_file(), "missing compiled Rust probe")
        report = run(args.binary, args.trace)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "BLOCKED_PROBE_MATRIX", "error": str(exc)}),
              file=sys.stderr)
        return 2
    output = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.report:
        args.report.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
