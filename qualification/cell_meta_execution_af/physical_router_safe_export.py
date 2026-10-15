#!/usr/bin/env python3
"""Minimal, fail-closed Granite research artifact export (not source custody).

Hash original files without publishing their bytes, then serialize only a
narrow, independently checked, nonauthorizing aggregate. A failed/partial job
still exports a safe BLOCKED receipt and returns a nonzero exit status.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

SCHEMA = "hepta.cell-meta-granite-redacted-artifact.v1"
SEEDS = (41, 47, 53)
ARMS = ("no_change", "fixed_router", "learned_router", "adaptive_split")
STATIC = frozenset({
    "source-train.parquet", "source-cal-test.parquet", "source-panel.json",
    "original-source-sha256.txt", "model-files.json", "model-files-source-hash.txt",
    "granite-q24-features.json", "paired-original-source-screen.json",
    "observed-work-frontier.json", "os-meter-joined.json",
    "descriptive-retrospective-summary.json",
    "hardtop1-descriptive-retrospective-summary.json",
})
SEED_SUFFIXES = (
    "trial-panel", "trial-report", "bridge-receipt", "feature-review",
    "numeric-review", "top1-report", "top1-review", "hard-train-report",
    "hard-train-review", "frozen-report", "frozen-review", "fivearm-report",
    "os-meter",
)
EXPECTED = frozenset(STATIC | {
    f"{seed}-{suffix}.json" for seed in SEEDS for suffix in SEED_SUFFIXES
})
SOURCE_SHA = "2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4"
# These refer to the previously pinned, source-checked AG News parquet bytes.
# Equality is an end-of-run integrity check; it is not external provenance signing.
SOURCE_PARQUET_SHA = {
    "source-train.parquet": "cc35afe9d5e7ff01878c9aeba08bb0bdfa16947702789530b216a580a1bc09d5",
    "source-cal-test.parquet": "3171d3aeee227372165bb0f9e84ebf2bfaf5fc870d034f33a5fc568e7995c672",
}
MODEL_NAME = "ibm-granite/granite-embedding-97m-multilingual-r2"
OS_ARMS = (
    "frozen_stage1_no_second_phase_learning", "unsplit_continued_update",
    "fixed_router", "learned_router", "adaptive_split",
)
MAX_FILES = 128
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_SUMMARY_BYTES = 512 * 1024
MAX_REPORT_BYTES = 128 * 1024
HEX64 = re.compile(r"[a-f0-9]{64}\Z")


class UnsafeExport(ValueError):
    """The release envelope cannot establish the narrow approved inventory."""


def require(cond: bool, reason: str) -> None:
    if not cond:
        raise UnsafeExport(reason)


def strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in output, "duplicate_json_keys")
        output[key] = value
    return output


def forbidden_constant(value: str) -> Any:
    raise UnsafeExport("nonfinite_json_number")


def safe_read(path: Path, *, max_bytes: int = MAX_FILE_BYTES) -> bytes:
    """No-follow, regular, bounded, stable descriptor read; no source echo."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_NONBLOCK", 0))
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= max_bytes,
                "nonregular_or_oversized_file")
        parts = []
        total = 0
        while True:
            chunk = os.read(fd, min(1024 * 1024, max_bytes + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            require(total <= max_bytes, "oversized_file")
            parts.append(chunk)
        after = os.fstat(fd)
        require(total == before.st_size and
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                 before.st_ctime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                 after.st_ctime_ns), "source_changed_during_read")
        return b"".join(parts)
    finally:
        os.close(fd)


def load_json(path: Path) -> dict[str, Any]:
    raw = safe_read(path, max_bytes=MAX_SUMMARY_BYTES)
    try:
        obj = json.loads(raw, object_pairs_hook=strict_pairs,
                         parse_constant=forbidden_constant)
    except (ValueError, RecursionError, UnicodeDecodeError, OverflowError) as exc:
        raise UnsafeExport("invalid_summary_json") from exc
    require(type(obj) is dict, "summary_object_required")
    return obj


def nonnegative_int(value: Any) -> int:
    require(type(value) is int and 0 <= value <= (1 << 53) - 1,
            "invalid_count")
    return value


def rate(value: Any) -> float:
    require(type(value) in (float, int) and math.isfinite(value) and
            0.0 <= value <= 1.0, "invalid_rate")
    return float(value)


def metric(value: Any) -> dict[str, float]:
    require(type(value) is dict and "brier" in value and "accuracy" in value,
            "missing_metric")
    return {"accuracy": rate(value["accuracy"]), "brier": rate(value["brier"])}


def extract_summary(value: dict[str, Any], *, hard: bool) -> list[dict[str, Any]]:
    """Construct safe scalar records; never copy user-supplied nested data."""
    expected_schema = ("hepta.cell-meta-hard-trained-physcpu-descriptive.v1"
                       if hard else "hepta.cell-meta-granite-descriptive-only.v1")
    require(value.get("schema") == expected_schema and
            value.get("production_admission") == "BLOCKED" and
            value.get("authority_posture") == "DENY_ALL",
            "incorrect_non_authority_summary")
    if hard:
        require(value.get("retrospective_public_test_not_future") is True and
                value.get("ood_true_tested") is False and
                value.get("matched_total_compute") is False and
                value.get("independent_NDU_verified") is False and
                value.get("original_model_origin_independently_signed") is False,
                "false_hard_model_or_future_claim")
    else:
        require(value.get("registered_public_model") == MODEL_NAME and
                value.get("future_window_prospective") is False and
                value.get("real_ood_verified") is False and
                value.get("total_compute_matched") is False and
                value.get("ndu_selection_authorized") is False and
                value.get("independent_model_origin_authenticated") is False,
                "false_soft_model_or_future_claim")
    arms = value.get("arms")
    require(type(arms) is list and len(arms) == len(SEEDS) * len(ARMS),
            "incomplete_arm_inventory")
    seen: set[tuple[int, str]] = set()
    output = []
    for arm in arms:
        require(type(arm) is dict and type(arm.get("seed")) is int and
                arm["seed"] in SEEDS and type(arm.get("arm")) is str and
                arm["arm"] in ARMS and
                type(arm.get("split_proposed")) is bool,
                "wrong_seed_or_arm")
        key = (arm["seed"], arm["arm"])
        require(key not in seen, "duplicate_seed_arm")
        seen.add(key)
        record = {"seed": key[0], "arm": key[1],
                  "split_proposed": arm["split_proposed"],
                  "test_1": metric(arm.get("retrospective_test_1")),
                  "test_2": metric(arm.get("retrospective_test_2"))}
        if hard:
            for name in ("train_head_rows", "eval_head_rows",
                         "diagnostic_head_rows", "train_router_rows",
                         "sampled_routes"):
                record[name] = nonnegative_int(arm.get(name))
        else:
            record["head_forward_rows"] = nonnegative_int(
                arm.get("head_forward_rows"))
        output.append(record)
    require(seen == {(s, a) for s in SEEDS for a in ARMS},
            "missing_seed_arm")
    return sorted(output, key=lambda v: (v["seed"], ARMS.index(v["arm"])))


def extract_isolated_os(value: dict[str, Any]) -> dict[str, Any]:
    """Whitelist five OS medians; no raw process traces or child payloads."""
    require(value.get("schema") == "hepta.cell-meta-isolated-kernel-resource-joined.v1"
            and value.get("authority_posture") == "DENY_ALL"
            and value.get("production_admission") == "BLOCKED"
            and value.get("exact_15_isolated_processes") == 15
            and type(value.get("exact_15_isolated_processes")) is int
            and value.get("original_source_row_count_not_tripled") == 224
            and type(value.get("original_source_row_count_not_tripled")) is int
            and value.get("resource_samples_are_three_correlated_seeds") is True
            and value.get("includes_python_import_and_replay_cost") is True
            and value.get("resource_or_model_winner_certified") is False
            and value.get("original_host_or_model_signatures_authenticated") is False
            and value.get("causal_reuse_or_total_compute_parity_proved") is False
            and value.get("independent_future_ndu_outcomes_observed") is False
            and value.get("energy_or_gpu_observed") is False
            and value.get("real_target_device_qualified") is False,
            "invalid_isolated_os_evidence")
    cpu = value.get("median_kernel_cpu_seconds_by_arm")
    rss = value.get("median_peak_rss_bytes_by_arm")
    require(type(cpu) is dict and type(rss) is dict and
            set(cpu) == set(OS_ARMS) and set(rss) == set(OS_ARMS),
            "incomplete_isolated_os_mediana")
    result = {}
    for arm in OS_ARMS:
        seconds = cpu[arm]
        require(type(seconds) in (int, float) and math.isfinite(seconds)
                and 0 < seconds <= 3600, "invalid_kernel_cpu")
        peak = rss[arm]
        require(type(peak) is int and 0 < peak <= (1 << 44),
                "invalid_peak_rss")
        result[arm] = {"cpu_seconds_including_import_and_replay": float(seconds),
                       "peak_process_rss_bytes": peak}
    return {"exact_15_os_processes_declared": 15,
            "cpu_and_rss_are_untrusted_same_class_samples": True,
            "cost_includes_python_import_and_numeric_replay": True,
            "by_arm": result}



def extract_fivearm(value: dict[str, Any], seed: int) -> tuple[str, list[dict[str, Any]]]:
    """Sanitize the crucial fifth frozen policy; omit all source-case payloads."""
    require(value.get("schema") == "hepta.cell-meta-five-arm-retrospective.v1"
            and type(value.get("seed")) is int and value.get("seed") == seed
            and value.get("source_kind") == "external_unverified"
            and value.get("source_rule") == "external"
            and value.get("retrospective_not_prospective") is True
            and value.get("same_source_calibration_not_ood") is True
            and value.get("research_only_no_independent_external_outcomes") is True
            and value.get("single_common_frozen_stage1_parent") is True
            and value.get("training_budget_unequal_across_five_arms") is True
            and value.get("complete_lifecycle_compute_matched") is False
            and value.get("statistical_winner_certified") is False
            and value.get("ndu_selection_authorized") is False
            and value.get("original_worker_model_origin_signed") is False
            and value.get("physical_cell_split_permitted") is False
            and value.get("production_admission") == "BLOCKED"
            and value.get("authority_posture") == "DENY_ALL",
            "false_fivearm_future_or_authority_claim")
    stem = value.get("shared_stem_sha256")
    require(type(stem) is str and HEX64.fullmatch(stem) is not None,
            "invalid_fivearm_encoder_identity")
    arms = value.get("arms")
    require(type(arms) is list and len(arms) == len(OS_ARMS) and
            [x.get("arm") for x in arms if type(x) is dict] == list(OS_ARMS),
            "wrong_fivearm_inventory")
    output = []
    for arm, name in zip(arms, OS_ARMS, strict=True):
        require(type(arm.get("split_proposed")) is bool,
                "invalid_fivearm_split_decision")
        scores = arm.get("retrospective_scores")
        require(type(scores) is dict and
                {"future_1", "future_2"} <= set(scores),
                "missing_fivearm_outcomes")
        costs = arm.get("cost_observation")
        require(type(costs) is dict, "missing_fivearm_costs")
        work = {key: nonnegative_int(costs.get(key)) for key in (
            "additional_stage2_training_head_rows", "additional_stage2_optimizer_updates",
            "evaluated_head_rows", "train_router_rows",
            "diagnostic_head_rows_in_existing_arm")}
        if name == OS_ARMS[0]:
            require(work["additional_stage2_training_head_rows"] ==
                    work["additional_stage2_optimizer_updates"] ==
                    work["train_router_rows"] == 0, "frozen_policy_not_frozen")
        output.append({"seed": seed, "arm": name,
                       "split_proposed": arm["split_proposed"],
                       "test_1": metric(scores["future_1"]),
                       "test_2": metric(scores["future_2"]),
                       "observed_head_router_work": work})
    return stem, output


def produce(root: Path) -> dict[str, Any]:
    """Return a BLOCKED receipt on every invalid or incomplete raw inventory."""
    result: dict[str, Any] = {
        "schema": SCHEMA, "status": "BLOCKED", "reason_codes": [],
        "authority_posture": "DENY_ALL", "production_admission": "BLOCKED",
        "pretrained_origin_independently_authenticated": False,
        "prospective_future_windows_verified": False,
        "ood_verified": False, "matched_lifecycle_compute": False,
        "independent_ndu_selection_authorized": False,
        "host_custody_authenticated": False,
        "descriptive_only": True,
        "expected_source_cases": 224,
        "training_seeds_are_not_independent_datasets": True,
        "raw_payloads_published": False,
        "files": [], "missing": [], "aggregate": {},
    }
    reasons = result["reason_codes"]
    if not root.is_dir() or root.is_symlink():
        reasons.append("missing_or_unsafe_evidence_directory")
        return result
    names = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                names.append(entry.name)
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    reasons.append("nonregular_or_symlink_entry")
    except OSError:
        reasons.append("unreadable_evidence_directory")
        return result
    if len(names) > MAX_FILES:
        reasons.append("excessive_file_inventory")
        return result
    if set(names) - EXPECTED:
        reasons.append("unregistered_evidence_filename")
    result["missing"] = sorted(EXPECTED - set(names))
    if result["missing"]:
        reasons.append("incomplete_evidence_inventory")
    total = 0
    for name in sorted(set(names) & EXPECTED):
        try:
            raw = safe_read(root / name)
        except (OSError, UnsafeExport):
            reasons.append("unreadable_or_changed_evidence")
            continue
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            reasons.append("total_evidence_bytes_exceeded")
            break
        result["files"].append({"name": name, "bytes": len(raw),
                                "sha256": hashlib.sha256(raw).hexdigest()})
    # Never materialize original JSONL/FP32/features/panel in the export.
    if reasons:
        result["reason_codes"] = sorted(set(reasons))
        return result
    try:
        # Recheck actual pinned inputs at the point of evidence export, not
        # just their separately produced digest-claim sidecars. A changed
        # payload with an unchanged sidecar must never be marked complete.
        for name, expected_sha in SOURCE_PARQUET_SHA.items():
            actual_sha = hashlib.sha256(safe_read(root / name)).hexdigest()
            require(actual_sha == expected_sha, "pinned_source_bytes_mismatch")
        actual_panel_sha = hashlib.sha256(
            safe_read(root / "source-panel.json")).hexdigest()
        require(actual_panel_sha == SOURCE_SHA, "public_panel_bytes_mismatch")
        source_sha = safe_read(root / "original-source-sha256.txt", max_bytes=128)
        require(source_sha == (SOURCE_SHA + "\n").encode("ascii"),
                "original_source_digest_drift")
        model_inventory_sha = hashlib.sha256(
            safe_read(root / "model-files.json")).hexdigest()
        model_pointer = safe_read(root / "model-files-source-hash.txt", max_bytes=128)
        require(model_pointer == (model_inventory_sha + "\n").encode("ascii"),
                "model_inventory_bytes_mismatch")
        soft = load_json(root / "descriptive-retrospective-summary.json")
        hard = load_json(root / "hardtop1-descriptive-retrospective-summary.json")
        kernel = load_json(root / "os-meter-joined.json")
        fivearm = []
        common_stem = None
        for seed in SEEDS:
            stem, rows = extract_fivearm(
                load_json(root / f"{seed}-fivearm-report.json"), seed)
            if common_stem is None:
                common_stem = stem
            else:
                require(stem == common_stem, "inconsistent_fivearm_shared_encoder")
            fivearm.extend(rows)
        result["aggregate"] = {
            "original_public_panel_sha256": SOURCE_SHA,
            "registered_encoder": MODEL_NAME,
            "four_arm_soft_research": extract_summary(soft, hard=False),
            "four_arm_hard_top1_research": extract_summary(hard, hard=True),
            "five_arm_retrospective_research": fivearm,
            "five_arm_os_medians": extract_isolated_os(kernel),
        }
    except (UnsafeExport, OSError, UnicodeError, RecursionError) as exc:
        # Only constant reason labels; never leak malformed raw content.
        result["reason_codes"] = ["invalid_source_or_aggregate"]
        result["aggregate"] = {}
        return result
    result["status"] = "COMPLETE_DESCRIPTIVE_ONLY"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        parent = args.out.parent
        require(parent.is_dir() and not parent.is_symlink() and
                not args.out.exists() and not args.out.is_symlink(),
                "unsafe_export_destination")
        report = produce(args.root)
        data = json.dumps(report, ensure_ascii=True, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
        require(len(data) <= MAX_REPORT_BYTES, "unbounded_redacted_receipt")
        fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        print(json.dumps({"safe_receipt": str(args.out),
                          "status": report["status"],
                          "authority_posture": "DENY_ALL"}, sort_keys=True))
        return 0 if report["status"] == "COMPLETE_DESCRIPTIVE_ONLY" else 2
    except (OSError, UnsafeExport, RecursionError) as exc:
        print("GRANITE REDACTED EXPORT DENIED", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
