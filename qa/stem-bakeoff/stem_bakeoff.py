#!/usr/bin/env python3
"""Validate the shared-stem bake-off manifest and result evidence shape.

The validator is qualification-only. It never downloads weights, executes a
model, or admits a candidate to runtime.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

SCHEMA = "hepta.shared-stem-bakeoff.v1"
RESULT_SCHEMA = "hepta.shared-stem-bakeoff-result.v1"
POSTURE = {"mode": "SHADOW_ONLY", "authority": "DENY_ALL", "release": "HOLD_NO_GO"}
CANDIDATES = (
    "embeddinggemma2_740m",
    "t5gemma2_encoder_270m",
    "hepta_latent_150m",
    "hepta_latent_300m",
)
CELL_COMPONENTS = (
    "gate",
    "light_adapter",
    "task_head",
    "action_head",
    "value_head",
    "local_state",
    "external_memory_ref",
)
FORBIDDEN_CELL_COMPONENTS = (
    "encoder_copy",
    "per_cell_backbone",
    "per_cell_optimizer_state",
    "authority_token",
)
REQUIRED_METRICS = (
    "task_utility",
    "future_window_utility",
    "negative_transfer_rate",
    "multimodal_coverage",
    "long_context_retention",
    "calibration_error",
    "p99_ms",
    "throughput_per_host",
    "gpu_peak_bytes",
    "rss_bytes",
    "feature_cache_reuse_rate",
    "per_cell_incremental_bytes",
)
REQUIRED_GATES = (
    "artifact_digest",
    "one_shared_forward_per_batch",
    "zero_delta_parity",
    "stale_generation_rejection",
    "receipt_terminality",
    "control_regression_bound",
    "resource_budget",
    "rollback_witness",
)


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    if not isinstance(manifest, dict):
        return ["manifest must be an object"]
    errors: list[str] = []
    if manifest.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if manifest.get("status") != "qualification_plan":
        errors.append("status must remain qualification_plan")
    if manifest.get("authority") != "qualification_only":
        errors.append("authority must remain qualification_only")
    if manifest.get("runtime_posture") != POSTURE:
        errors.append("runtime_posture must remain SHADOW_ONLY/DENY_ALL/HOLD_NO_GO")

    control = manifest.get("control")
    if not isinstance(control, dict):
        errors.append("control must be an object")
    else:
        if control.get("id") != "control_421m":
            errors.append("control.id must be control_421m")
        if control.get("trainable") is not False:
            errors.append("control.trainable must be false")
        if control.get("required") is not True:
            errors.append("control.required must be true")

    candidates = manifest.get("candidates")
    if not isinstance(candidates, list):
        errors.append("candidates must be an array")
    else:
        ids = [candidate.get("id") for candidate in candidates if isinstance(candidate, dict)]
        if ids != list(CANDIDATES):
            errors.append("candidates must preserve the registered order and ids")
        if len(ids) != len(set(ids)):
            errors.append("candidates must not contain duplicate ids")

    cell_contract = manifest.get("cell_contract")
    if not isinstance(cell_contract, dict):
        errors.append("cell_contract must be an object")
    else:
        if cell_contract.get("shared_forward_once_per_batch") is not True:
            errors.append("shared_forward_once_per_batch must be true")
        if cell_contract.get("allowed_cell_components") != list(CELL_COMPONENTS):
            errors.append("allowed_cell_components changed")
        if cell_contract.get("forbidden_cell_components") != list(FORBIDDEN_CELL_COMPONENTS):
            errors.append("forbidden_cell_components changed")

    for field in ("scales", "comparison_arms", "required_metrics", "required_gates"):
        if not isinstance(manifest.get(field), list) or not manifest[field]:
            errors.append(f"{field} must be a non-empty array")
    if manifest.get("required_metrics") != list(REQUIRED_METRICS):
        errors.append("required_metrics changed")
    if manifest.get("required_gates") != list(REQUIRED_GATES):
        errors.append("required_gates changed")
    return errors


def validate_result(result: dict[str, Any]) -> list[str]:
    if not isinstance(result, dict):
        return ["result must be an object"]
    errors: list[str] = []
    if result.get("schema") != RESULT_SCHEMA:
        errors.append(f"schema must be {RESULT_SCHEMA}")
    if result.get("authority") != "qualification_only":
        errors.append("authority must remain qualification_only")
    if result.get("runtime_posture") != POSTURE:
        errors.append("runtime_posture must remain SHADOW_ONLY/DENY_ALL/HOLD_NO_GO")
    candidate = result.get("candidate")
    if candidate not in CANDIDATES:
        errors.append("candidate is not a registered bake-off candidate")

    artifact = result.get("artifact")
    if not isinstance(artifact, dict) or not artifact.get("digest"):
        errors.append("artifact.digest is required")
    metrics = result.get("metrics")
    if not isinstance(metrics, dict):
        errors.append("metrics must be an object")
    else:
        for key in REQUIRED_METRICS:
            if key not in metrics:
                errors.append(f"metrics.{key} is required")
    gates = result.get("gates")
    if not isinstance(gates, dict):
        errors.append("gates must be an object")
    else:
        for key in REQUIRED_GATES:
            if gates.get(key) is not True:
                errors.append(f"gates.{key} must be true")
    components = result.get("cell_components")
    if not isinstance(components, list) or any(type(item) is not str for item in components):
        errors.append("cell_components must be a string array")
    else:
        if components != list(CELL_COMPONENTS):
            errors.append("cell_components must match the lightweight Cell contract")
        if any(component in components for component in FORBIDDEN_CELL_COMPONENTS):
            errors.append("forbidden per-Cell model component present")
    return errors


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("manifest")
    validate = subparsers.add_parser("validate")
    validate.add_argument("result", type=argparse.FileType("r"))
    args = parser.parse_args(argv)
    if args.command == "manifest":
        json.dump(
            {
                "schema": SCHEMA,
                "authority": "qualification_only",
                "runtime_posture": POSTURE,
                "candidates": list(CANDIDATES),
                "cell_components": list(CELL_COMPONENTS),
                "required_metrics": list(REQUIRED_METRICS),
                "required_gates": list(REQUIRED_GATES),
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0
    result = json.load(args.result)
    errors = validate_result(result)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("valid shared-stem qualification result shape")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
