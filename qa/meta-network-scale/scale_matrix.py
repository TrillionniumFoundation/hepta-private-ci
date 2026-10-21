#!/usr/bin/env python3
"""Generate and validate the Hepta cell/meta-network qualification matrix.

This tool validates experiment shape and evidence completeness only. A valid
manifest is not an efficacy result and cannot promote a topology.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from typing import Any

SIZES = (1, 8, 64, 256, 1024, 4096)
ARMS = (
    "no_change",
    "fixed_routing",
    "learned_routing",
    "single_head",
    "shared_encoder",
    "duplicated_encoder",
)
REQUIRED_EVIDENCE = (
    "future_window",
    "negative_transfer",
    "lesion_ablation",
    "crash_reopen",
    "stale_generation_rejection",
    "rollback",
    "resource_cost",
)
REQUIRED_METRICS = (
    "task_utility",
    "p99_ms",
    "throughput_per_host",
    "rss_bytes",
    "queue_age_ms",
    "starvation_count",
)
LIFECYCLE = (
    "candidate",
    "independent_evaluation",
    "selector",
    "signed_successor_snapshot",
    "state_migration",
    "old_writer_fence",
    "route_cutover",
    "canary",
    "rollback_rehearsal",
    "production_admission",
)

# A scale result is only a qualification-shaped record.  It still has to bind
# the observations to immutable source/host evidence so that a fixture cannot
# be mistaken for an exact-head or target-host run.  The validator cannot
# authenticate these values; that remains the workflow/host owner's job.
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
PROVENANCE_FIELDS = (
    "source_commit",
    "source_tree",
    "target_host_digest",
    "runtime_digest",
    "measurement_digest",
)


def build_plan() -> dict[str, Any]:
    return {
        "schema": "hepta.cell-execution-scale-plan.v1",
        "authority": "qualification_only",
        "sizes": list(SIZES),
        "arms": list(ARMS),
        "required_evidence": list(REQUIRED_EVIDENCE),
        "required_metrics": list(REQUIRED_METRICS),
        "required_provenance": list(PROVENANCE_FIELDS),
        "required_evidence_receipts": list(REQUIRED_EVIDENCE),
        "topology_lifecycle": list(LIFECYCLE),
        "claims": [
            "expressivity",
            "learnability",
            "unseen_task_adaptation",
            "resource_scaling",
        ],
    }


def validate_result(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if result.get("schema") != "hepta.cell-execution-scale-result.v1":
        errors.append("schema must be hepta.cell-execution-scale-result.v1")
    if result.get("size") not in SIZES:
        errors.append("size must be one of 1, 8, 64, 256, 1024, 4096")
    if result.get("arm") not in ARMS:
        errors.append("arm is not in the registered comparison arms")
    if result.get("authority") != "qualification_only":
        errors.append("authority must remain qualification_only")

    provenance = result.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("provenance must be an object")
    else:
        for key in PROVENANCE_FIELDS:
            value = provenance.get(key)
            pattern = _HEX40 if key in {"source_commit", "source_tree"} else _HEX64
            if not isinstance(value, str) or pattern.fullmatch(value) is None:
                errors.append(f"provenance.{key} must be a lowercase hexadecimal digest")

    evidence = result.get("evidence")
    if not isinstance(evidence, dict):
        errors.append("evidence must be an object")
    else:
        for key in REQUIRED_EVIDENCE:
            if evidence.get(key) is not True:
                errors.append(f"evidence.{key} must be true")

    evidence_receipts = result.get("evidence_receipts")
    if not isinstance(evidence_receipts, dict):
        errors.append("evidence_receipts must be an object")
    else:
        for key in REQUIRED_EVIDENCE:
            value = evidence_receipts.get(key)
            if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
                errors.append(
                    f"evidence_receipts.{key} must be a lowercase SHA-256 digest"
                )

    metrics = result.get("metrics")
    if not isinstance(metrics, dict):
        errors.append("metrics must be an object")
    else:
        for key in REQUIRED_METRICS:
            if key not in metrics:
                errors.append(f"metrics.{key} is required")
                continue
            value = metrics[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"metrics.{key} must be a finite number")
            elif not math.isfinite(value):
                errors.append(f"metrics.{key} must be a finite number")
            elif key != "task_utility" and value < 0:
                errors.append(f"metrics.{key} must be non-negative")

    metrics_receipt = result.get("metrics_receipt")
    if not isinstance(metrics_receipt, str) or _HEX64.fullmatch(metrics_receipt) is None:
        errors.append("metrics_receipt must be a lowercase SHA-256 digest")
    lifecycle = result.get("topology_lifecycle")
    if lifecycle != list(LIFECYCLE):
        errors.append("topology_lifecycle must contain the complete ordered lifecycle")
    return errors


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan")
    validate = subparsers.add_parser("validate")
    validate.add_argument("result", type=argparse.FileType("r"))
    args = parser.parse_args(argv)
    if args.command == "plan":
        json.dump(build_plan(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    result = json.load(args.result)
    errors = validate_result(result)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("valid qualification result shape")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
