#!/usr/bin/env python3
"""Deterministic, model-free runners for the multimodal and NDU experiments.

The runner intentionally consumes observations produced by an external model
executor.  It never trains, selects, activates, or promotes an artifact.  A
receipt is therefore evidence of a bounded measurement, not evidence of
production readiness or of an emergent capability.
"""

import argparse
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable


RECEIPT_SCHEMA = "hepta.shared-stem-experiment-receipt.v1"
CONFIG_SCHEMA = "hepta.shared-stem-experiment-config.v1"
MODALITIES = {"text", "image", "video", "audio"}
MODALITY_ARMS = (
    "text_text",
    "image_text",
    "audio_text",
    "video_text",
    "text_image",
    "text_audio",
)
NDU_ARMS = (
    "no_system2",
    "replay_only",
    "routing",
    "split_proposal",
    "full_resource_allocation",
)
SPLITS = {"train", "validation", "holdout", "future"}
STATUSES = {"completed", "failed", "abstained", "unavailable"}
REQUIRED_METRICS = (
    "task_utility",
    "active_flops",
    "latency_ms",
    "peak_rss_bytes",
    "gpu_peak_bytes",
    "retention_score",
    "old_task_regression",
)
OPTIONAL_METRICS = (
    "negative_transfer",
    "new_cell_incremental_cost",
    "calibration_error",
    "ood_false_acceptance",
)
REQUIRED_CONTEXT = (
    "objective_digest",
    "stem_digest",
    "dataset_digest",
    "host_profile_digest",
    "measurement_interval_digest",
    "seed",
    "cell_count",
    "training_budget",
)
REQUIRED_ARTIFACT_DIGESTS = ("model_digest", "preprocessor_digest", "head_digest")
BASELINE_METRICS = (
    "task_utility",
    "active_flops",
    "latency_ms",
    "peak_rss_bytes",
    "gpu_peak_bytes",
    "retention_score",
    "old_task_regression",
)
BASELINE_REQUIRED_FIELDS = (
    "baseline_status",
    "baseline_id",
    "baseline_model_digest",
    "baseline_preprocessor_digest",
    "baseline_head_digest",
)


class ExperimentError(ValueError):
    """Raised for malformed or incomplete experiment inputs."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise ExperimentError(f"{path} must contain a JSON object")
    return value


def _finite_number(value: Any, name: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExperimentError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise ExperimentError(f"{name} must be finite and >= {minimum}")
    return number


def _require_digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ExperimentError(f"{name} must be a lowercase SHA-256 digest")
    return value


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    if config.get("schema") != CONFIG_SCHEMA:
        raise ExperimentError("unexpected experiment config schema")
    experiment_id = config.get("experiment_id")
    kind = config.get("kind")
    if not isinstance(experiment_id, str) or not experiment_id:
        raise ExperimentError("experiment_id is required")
    if kind not in {"multimodal_differentiation", "ndu_system2_ablation"}:
        raise ExperimentError("kind must identify a supported experiment")
    arms = config.get("arms")
    if not isinstance(arms, list) or not arms:
        raise ExperimentError("arms must be a non-empty array")
    arm_ids: list[str] = []
    for arm in arms:
        if not isinstance(arm, dict):
            raise ExperimentError("each arm must be an object")
        arm_id = arm.get("id")
        if not isinstance(arm_id, str) or not arm_id or arm_id in arm_ids:
            raise ExperimentError("arm ids must be unique non-empty strings")
        arm_ids.append(arm_id)
        if kind == "multimodal_differentiation":
            input_modality = arm.get("input_modality")
            output_modality = arm.get("output_modality")
            if input_modality not in MODALITIES or output_modality not in MODALITIES:
                raise ExperimentError(f"invalid modality pair in arm {arm_id}")
        else:
            if arm_id not in NDU_ARMS:
                raise ExperimentError(f"invalid System 2 arm {arm_id}")
    expected = set(MODALITY_ARMS if kind == "multimodal_differentiation" else NDU_ARMS)
    if set(arm_ids) != expected:
        raise ExperimentError("config must contain exactly the preregistered arm set")
    evaluation = config.get("evaluation")
    if not isinstance(evaluation, dict):
        raise ExperimentError("evaluation block is required")
    if evaluation.get("split") not in SPLITS:
        raise ExperimentError("evaluation.split must be train, validation, holdout or future")
    if not isinstance(evaluation.get("paired_by"), str) or not evaluation["paired_by"]:
        raise ExperimentError("evaluation.paired_by is required")
    if evaluation.get("context_fields") != list(REQUIRED_CONTEXT):
        raise ExperimentError("evaluation.context_fields must preserve the canonical context order")
    for field in ("same_stem_digest_required", "same_seed_required", "artifact_digest_stability_required"):
        if evaluation.get(field) is not True:
            raise ExperimentError(f"evaluation.{field} must be true")
    baseline = evaluation.get("baseline")
    if not isinstance(baseline, dict):
        raise ExperimentError("evaluation.baseline is required")
    if kind == "multimodal_differentiation":
        if baseline.get("enabled") is not True or baseline.get("kind") != "single_modality":
            raise ExperimentError("multimodal evaluation requires an independent single-modality baseline")
        if baseline.get("paired_by") != evaluation["paired_by"]:
            raise ExperimentError("baseline.paired_by must match evaluation.paired_by")
        if baseline.get("required_metrics") != list(BASELINE_METRICS):
            raise ExperimentError("baseline.required_metrics must preserve the canonical metric order")
    else:
        if baseline.get("enabled") is not False:
            raise ExperimentError("NDU evaluation does not use an independent modality baseline")
        if evaluation.get("control_arm") != "no_system2":
            raise ExperimentError("NDU evaluation must use no_system2 as its fixed control arm")
    min_rows = evaluation.get("min_rows_per_arm")
    if isinstance(min_rows, bool) or not isinstance(min_rows, int) or min_rows < 1:
        raise ExperimentError("evaluation.min_rows_per_arm must be a positive integer")
    metrics = config.get("required_metrics")
    if metrics != list(REQUIRED_METRICS):
        raise ExperimentError("required_metrics must preserve the canonical metric order")
    authority = config.get("authority")
    if authority != {
        "production_accepted": False,
        "selection_authority": False,
        "training_authority": False,
    }:
        raise ExperimentError("experiment configs cannot grant authority")
    budgets = config.get("budgets")
    if not isinstance(budgets, dict):
        raise ExperimentError("budgets are required")
    for key in ("max_active_flops", "max_latency_ms", "max_peak_memory_bytes"):
        _finite_number(budgets.get(key), f"budgets.{key}", minimum=1)
    return config


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]], str]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ExperimentError(f"cannot read observations {path}: {error}") from error
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ExperimentError(f"observations are not valid UTF-8: {error}") from error
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ExperimentError(f"invalid JSONL at line {line_no}: {error}") from error
        if not isinstance(row, dict):
            raise ExperimentError(f"observation line {line_no} must be an object")
        rows.append(row)
    if not rows:
        raise ExperimentError("observation JSONL is empty")
    return rows, hashlib.sha256(raw).hexdigest()


def validate_observation(row: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    paired_by = config["evaluation"]["paired_by"]
    for key in ("run_id", "arm_id", "split", "status", paired_by):
        if not isinstance(row.get(key), str) or not row[key]:
            raise ExperimentError(f"observation.{key} is required")
    arm_ids = {arm["id"] for arm in config["arms"]}
    if row["arm_id"] not in arm_ids:
        raise ExperimentError(f"unknown arm {row['arm_id']}")
    if row["split"] not in SPLITS or row["status"] not in STATUSES:
        raise ExperimentError("invalid observation split or status")
    for field in REQUIRED_CONTEXT:
        if field in {"seed", "cell_count", "training_budget"}:
            minimum = 0 if field == "seed" else 1
            if isinstance(row.get(field), bool) or not isinstance(row.get(field), int) or row[field] < minimum:
                raise ExperimentError(f"observation.{field} must be an integer >= {minimum}")
        else:
            _require_digest(row.get(field), f"observation.{field}")
    for field in REQUIRED_ARTIFACT_DIGESTS:
        _require_digest(row.get(field), f"observation.{field}")
    if config["kind"] == "multimodal_differentiation":
        for field in BASELINE_REQUIRED_FIELDS:
            value = row.get(field)
            if field == "baseline_status":
                if value not in STATUSES:
                    raise ExperimentError("observation.baseline_status must be a known status")
            elif field == "baseline_id":
                if not isinstance(value, str) or not value:
                    raise ExperimentError("observation.baseline_id is required")
            else:
                _require_digest(value, f"observation.{field}")
        if row["baseline_status"] == "completed":
            for metric in BASELINE_METRICS:
                minimum = -math.inf if metric == "task_utility" else 0.0
                _finite_number(row.get(f"baseline_{metric}"), f"observation.baseline_{metric}", minimum=minimum)
    kind = config["kind"]
    if kind == "multimodal_differentiation":
        arm = next(arm for arm in config["arms"] if arm["id"] == row["arm_id"])
        if row.get("input_modality") != arm["input_modality"] or row.get("output_modality") != arm["output_modality"]:
            raise ExperimentError(f"modality metadata does not match arm {row['arm_id']}")
    else:
        if row.get("system2_variant") != row["arm_id"]:
            raise ExperimentError(f"system2_variant must match arm {row['arm_id']}")
    if row["status"] == "completed":
        for metric in REQUIRED_METRICS:
            minimum = -math.inf if metric == "task_utility" else 0.0
            _finite_number(row.get(metric), f"observation.{metric}", minimum=minimum)
        for metric in OPTIONAL_METRICS:
            if metric in row:
                _finite_number(row[metric], f"observation.{metric}")
    if "task_success" in row and not isinstance(row["task_success"], bool):
        raise ExperimentError("task_success must be boolean")
    return row


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return statistics.fmean(values) if values else None


def summarize_arm(rows: list[dict[str, Any]], arm_id: str, split: str) -> dict[str, Any]:
    selected = [row for row in rows if row["arm_id"] == arm_id and row["split"] == split]
    completed = [row for row in selected if row["status"] == "completed"]
    utility = [float(row["task_utility"]) for row in completed]
    flops = [float(row["active_flops"]) for row in completed]
    latency = [float(row["latency_ms"]) for row in completed]
    rss = [float(row["peak_rss_bytes"]) for row in completed]
    gpu = [float(row["gpu_peak_bytes"]) for row in completed]
    retention = [float(row["retention_score"]) for row in completed]
    regression = [float(row["old_task_regression"]) for row in completed]
    optional = {
        metric: [float(row[metric]) for row in completed if metric in row]
        for metric in OPTIONAL_METRICS
    }
    metric_presence = {
        metric: sum(metric in row for row in selected)
        for metric in REQUIRED_METRICS
    }
    success_rows = [row for row in selected if "task_success" in row]
    success_count = sum(row.get("task_success") is True for row in success_rows)
    result: dict[str, Any] = {
        "arm_id": arm_id,
        "split": split,
        "rows": len(selected),
        "completed_rows": len(completed),
        "survivorship": {
            "denominator_rows": len(selected),
            "completed_rows": len(completed),
            "failed_rows": sum(row["status"] == "failed" for row in selected),
            "abstained_rows": sum(row["status"] == "abstained" for row in selected),
            "unavailable_rows": sum(row["status"] == "unavailable" for row in selected),
            "metric_presence": metric_presence,
            "utility_per_active_flop_uses_completed_rows_only": True,
        },
        "status_counts": {status: sum(row["status"] == status for row in selected) for status in sorted(STATUSES)},
        "task_utility_mean": _mean(utility),
        "utility_per_active_flop": (sum(utility) / sum(flops)) if sum(flops) > 0 else None,
        "latency_ms": {"p50": _percentile(latency, 0.50), "p95": _percentile(latency, 0.95), "p99": _percentile(latency, 0.99)},
        "peak_rss_bytes_max": max(rss) if rss else None,
        "gpu_peak_bytes_max": max(gpu) if gpu else None,
        "retention_score_mean": _mean(retention),
        "old_task_regression_max": max(regression) if regression else None,
        "optional_metric_coverage": {metric: len(values) for metric, values in optional.items()},
        "negative_transfer_mean": _mean(optional["negative_transfer"]),
        "new_cell_incremental_cost_mean": _mean(optional["new_cell_incremental_cost"]),
        "calibration_error_mean": _mean(optional["calibration_error"]),
        "ood_false_acceptance_mean": _mean(optional["ood_false_acceptance"]),
        # Failed, abstained and unavailable rows remain in the denominator when
        # an executor supplies task_success. This prevents selective completion
        # from inflating the apparent task rate.
        "task_success_rate": (success_count / len(selected)) if success_rows and selected else None,
    }
    return result


def _paired_delta(left_rows: list[dict[str, Any]], right_rows: list[dict[str, Any]], paired_by: str, *, right_prefix: str = "") -> dict[str, Any]:
    left = {row[paired_by]: row for row in left_rows}
    right = {row[paired_by]: row for row in right_rows}
    common = sorted(set(left) & set(right))
    complete = [
        (left[key], right[key])
        for key in common
        if left[key]["status"] == "completed" and right[key]["status"] == "completed"
    ]
    missing_or_incomplete = [key for key in common if key not in {left_row[paired_by] for left_row, _ in complete}]

    def delta(metric: str) -> float | None:
        values = [float(left_row[metric]) - float(right_row[f"{right_prefix}{metric}"]) for left_row, right_row in complete]
        return _mean(values)

    return {
        "paired_by": paired_by,
        "paired_rows": len(common),
        "completed_pairs": len(complete),
        "unpaired_left": sorted(set(left) - set(right)),
        "unpaired_right": sorted(set(right) - set(left)),
        "incomplete_pairs": sorted(missing_or_incomplete),
        "external_task": {
            "task_utility_delta_mean": delta("task_utility"),
            "retention_score_delta_mean": delta("retention_score"),
        },
        "resource": {
            "active_flops_delta_mean": delta("active_flops"),
            "latency_ms_delta_mean": delta("latency_ms"),
            "peak_rss_bytes_delta_mean": delta("peak_rss_bytes"),
            "gpu_peak_bytes_delta_mean": delta("gpu_peak_bytes"),
        },
        "old_task": {
            "old_task_regression_delta_mean": delta("old_task_regression"),
        },
    }


def _baseline_result(rows: list[dict[str, Any]], arm_ids: list[str], split: str, paired_by: str) -> dict[str, Any]:
    comparisons: dict[str, Any] = {}
    identity_drift: dict[str, list[str]] = {}
    artifact_drift: dict[str, dict[str, list[str]]] = {}
    for arm_id in arm_ids:
        selected = [row for row in rows if row["arm_id"] == arm_id and row["split"] == split]
        baseline_ids = sorted({row["baseline_id"] for row in selected})
        if len(baseline_ids) > 1:
            identity_drift[arm_id] = baseline_ids
        for field in ("baseline_model_digest", "baseline_preprocessor_digest", "baseline_head_digest"):
            values = sorted({row[field] for row in selected})
            if len(values) > 1:
                artifact_drift.setdefault(arm_id, {})[field] = values
        baseline_rows = [
            {
                **row,
                "status": row["baseline_status"],
                **{metric: row[f"baseline_{metric}"] for metric in BASELINE_METRICS if f"baseline_{metric}" in row},
            }
            for row in selected
        ]
        comparisons[arm_id] = {
            "baseline_ids": baseline_ids,
            "baseline_status_counts": {status: sum(row["baseline_status"] == status for row in selected) for status in sorted(STATUSES)},
            "delta": _paired_delta(selected, baseline_rows, paired_by, right_prefix=""),
        }
    return {
        "kind": "single_modality",
        "comparisons": comparisons,
        "baseline_identity_drift": identity_drift,
        "baseline_artifact_digest_drift": artifact_drift,
    }


def make_receipt(config: dict[str, Any], rows: list[dict[str, Any]], observation_digest: str) -> dict[str, Any]:
    validate_config(config)
    if not rows:
        raise ExperimentError("observations are empty")
    _require_digest(observation_digest, "observation_digest")
    for row in rows:
        validate_observation(row, config)
    context = {field: sorted({row[field] for row in rows}) for field in REQUIRED_CONTEXT}
    for field, values in context.items():
        if len(values) != 1:
            raise ExperimentError(f"observation context drift in {field}")
    arm_artifact_digests = {
        arm_id: {
            field: sorted({row[field] for row in rows if row["arm_id"] == arm_id})
            for field in REQUIRED_ARTIFACT_DIGESTS
        }
        for arm_id in (arm["id"] for arm in config["arms"])
    }
    artifact_digest_drift = {
        arm_id: {
            field: values
            for field, values in arm_artifact_digests[arm_id].items()
            if len(values) > 1
        }
        for arm_id in (arm["id"] for arm in config["arms"])
    }
    artifact_digest_drift = {arm_id: values for arm_id, values in artifact_digest_drift.items() if values}
    split = config["evaluation"]["split"]
    arms = [arm["id"] for arm in config["arms"]]
    paired_by = config["evaluation"]["paired_by"]
    seen_pairs: set[tuple[str, str]] = set()
    for row in rows:
        if row["split"] != split:
            continue
        pair = (row["arm_id"], row[paired_by])
        if pair in seen_pairs:
            raise ExperimentError(f"duplicate evaluation row for {pair[0]}:{pair[1]}")
        seen_pairs.add(pair)
    summaries = [summarize_arm(rows, arm_id, split) for arm_id in arms]
    min_rows = config["evaluation"]["min_rows_per_arm"]
    insufficient = [item["arm_id"] for item in summaries if item["completed_rows"] < min_rows]
    evaluation_sets = {
        arm_id: {row[paired_by] for row in rows if row["arm_id"] == arm_id and row["split"] == split}
        for arm_id in arms
    }
    reference_set = next((values for values in evaluation_sets.values() if values), set())
    unpaired = {
        arm_id: sorted(values ^ reference_set)
        for arm_id, values in evaluation_sets.items()
        if values != reference_set
    }
    budgets = config["budgets"]
    budget_violations = {
        arm_id: [
            row[paired_by]
            for row in rows
            if row["arm_id"] == arm_id
            and row["split"] == split
            and row["status"] == "completed"
            and (
                row["active_flops"] > budgets["max_active_flops"]
                or row["latency_ms"] > budgets["max_latency_ms"]
                or row["peak_rss_bytes"] > budgets["max_peak_memory_bytes"]
                or row["gpu_peak_bytes"] > budgets["max_peak_memory_bytes"]
            )
        ]
        for arm_id in arms
    }
    budget_violations = {arm_id: examples for arm_id, examples in budget_violations.items() if examples}
    if config["kind"] == "multimodal_differentiation":
        baseline_comparison = _baseline_result(rows, arms, split, paired_by)
        ndu_control_arm = None
        ndu_paired_deltas = None
        digest_blockers = bool(
            artifact_digest_drift
            or baseline_comparison["baseline_identity_drift"]
            or baseline_comparison["baseline_artifact_digest_drift"]
        )
    else:
        control_arm = config["evaluation"]["control_arm"]
        control_rows = [row for row in rows if row["arm_id"] == control_arm and row["split"] == split]
        baseline_comparison = None
        ndu_control_arm = control_arm
        ndu_paired_deltas = {
            arm_id: _paired_delta(
                [row for row in rows if row["arm_id"] == arm_id and row["split"] == split],
                control_rows,
                paired_by,
            )
            for arm_id in arms
            if arm_id != control_arm
        }
        digest_blockers = bool(artifact_digest_drift)
    if budget_violations:
        disposition = "resource_budget_exceeded"
    elif digest_blockers:
        disposition = "artifact_digest_drift"
    elif insufficient:
        disposition = "insufficient_evidence"
    elif unpaired:
        disposition = "unpaired_evaluation_set"
    else:
        disposition = "diagnostic_complete"
    result = {
        "evaluation_split": split,
        "arms": summaries,
        "insufficient_arms": insufficient,
        "unpaired_arms": unpaired,
        "budget_violations": budget_violations,
        "artifact_digest_drift": artifact_digest_drift,
        "paired_by": paired_by,
        "baseline_comparison": baseline_comparison,
        "ndu_control_arm": ndu_control_arm,
        "ndu_paired_deltas": ndu_paired_deltas,
        "disposition": disposition,
        "winner": None,
    }
    payload = {
        "schema": RECEIPT_SCHEMA,
        "experiment_id": config["experiment_id"],
        "kind": config["kind"],
        "config_digest": digest(config),
        "observation_digest": observation_digest,
        "observation_count": len(rows),
        "execution_context": {field: values[0] for field, values in context.items()},
        "arm_artifact_digests": arm_artifact_digests,
        "result": result,
    }
    return {
        **payload,
        "receipt_digest": digest(payload),
        "authority": {
            "authority_delta": "none",
            "production_accepted": False,
            "selection_authority": False,
            "training_authority": False,
        },
    }


def verify_receipt(receipt: dict[str, Any], config: dict[str, Any], rows: list[dict[str, Any]], observation_digest: str) -> None:
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise ExperimentError("unexpected receipt schema")
    expected = make_receipt(config, rows, observation_digest)
    for key in (
        "experiment_id",
        "kind",
        "config_digest",
        "observation_digest",
        "observation_count",
        "execution_context",
        "arm_artifact_digests",
        "result",
    ):
        if receipt.get(key) != expected.get(key):
            raise ExperimentError(f"receipt mismatch at {key}")
    if receipt.get("receipt_digest") != expected["receipt_digest"]:
        raise ExperimentError("receipt digest mismatch")
    if receipt.get("authority") != expected["authority"]:
        raise ExperimentError("receipt authority posture mismatch")


def _command() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-config")
    validate.add_argument("config", type=Path)
    run = subparsers.add_parser("run")
    run.add_argument("config", type=Path)
    run.add_argument("observations", type=Path)
    run.add_argument("output", type=Path)
    verify = subparsers.add_parser("verify")
    verify.add_argument("config", type=Path)
    verify.add_argument("observations", type=Path)
    verify.add_argument("receipt", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _command()
    args = parser.parse_args(argv)
    try:
        config = validate_config(read_json(args.config))
        if args.command == "validate-config":
            print(json.dumps({"valid": True, "config_digest": digest(config)}, sort_keys=True))
            return 0
        rows, observation_digest = _load_jsonl(args.observations)
        if args.command == "run":
            receipt = make_receipt(config, rows, observation_digest)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps({"receipt": str(args.output), "receipt_digest": receipt["receipt_digest"]}, sort_keys=True))
            return 0
        verify_receipt(read_json(args.receipt), config, rows, observation_digest)
        print(json.dumps({"valid": True, "receipt": str(args.receipt)}, sort_keys=True))
        return 0
    except ExperimentError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
