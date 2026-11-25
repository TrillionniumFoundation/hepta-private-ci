#!/usr/bin/env python3
"""Verify signed model upgrade/fault/rollback receipts; never executes effects."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from bakeoff import EvidenceError, file_hash, load_json, load_jsonl, require

STAGES = (
    ("artifact_cas", "artifact_owner"),
    ("supervisor_fence", "supervisor"),
    ("route_cutover", "router"),
    ("old_generation_rejected", "observer"),
    ("forced_crash", "observer"),
    ("durable_recovery", "supervisor"),
    ("rollback_artifact_cas", "artifact_owner"),
    ("rollback_fence", "supervisor"),
    ("rollback_cutover", "router"),
    ("stale_candidate_rejected", "observer"),
)
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def canonical(obj: dict[str, Any]) -> bytes:
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        allow_nan=False,
    ).encode()


def verify_signature(payload: dict[str, Any], signature: str, public_hex: str) -> None:
    require(isinstance(signature, str) and re.fullmatch(r"[0-9a-f]{128}", signature) is not None,
            "invalid Ed25519 signature encoding")
    require(isinstance(public_hex, str) and HEX64.fullmatch(public_hex) is not None,
            "invalid Ed25519 public key")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise EvidenceError("cryptography required; signature checks cannot be bypassed") from exc
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex)).verify(
            bytes.fromhex(signature), canonical(payload),
        )
    except (InvalidSignature, ValueError) as exc:
        raise EvidenceError("independent receipt signature invalid") from exc


def verify_lifecycle(events: list[dict[str, Any]], keys: dict[str, Any]) -> dict[str, Any]:
    require(len(events) == len(STAGES), "missing/reordered/extra lifecycle stages")
    require(set(keys) == {role for _, role in STAGES}, "trusted key role set drift")
    require(len(set(keys.values())) == len(keys), "independent issuers cannot share a public key")
    head = "0" * 64
    baseline = candidate = commit = None
    base_generation = None
    for i, (stage, role) in enumerate(STAGES):
        item = events[i]
        require(set(item) == {"payload", "signature"}, f"{stage}: malformed envelope")
        payload = item["payload"]
        require(isinstance(payload, dict), f"{stage}: missing payload")
        require(payload.get("stage") == stage and payload.get("issuer_role") == role,
                f"{stage}: stage/role drift")
        require(payload.get("sequence") == i + 1
                and payload.get("previous_receipt_sha256") == head,
                f"{stage}: hash chain broken")
        require(type(payload.get("observed")) is bool and payload["observed"],
                f"{stage}: no observed operation result")
        require(isinstance(payload.get("operation_id"), str) and payload["operation_id"],
                f"{stage}: missing operation identity")
        evidence = payload.get("evidence_digest")
        require(isinstance(evidence, str) and HEX64.fullmatch(evidence) is not None
                and evidence != "0" * 64, f"{stage}: no evidence digest")
        source = payload.get("source_commit")
        require(isinstance(source, str) and HEX40.fullmatch(source) is not None,
                f"{stage}: no source commit")
        generation = payload.get("generation")
        require(type(generation) is int and generation > 0, f"{stage}: invalid generation")
        model = payload.get("model_digest")
        require(isinstance(model, str) and HEX64.fullmatch(model) is not None,
                f"{stage}: invalid model digest")
        verify_signature(payload, item["signature"], keys[role])
        if i == 0:
            base_generation, candidate, commit = generation, model, source
            baseline = payload.get("baseline_digest")
            require(isinstance(baseline, str) and HEX64.fullmatch(baseline) is not None
                    and baseline != candidate, "baseline/candidate not bound")
        else:
            require(source == commit, f"{stage}: source drift")
        expected_gen = base_generation if i < 6 else base_generation + 1
        if stage == "old_generation_rejected":
            expected_gen = base_generation - 1
        if stage == "stale_candidate_rejected":
            expected_gen = base_generation
        require(generation == expected_gen, f"{stage}: incorrect generation")
        expected_model = baseline if i >= 6 else candidate
        if stage == "old_generation_rejected":
            expected_model = baseline
        if stage == "stale_candidate_rejected":
            expected_model = candidate
        require(model == expected_model, f"{stage}: incorrect model binding")
        head = hashlib.sha256(canonical(item)).hexdigest()
    return {
        "schema": "hepta.neuron.model-lifecycle.verification.v1",
        "source_commit": commit,
        "candidate_generation": base_generation,
        "rollback_generation": base_generation + 1,
        "receipt_chain_sha256": head,
        "signed_sequence_valid": True,
        "claim_ceiling": "signed_receipt_consistency_not_physical_execution_proof",
        "promotion_authorized": False, "independent_acceptance": False,
        "all_blockers_closed": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--trusted-keys", type=Path, required=True)
    p.add_argument("--trusted-keys-sha256", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    try:
        require(HEX64.fullmatch(a.trusted_keys_sha256) is not None, "trusted key digest not pinned")
        require(file_hash(a.trusted_keys) == a.trusted_keys_sha256, "trusted keys changed")
        report = verify_lifecycle(load_jsonl(a.events), load_json(a.trusted_keys))
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(f"Signed receipt structure verified, no authority granted: {a.output}")
        return 0
    except (EvidenceError, OSError, ValueError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
