"""Fail-closed six-stage Neuron model-replacement evidence preflight.

Scores are independently recomputed from supplied row predictions, but supplied
rows, model loads, signer status and hardware measurements are NOT authenticated
by this process. A passing preflight is NEVER production qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

EXPECTED = ("laya_english_421m", "laya_typed_421m", "laya_multi_322m",
            "arctic_305m", "harrier_270m")
SPLITS = ("train", "calibration", "future_1", "future_2", "ood")
SCALES = (64, 256, 1024, 4096)
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
STAGES = ("1_baseline", "2_direct_replacement", "3_encoder_head",
          "4_calibration_safety", "5_host_resources", "6_lifecycle")


def _sha(value: Any, width: int = 64) -> bool:
    return isinstance(value, str) and (HEX40 if width == 40 else HEX64).fullmatch(value) is not None


def _number(v: Any) -> bool:
    return type(v) in (int, float) and math.isfinite(v)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate_registry(registry: Any) -> list[str]:
    errors = []
    if not isinstance(registry, dict) or set(registry) != {
            "schema", "models", "production_activation_allowed", "authority", "mode"}:
        return ["registry requires exact top-level fields"]
    if (registry["schema"] != "hepta.neuron.replacement-pins.v1" or
            registry["production_activation_allowed"] is not False or
            registry["authority"] != "DENY_ALL" or registry["mode"] != "SHADOW_ONLY"):
        errors.append("registry must be shadow-only and deny all authority")
    models = registry["models"]
    if not isinstance(models, dict) or set(models) != set(EXPECTED):
        return errors + ["registry must enumerate precisely five pinned model identities"]
    for name, spec in models.items():
        if not isinstance(spec, dict) or set(spec) != {
                "repository", "revision", "weight_sha256", "weight_file",
                "role", "license", "parameter_class"}:
            errors.append(f"{name}: incomplete model provenance")
            continue
        if (not isinstance(spec["repository"], str) or spec["repository"].count("/") != 1 or
                not _sha(spec["revision"], 40) or not _sha(spec["weight_sha256"]) or
                spec["weight_file"] != "model.safetensors"):
            errors.append(f"{name}: invalid full revision, weight SHA or file")
        expected_role = "full_policy" if name.startswith("laya_") else "encoder_plus_new_head"
        if spec["role"] != expected_role or spec["license"] not in ("mit", "apache-2.0"):
            errors.append(f"{name}: role/license mismatch")
    return errors


def score_rows(rows: Any, *, classes: int = 4, threshold: float = .7) -> dict:
    """Calculate task/selection metrics from untouched rows (not model claims)."""
    if (type(classes) is not int or not 2 <= classes <= 256 or
            not _number(threshold) or not 0 < threshold < 1 or
            not isinstance(rows, list) or not rows):
        raise ValueError("valid nonempty classified cohort and threshold required")
    seen, supports = set(), [0] * classes
    tp = [0] * classes
    accuracy = ece = brier = nll = covered = accepted_wrong = false_accept = ood_count = 0
    confidences = []
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"source_id", "source_group_id",
                "label", "probabilities", "is_ood", "language"} or
                not isinstance(row["source_id"], str) or not row["source_id"] or
                not isinstance(row["source_group_id"], str) or not row["source_group_id"] or
                not isinstance(row["language"], str) or not row["language"] or
                type(row["label"]) is not int or not 0 <= row["label"] < classes or
                type(row["is_ood"]) is not bool or
                not isinstance(row["probabilities"], list) or len(row["probabilities"]) != classes):
            raise ValueError("invalid row identity, class, OOD or distribution")
        group = row["source_group_id"]
        if group in seen:
            raise ValueError("repeated source group within cohort")
        seen.add(group)
        p = row["probabilities"]
        if any(not _number(x) or not 0 <= x <= 1 for x in p) or abs(sum(p) - 1) > 1e-5:
            raise ValueError("nonfinite, unnormalized or negative class probability")
        label, pred = row["label"], max(range(classes), key=lambda k: (p[k], -k))
        confidence = float(p[pred])
        correct = int(pred == label)
        supports[label] += 1
        tp[label] += correct
        accuracy += correct
        brier += sum((p[k] - (k == label)) ** 2 for k in range(classes))
        nll -= math.log(max(p[label], 1e-15))
        accepted = confidence >= threshold
        covered += accepted
        accepted_wrong += bool(accepted and not correct)
        false_accept += bool(accepted and row["is_ood"])
        ood_count += row["is_ood"]
        confidences.append((confidence, correct))
    n = len(rows)
    for bucket in range(10):
        members = [(c, a) for c, a in confidences if min(int(c * 10), 9) == bucket]
        if members:
            ece += len(members) / n * abs(
                sum(c for c, _ in members) / len(members) -
                sum(a for _, a in members) / len(members))
    return {
        "rows": n, "accuracy": accuracy / n,
        "balanced_accuracy": sum(tp[k] / supports[k] for k in range(classes) if supports[k]) /
                             sum(bool(x) for x in supports),
        "class_support": supports,
        "brier_multiclass_sum": brier / n,
        "nll": nll / n, "ece10": ece,
        "coverage": covered / n,
        "selective_risk": accepted_wrong / covered if covered else None,
        "ood_rows": ood_count,
        "ood_false_accept_rate": false_accept / ood_count if ood_count else None,
        "source_groups_sha256": digest(sorted(seen)),
    }


def _check_arm(name: str, arm: Any, spec: dict) -> list[str]:
    e = []
    if not isinstance(arm, dict):
        return [f"{name}: no real inference evidence"]
    for key, expected in (("repository", spec["repository"]),
                          ("revision", spec["revision"]),
                          ("loaded_weight_sha256", spec["weight_sha256"]),
                          ("runtime_mode", "SHADOW_ONLY")):
        if arm.get(key) != expected:
            e.append(f"{name}: missing/mismatched {key}")
    for key in ("checkpoint_inventory_sha256", "runtime_sha256", "dataset_sha256",
                "model_execution_receipt_sha256", "training_plan_sha256"):
        if not _sha(arm.get(key)):
            e.append(f"{name}: missing full {key}")
    if (arm.get("inference_kind") != spec["role"] or
            arm.get("actual_model_forward_observed") is not True or
            arm.get("no_production_authority") is not True):
        e.append(f"{name}: full policy/encoder role or actual model invocation unproved")
    if name in ("arctic_305m", "harrier_270m"):
        if not _sha(arm.get("trained_head_sha256")) or arm.get("encoder_frozen") is not True:
            e.append(f"{name}: frozen encoder and actual trained Head missing")
    splits = arm.get("splits")
    if not isinstance(splits, dict) or set(splits) != set(SPLITS):
        return e + [f"{name}: complete disjoint split predictions required"]
    seen_groups = set()
    for split in SPLITS:
        rows = splits[split]
        try:
            metrics = score_rows(rows)
            if split == "ood" and metrics["ood_rows"] == 0:
                e.append(f"{name}: OOD split lacks OOD labels")
            if split in ("future_1", "future_2") and any(row["is_ood"] for row in rows):
                e.append(f"{name}: future ID split mislabeled OOD")
            groups = {r["source_group_id"] for r in rows}
            if seen_groups & groups:
                e.append(f"{name}: leaked groups across splits")
            seen_groups |= groups
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            e.append(f"{name}: {split} rejected ({exc})")
    return e


def _check_resources(evidence: Any) -> list[str]:
    if not isinstance(evidence, dict):
        return ["host-resource: no physically observed runs"]
    e = []
    for scale in SCALES:
        row = evidence.get(str(scale))
        if not isinstance(row, dict):
            e.append(f"host-resource: {scale} Cells missing")
            continue
        samples = row.get("latency_samples_ms")
        if (type(row.get("logical_cells")) is not int or row["logical_cells"] != scale or
                type(row.get("active_cells")) is not int or not 1 <= row["active_cells"] <= scale or
                type(row.get("actual_private_head_instances")) is not int or
                row["actual_private_head_instances"] != scale or
                not _sha(row.get("host_runtime_sha256")) or
                not _sha(row.get("physical_model_receipt_sha256")) or
                row.get("target_hardware") is not True or
                type(row.get("peak_rss_bytes")) is not int or row["peak_rss_bytes"] <= 0 or
                type(row.get("gpu_peak_bytes")) is not int or row["gpu_peak_bytes"] < 0 or
                not _number(row.get("throughput_per_second")) or row["throughput_per_second"] <= 0 or
                not isinstance(samples, list) or len(samples) < 100 or
                any(not _number(n) or n <= 0 for n in samples)):
            e.append(f"host-resource: {scale} lacks target-host p95/p99/throughput/RSS evidence")
    return e


def assess(registry: Any, evidence: Any) -> dict:
    errors = {stage: [] for stage in STAGES}
    registry_errors = validate_registry(registry)
    if registry_errors:
        errors["1_baseline"].extend(registry_errors)
        return _result(errors)
    if not isinstance(evidence, dict) or evidence.get("schema") != "hepta.neuron.replacement-evidence.v1":
        errors["1_baseline"].append("frozen real-model evidence bundle absent")
        for stage in STAGES[1:]:
            errors[stage].append("stage has no recorded execution receipts")
        return _result(errors)
    arms = evidence.get("arms")
    if not isinstance(arms, dict) or set(arms) != set(EXPECTED):
        errors["1_baseline"].append("all five separately observed arms are required")
        arms = arms if isinstance(arms, dict) else {}
    for name in EXPECTED:
        err = _check_arm(name, arms.get(name), registry["models"][name])
        stage = ("1_baseline" if name in EXPECTED[:2] else
                 "2_direct_replacement" if name == EXPECTED[2] else "3_encoder_head")
        errors[stage].extend(err)
    if all(isinstance(arms.get(n), dict) for n in EXPECTED):
        datasets = {arms[n].get("dataset_sha256") for n in EXPECTED}
        plans = {arms[n].get("training_plan_sha256") for n in EXPECTED}
        if len(datasets) != 1:
            errors["3_encoder_head"].append("different datasets invalidate direct comparison")
        if len(plans) != 1:
            errors["3_encoder_head"].append("training budget/seed/Head plan differs between arms")
        # Raw per-row identities must also match, not merely a user-supplied manifest.
        try:
            for split in SPLITS:
                identities = [{(r["source_id"], r["source_group_id"], r["label"], r["is_ood"])
                               for r in arms[n]["splits"][split]} for n in EXPECTED]
                if any(rows != identities[0] for rows in identities[1:]):
                    errors["3_encoder_head"].append(f"{split}: arms were not scored on identical rows")
        except (KeyError, TypeError):
            errors["3_encoder_head"].append("missing common row-level evaluation basis")
    safety = evidence.get("safety")
    if not isinstance(safety, dict) or not _sha(safety.get("frozen_threshold_plan_sha256")):
        errors["4_calibration_safety"].append("frozen calibration/abstention threshold plan missing")
    if not isinstance(safety, dict) or safety.get("independent_future_window") is not True:
        errors["4_calibration_safety"].append("independent future/outcome observation absent")
    if not isinstance(safety, dict) or safety.get("class_imbalance_negative_transfer_tested") is not True:
        errors["4_calibration_safety"].append("negative transfer/imbalance evaluation absent")
    errors["5_host_resources"].extend(_check_resources(evidence.get("resources")))
    lifecycle = evidence.get("lifecycle")
    needed = ("artifact_cas_commit", "predecessor_checkpoint_migration", "route_cutover",
              "supervisor_generation_fence", "crash_reopen_reconcile", "rollback_restore",
              "old_generation_final_use_denied")
    if not isinstance(lifecycle, dict):
        errors["6_lifecycle"].append("lifecycle receipts missing")
    else:
        for key in needed:
            if not _sha(lifecycle.get(key)):
                errors["6_lifecycle"].append(f"{key}: missing independent operation receipt SHA")
        if not _sha(lifecycle.get("external_signature_verifier_digest")):
            errors["6_lifecycle"].append("independent cryptographic signature verification unproven")
    # Never infer cryptographic witness validity or deployment merely from
    # caller-supplied hashes/boolean fields. Only an external owner may qualify.
    return _result(errors)


def _result(errors: dict) -> dict:
    return {
        "schema": "hepta.neuron.replacement-preflight.v1",
        "stages": {stage: {"preflight": "BLOCKED" if reasons else "REVIEW_REQUIRED",
                           "blockers": sorted(set(reasons))} for stage, reasons in errors.items()},
        "authority": "DENY_ALL", "mode": "SHADOW_ONLY", "release": "HOLD_NO_GO",
        "independent_observer_verification_required": True,
        "production_activation_allowed": False,
        "all_six_production_blockers_closed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default=str(Path(__file__).with_name("replacement_models.json")))
    parser.add_argument("--evidence", help="untrusted model/host/lifecycle receipt JSON")
    parser.add_argument("--assert-no-production", action="store_true")
    args = parser.parse_args()
    try:
        registry = json.loads(Path(args.registry).read_text())
        evidence = json.loads(Path(args.evidence).read_text()) if args.evidence else None
        result = assess(registry, evidence)
    except (ValueError, OSError, TypeError) as exc:
        print(json.dumps({"status": "REJECTED", "error": str(exc), "authority": "DENY_ALL"}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.assert_no_production:
        return 0 if (not result["production_activation_allowed"] and
                     not result["all_six_production_blockers_closed"]) else 2
    return 0 if all(row["preflight"] == "REVIEW_REQUIRED"
                    for row in result["stages"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
