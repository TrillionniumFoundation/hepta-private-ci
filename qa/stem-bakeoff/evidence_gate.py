"""Independent fail-closed admission preflight for shared-Stem receipts.

This cannot independently authenticate self-reported upstream GitHub checks,
model provenance, or future outcomes. Its highest state is REVIEW_REQUIRED;
NO response from this script ever grants production authority or selects a Stem.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from typing import Any

from stem_bakeoff import REQUIRED_GATES, REQUIRED_METRICS, validate_result

SCALES = (1, 8, 64, 256, 1024, 4096)
HEX64 = re.compile(r"(?:sha256:)?[0-9a-f]{64}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
REQUIRED_SPLITS = ("train", "calibration", "future_1", "future_2", "ood")
BOUNDED_FRACTIONS = (
    "negative_transfer_rate", "multimodal_coverage",
    "long_context_retention", "calibration_error", "feature_cache_reuse_rate",
)
POSITIVE_METRICS = ("p99_ms", "throughput_per_host", "rss_bytes")
NONNEGATIVE_METRICS = ("gpu_peak_bytes", "per_cell_incremental_bytes")


def _hash(value: object) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _finite_num(value: object) -> bool:
    return type(value) in (float, int) and math.isfinite(value)


def assess(result: dict[str, Any], expected_head_sha: str) -> dict[str, Any]:
    """Return rejection reasons and an inescapably non-authorizing disposition."""
    errors = validate_result(result) if isinstance(result, dict) else ["result is not an object"]
    if not isinstance(expected_head_sha, str) or not HEX40.fullmatch(expected_head_sha):
        errors.append("exact expected Git head SHA40 is required")

    if isinstance(result, dict):
        if set(result) != {
            "schema", "authority", "runtime_posture", "candidate", "artifact",
            "metrics", "gates", "cell_components", "evidence", "ci",
        }:
            errors.append("result requires exact evidence-bound top-level fields")

        artifact = result.get("artifact")
        if not isinstance(artifact, dict) or set(artifact) != {"digest", "revision"}:
            errors.append("artifact requires exact digest and pinned revision")
        elif not _hash(artifact.get("digest")) or not isinstance(artifact.get("revision"), str) or not HEX40.fullmatch(artifact["revision"]):
            errors.append("artifact digest must be SHA256 and revision must be SHA40")

        metrics = result.get("metrics")
        if isinstance(metrics, dict):
            if set(metrics) != set(REQUIRED_METRICS):
                errors.append("metrics must exactly match the registered set")
            for key, value in metrics.items():
                if not _finite_num(value):
                    errors.append(f"metrics.{key} is not a finite number")
                elif key in BOUNDED_FRACTIONS and not 0 <= value <= 1:
                    errors.append(f"metrics.{key} outside [0,1]")
                elif key in POSITIVE_METRICS and value <= 0:
                    errors.append(f"metrics.{key} must be positive")
                elif key in NONNEGATIVE_METRICS and value < 0:
                    errors.append(f"metrics.{key} must be nonnegative")

        gates = result.get("gates")
        if isinstance(gates, dict) and set(gates) != set(REQUIRED_GATES):
            errors.append("gates must contain exactly the registered set")

        evidence = result.get("evidence")
        if not isinstance(evidence, dict) or set(evidence) != {
            "evidence_class", "loaded_pretrained_weights", "checkpoint_inventory_sha256",
            "runtime_sha256", "source_sha256", "splits", "held_labels_hidden",
            "future_source_disjoint", "instrumentation", "scale_measurements",
        }:
            errors.append("complete source/model/measurement evidence is required")
        else:
            if evidence.get("evidence_class") != "REAL_MODEL_OBSERVED" or evidence.get("loaded_pretrained_weights") is not True:
                errors.append("real, loaded pretrained model evidence required")
            for key in ("checkpoint_inventory_sha256", "runtime_sha256", "source_sha256"):
                if not _hash(evidence.get(key)):
                    errors.append(f"evidence.{key} must be SHA256")
            splits = evidence.get("splits")
            if not isinstance(splits, dict) or set(splits) != set(REQUIRED_SPLITS):
                errors.append("independent train/calibration/two future/OOD splits required")
            else:
                hashes = list(splits.values())
                if not all(_hash(x) for x in hashes) or len(set(hashes)) != len(hashes):
                    errors.append("split digests must be complete and source-disjoint")
            if evidence.get("held_labels_hidden") is not True or evidence.get("future_source_disjoint") is not True:
                errors.append("held labels/future source isolation not proven")
            instr = evidence.get("instrumentation")
            if not isinstance(instr, dict) or set(instr) != {"level", "backend_forward_count_observed"} or instr.get("level") != "model_forward_hook" or instr.get("backend_forward_count_observed") is not True:
                errors.append("model forward hook is required; encode() API call is insufficient")
            runs = evidence.get("scale_measurements")
            if not isinstance(runs, list) or len(runs) != len(SCALES):
                errors.append("six physical scale measurements are required")
            else:
                for scale, row in zip(SCALES, runs):
                    if not isinstance(row, dict) or set(row) != {
                        "cells", "unique_input_batches", "encoder_forward_calls",
                        "private_backbone_bytes", "p95_ms", "p99_ms", "peak_rss_bytes",
                    }:
                        errors.append(f"scale {scale} missing exact resource fields")
                        continue
                    if type(row["cells"]) is not int or row["cells"] != scale:
                        errors.append(f"scale order must include {scale} Cells")
                    batches, calls, private_bytes = (row[k] for k in (
                        "unique_input_batches", "encoder_forward_calls", "private_backbone_bytes"))
                    if (type(batches) is not int or type(calls) is not int or batches < 1 or calls != batches):
                        errors.append(f"scale {scale} did not prove one Encoder forward per batch")
                    if type(private_bytes) is not int or private_bytes != 0:
                        errors.append(f"scale {scale} duplicates Encoder bytes inside Cells")
                    p95, p99, rss = (row[k] for k in ("p95_ms", "p99_ms", "peak_rss_bytes"))
                    if not (_finite_num(p95) and _finite_num(p99) and 0 < p95 <= p99):
                        errors.append(f"scale {scale} has invalid p95/p99 latency")
                    if type(rss) is not int or rss <= 0:
                        errors.append(f"scale {scale} lacks measured RSS")

        ci = result.get("ci")
        if not isinstance(ci, dict) or set(ci) != {"head_sha", "status", "conclusion", "run_id", "workflow"}:
            errors.append("exact-head terminal CI evidence is required")
        elif (ci.get("head_sha") != expected_head_sha or ci.get("status") != "completed"
              or ci.get("conclusion") != "success" or type(ci.get("run_id")) is not int
              or ci["run_id"] <= 0 or ci.get("workflow") != "blocking-ci"):
            errors.append("CI is not completed success on the exact head")

    # No programmatic authority: an independent approver must verify model,
    # source, host measurements and GitHub statuses OUTSIDE this self-report.
    return {
        "evidence_status": "REJECTED" if errors else "REVIEW_REQUIRED",
        "runtime_posture": "SHADOW_ONLY",
        "authority": "DENY_ALL",
        "release": "HOLD_NO_GO",
        "production_activation_allowed": False,
        "independent_review_required": True,
        "blockers": sorted(set(errors)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", help="untrusted JSON evidence file")
    parser.add_argument("--expected-head", required=True, help="exact HEAD commit SHA40")
    args = parser.parse_args()
    with open(args.result, encoding="utf-8") as stream:
        evidence = json.load(stream)
    decision = assess(evidence, args.expected_head)
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0 if decision["evidence_status"] == "REVIEW_REQUIRED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
