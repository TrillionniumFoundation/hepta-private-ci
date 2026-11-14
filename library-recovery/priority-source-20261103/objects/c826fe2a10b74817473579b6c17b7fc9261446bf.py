#!/usr/bin/env python3
"""Fail-closed NDU-MGP P0-P4 evidence gate. Stdlib only; no CI status fabrication."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

PHASES = ("P0", "P1", "P2", "P3", "P4")
REQUIRED = {
    "P0": ("oracle_bvp_qp_agreement", "nonlinear_error_bounds", "encoder_flow_decoder_replay", "exact_head_ci"),
    "P1": ("matched_six_arm_comparison", "independent_heldout", "semantic_quality", "cvar", "ambiguity", "measured_total_cost", "strong_baseline_superiority"),
    "P2": ("frozen_dllm_backbone", "shared_vocab_logits", "dynamic_unmask", "stopping_policy", "matched_tokens_and_compute", "heldout_quality"),
    "P3": ("natural_image_speech_outputs", "cross_modal_alignment", "independent_factuality", "streaming_safety", "measured_latency", "heldout_quality"),
    "P4": ("factorial_2x2_training_inference", "same_capacity_free_controller", "out_of_time_replication", "external_utility_fixed", "no_protected_task_regression", "security_authority_review"),
}

def qualify(data: dict) -> tuple[bool, list[str]]:
    problems = []
    if data.get("schema_version") != 1:
        problems.append("schema_version: expected 1")
    if set(data.get("phases", {})) != set(PHASES):
        problems.append("phases: exactly P0..P4 required")
    for phase in PHASES:
        records = data.get("phases", {}).get(phase, {})
        if not isinstance(records, dict) or set(records) != set(REQUIRED[phase]):
            problems.append(f"{phase}: evidence keys missing or extra")
            continue
        for criterion in REQUIRED[phase]:
            item = records[criterion]
            if not isinstance(item, dict):
                problems.append(f"{phase}.{criterion}: record required")
                continue
            # A URL, PR, queued job, self-score, local smoke, or a digest alone is never PASS.
            if item.get("status") != "PASS":
                problems.append(f"{phase}.{criterion}: {item.get('status', 'MISSING')}")
                continue
            if item.get("attestation") != "independent-verified":
                problems.append(f"{phase}.{criterion}: independent attestation required")
            if not isinstance(item.get("evidence_url"), str) or not item["evidence_url"].startswith("https://"):
                problems.append(f"{phase}.{criterion}: https evidence URL required")
            if not isinstance(item.get("source_sha"), str) or len(item["source_sha"]) != 40 or not all(x in "0123456789abcdef" for x in item["source_sha"]):
                problems.append(f"{phase}.{criterion}: exact lowercase 40-hex SHA required")
            if item.get("study_status") not in ("pre_registered_holdout", "prospective_replication", "exact_head_ci"):
                problems.append(f"{phase}.{criterion}: qualified study status required")
    if not problems:
        problems.append("UNVERIFIED_TRUST: shape-only metadata cannot establish external acceptance")
    return False, problems

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", type=Path)
    args = ap.parse_args()
    try:
        content = json.loads(args.manifest.read_text(encoding="utf-8"))
        ok, problems = qualify(content)
    except (OSError, ValueError, TypeError) as exc:
        print(f"HOLD_NO_GO: invalid manifest: {exc}")
        return 2
    print("QUALIFIED" if ok else "HOLD_NO_GO")
    for problem in problems:
        print("BLOCKER " + problem)
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
