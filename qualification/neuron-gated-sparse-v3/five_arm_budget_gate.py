#!/usr/bin/env python3
"""Fail-closed five-arm, five-budget A1-A4 study verifier.

Recounts ACTUAL staged private safetensors bytes and joins five independently
signed paired-evaluator envelopes. Validating these files does not authenticate
a model invocation, its training history, a target host or a production owner.
Never select/promote a Cell on this report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

from a0_deployment_evidence import (
    EvidenceError, hex_digest, load_public_key, need, verify_signed,
)
import paired_shadow_analysis as paired

SCHEMA = "hepta.neuron.five-arm-matched-budget-bundle.v1"
BUDGETS = (2_048, 8_192, 16_384, 65_536, 262_144)
ARMS = ("no-change-v1", "v2", "v3", "ssm", "min_gru")
DTYPE_BYTES = {
    "BOOL": 1, "U8": 1, "I8": 1, "F16": 2, "BF16": 2, "I16": 2,
    "F32": 4, "I32": 4, "F64": 8, "I64": 8,
}
MAX_HEADER_BYTES = 1 << 20
MAX_WEIGHT_BYTES = 512 << 20
MAX_TENSORS = 4_096


def strictly_json(data: bytes) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            need(key not in result, "duplicate JSON key in safetensors/manifest")
            result[key] = value
        return result

    def reject(value: str) -> None:
        raise EvidenceError(f"nonfinite JSON number: {value}")

    try:
        return json.loads(data, object_pairs_hook=unique, parse_constant=reject)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("invalid UTF-8 JSON") from exc


def file_in(root: Path, raw: Any) -> Path:
    need(isinstance(raw, str) and raw and len(raw) <= 240, "invalid relative artifact path")
    relative = Path(raw)
    need(not relative.is_absolute() and all(part not in (".", "..") for part in relative.parts),
         "path traversal or absolute path rejected")
    current = root
    for part in relative.parts:
        current = current / part
        need(not current.is_symlink(), "symbolic link in artifact path")
    resolved = current.resolve()
    need(resolved.is_relative_to(root.resolve()) and resolved.is_file(),
         "artifact file missing/outside frozen evidence root")
    return resolved


def actual_safetensors(
    path: Path, expected_sha256: str,
) -> tuple[int, dict[str, tuple[int, ...]]]:
    hex_digest(expected_sha256, "selected private weights sha256")
    size = path.stat().st_size
    need(10 <= size <= MAX_WEIGHT_BYTES, "invalid physical weight file size")
    with path.open("rb") as handle:
        first = handle.read(8)
        header_size = int.from_bytes(first, "little")
        need(2 <= header_size <= MAX_HEADER_BYTES and header_size <= size - 8,
             "safetensors header missing/too large")
        header = strictly_json(handle.read(header_size))
        need(isinstance(header, dict) and 0 < len(header) <= MAX_TENSORS + 1,
             "invalid safetensors tensor inventory")
        remaining_data = size - 8 - header_size
        tensors: dict[str, tuple[int, ...]] = {}
        occupied: list[tuple[int, int]] = []
        count = 0
        for name, entry in header.items():
            if name == "__metadata__":
                need(isinstance(entry, dict) and all(
                    isinstance(k, str) and isinstance(v, str) for k, v in entry.items()
                ), "invalid safetensors metadata")
                continue
            need(isinstance(name, str) and name and isinstance(entry, dict)
                 and set(entry) == {"dtype", "shape", "data_offsets"},
                 "malformed physical tensor entry")
            dtype, shape, offsets = entry["dtype"], entry["shape"], entry["data_offsets"]
            need(dtype in DTYPE_BYTES and isinstance(shape, list)
                 and 0 < len(shape) <= 8
                 and all(type(dim) is int and 0 < dim <= 1_048_576 for dim in shape)
                 and isinstance(offsets, list) and len(offsets) == 2
                 and all(type(offset) is int for offset in offsets),
                 "invalid tensor dtype/dimensions/offsets")
            n = 1
            for dim in shape:
                n *= dim
                need(n <= 100_000_000, "unbounded tensor shape")
            start, end = offsets
            need(0 <= start < end <= remaining_data
                 and end - start == n * DTYPE_BYTES[dtype],
                 "tensor byte count does not match physical offsets")
            occupied.append((start, end))
            tensors[name] = tuple(shape)
            count += n
        need(tensors, "safetensors with no private weight tensors")
        occupied.sort()
        previous = 0
        for start, end in occupied:
            need(start == previous, "safetensors overlap or undeclared private bytes")
            previous = end
        need(previous == remaining_data, "undeclared trailing private weights")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    need(digest.hexdigest() == expected_sha256, "physical private weight SHA mismatch")
    return count, tensors


def verify_architecture(
    arm: str, architecture: dict[str, Any], tensors: dict[str, tuple[int, ...]],
) -> int:
    need(isinstance(architecture, dict), "missing exact Cell architecture")
    if arm == "min_gru":
        need(set(architecture) == {"width", "rank"}, "minGRU width/rank required")
        width, rank = architecture["width"], architecture["rank"]
        need(type(width) is int and type(rank) is int and 1 <= rank <= width <= 256,
             "invalid minGRU rank/width")
        required = {
            "temporal.gate_input": (rank, width),
            "temporal.gate_output": (width, rank),
            "temporal.candidate_input": (rank, width),
            "temporal.candidate_output": (width, rank),
            "temporal.gate_bias": (width,),
            "temporal.candidate_bias": (width,),
        }
        for name, expected in required.items():
            need(tensors.get(name) == expected, f"{name}: missing or wrong physical shape")
        need(not {name for name in tensors if name.startswith("temporal.")} - set(required),
             "unexpected minGRU temporal tensor")
        return 4 * width * rank + 2 * width
    need(architecture == {}, f"{arm}: unsupported architecture descriptor")
    return 0


def validate_bundle(
    bundle: Any,
    evaluations: dict[int, dict[str, Any]],
    evaluator_fingerprint: str,
    model_root: Path,
    *,
    require_a4: bool = True,
) -> dict[str, Any]:
    need(isinstance(bundle, dict) and set(bundle) == {"schema", "tiers"},
         "invalid study bundle schema fields")
    need(bundle["schema"] == SCHEMA, "wrong five-arm bundle version")
    tiers = bundle["tiers"]
    need(isinstance(tiers, list) and len(tiers) == len(BUDGETS),
         "all five budget tiers required")
    need(set(evaluations) == set(BUDGETS), "missing signed evaluator budget")
    report_tiers: list[dict[str, Any]] = []
    common = None
    common_cases = None
    common_baseline = None
    for idx, item in enumerate(tiers):
        cap = BUDGETS[idx]
        need(isinstance(item, dict)
             and set(item) == {"parameter_cap", "signed_evaluation", "models"}
             and type(item["parameter_cap"]) is int
             and item["parameter_cap"] == cap, "incorrect or reordered budget tier")
        declared = item["models"]
        need(isinstance(declared, dict) and set(declared) == set(ARMS),
             "all five comparator models required at every budget tier")
        payload = evaluations[cap]
        need(payload["total_parameter_ceiling"] == cap,
             "signed parameter ceiling disagrees with actual tier")
        need(set(payload["arms"]) == set(ARMS)
             and payload["no_change_arm"] == "no-change-v1",
             "signed evaluation missing one of five model arms")
        if require_a4:
            need(payload["phase"] == "A4", "strict final matrix requires signed A4")
        paired_report = paired.analyze(payload, evaluator_fingerprint)
        current_common = (
            payload["host_profile_digest"], payload["a0_registry_sha256"],
            payload["training_dataset_digest"], payload["training_cutoff_utc"],
            payload["evaluation_asof_utc"], payload["preregistered_at_utc"],
            payload["evaluator_key_id"], payload["selector_key_id"],
            payload["executor_key_id"],
            payload["candidate_optimizer_steps"],
            tuple(sorted((name, arm["encoder_digest"]) for name, arm in payload["arms"].items())),
        )
        if common is None:
            common = current_common
        need(current_common == common, "encoder/host/dataset/cutoff/steps/owners changed across tiers")
        cases = {
            (case["cell_id"], case["case_id"], case["input_digest"], case["split"],
             case["event_time_utc"], case["label_available_at_utc"])
            for case in payload["samples"]
        }
        if common_cases is None:
            common_cases = cases
        need(cases == common_cases, "budget arms not evaluated on identical cases")
        model_reports = {}
        for arm in ARMS:
            spec = declared[arm]
            need(isinstance(spec, dict) and set(spec) == {
                "path", "sha256", "architecture",
            }, "invalid private weight descriptor")
            physical_path = file_in(model_root, spec["path"])
            count, shapes = actual_safetensors(physical_path, spec["sha256"])
            verifier_temporal = verify_architecture(arm, spec["architecture"], shapes)
            signed = payload["arms"][arm]
            need(count == signed["parameter_count_total"],
                 "claimed parameters disagree with actual private tensor count")
            need(signed["artifact_digest"] == spec["sha256"],
                 "signed evaluator artifact does not bind physical private weights")
            need(count <= cap, "Cell-private model exceeds registered parameter tier")
            model_reports[arm] = {
                "physical_private_tensors": len(shapes),
                "physical_private_parameters": count,
                "min_gru_temporal_parameters": verifier_temporal if arm == "min_gru" else None,
                "state_bytes_claimed_by_evaluator": signed["state_bytes"],
                "sha256": spec["sha256"],
            }
        baseline_hash = model_reports["no-change-v1"]["sha256"]
        if common_baseline is None:
            common_baseline = baseline_hash
        need(baseline_hash == common_baseline,
             "no-change baseline artifact was changed between budgets")
        report_tiers.append({
            "parameter_cap": cap,
            "phase": payload["phase"],
            "models": model_reports,
            "paired_counts": paired_report["split_counts"],
            "comparisons_vs_no_change": paired_report["comparisons_vs_frozen_no_change"],
            "four_scale_slots_claimed": paired_report["all_scale_slots_observed"],
        })
    return {
        "schema": "hepta.neuron.five-arm-matched-budget-report.v1",
        "study_status": "RESEARCH_STRUCTURAL_AND_SIGNED_CLAIMS_ONLY",
        "parameter_tiers": list(BUDGETS),
        "five_arms": list(ARMS),
        "physical_private_weight_hash_and_tensor_shapes_verified": True,
        "frozen_encoder_and_identical_case_claims_cross_checked": True,
        "qualified_real_training_or_target_host": False,
        "independent_owner_and_checkpoint_attestation_verified": False,
        "production_qualification": False,
        "ndu_eligible": False,
        "decision": "NO_PRODUCTION_PROMOTION",
        "tiers": report_tiers,
        "limitations": [
            "Verified private safetensors do not prove the selected model is complete or deployed.",
            "Frozen-Encoder identity and train/evaluation provenance are signed assertions, not independently observed model execution.",
            "No authenticated training-time CPU/GPU/FLOPs or hyperparameter-tuning parity.",
            "A4 scale receipt digests are claims without a trusted host and independent checkpoint readback.",
            "Abstention calibration, physical model invocation, WAL/CAS/fence and actual NDU uplift still require independent acceptance.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--evaluation-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--trusted-evaluator-public-key", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--allow-pre-a4", action="store_true",
                        help="study-only A1-A3 audit; never a production qualification")
    args = parser.parse_args()
    try:
        evaluator, fingerprint = load_public_key(args.trusted_evaluator_public_key)
        bundle = strictly_json(args.bundle.read_bytes())
        need(isinstance(bundle, dict) and isinstance(bundle.get("tiers"), list),
             "missing five budget tiers")
        evaluations = {}
        for tier in bundle["tiers"]:
            need(isinstance(tier, dict), "invalid budget entry")
            cap = tier["parameter_cap"]
            need(type(cap) is int and cap in BUDGETS and cap not in evaluations,
                 "unknown/duplicate budget")
            signed = file_in(args.evaluation_root, tier["signed_evaluation"])
            evaluations[cap] = verify_signed(signed, evaluator, fingerprint, paired.SCHEMA)
        report = validate_bundle(bundle, evaluations, fingerprint, args.model_root,
                                 require_a4=not args.allow_pre_a4)
    except (EvidenceError, ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({"status": "BLOCKED_FIVE_ARM_BUDGET_GATE", "error": str(exc)}),
              file=sys.stderr)
        return 2
    output = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if args.report:
        args.report.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
