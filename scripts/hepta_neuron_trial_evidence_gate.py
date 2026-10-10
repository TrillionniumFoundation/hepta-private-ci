#!/usr/bin/env python3
"""Verify externally signed *claims* for Neuron trials; never authorize serving.

Each role must have a separately pinned Ed25519 key/principal supplied by an
operator-owned trust source, not by the training process. Cryptographic validity
proves origin and byte integrity, NOT target-host truth, evaluator independence,
physical rollback, two elapsed future windows, or NDU's causal validity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from hepta_neuron_model_trials import ARMS, SCHEMA, is_sha, read_json, require, sha_file, write_new

EVIDENCE_SCHEMA = "hepta.neuron.trial-external-evidence.v1"
ROLES = ("shadow", "evaluator", "ndu", "recovery")


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def verify_signature(envelope, trusted):
    """Validate one issuer-bound signature; there is deliberately no signing API."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    role = envelope.get("role")
    require(envelope.get("schema") == EVIDENCE_SCHEMA and role in ROLES,
            "invalid external evidence schema/role")
    require(envelope.get("key_id") == trusted[role]["key_id"], "signer not pinned to role")
    signature = envelope.get("signature_ed25519_hex")
    require(isinstance(signature, str) and len(signature) == 128, "invalid signature length")
    unsigned = {k: v for k, v in envelope.items() if k != "signature_ed25519_hex"}
    require(set(unsigned) == {"schema", "role", "key_id", "body"}, "unsigned/malformed fields")
    require(isinstance(envelope.get("body"), dict), "evidence body missing")
    try:
        raw_sig = bytes.fromhex(signature)
        Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(trusted[role]["public_key_ed25519_hex"])
        ).verify(raw_sig, _canonical(unsigned))
    except (InvalidSignature, ValueError) as error:
        raise ValueError("independent role signature verification failed") from error
    return envelope["body"]


def verify_trust(trust):
    require(trust.get("schema") == EVIDENCE_SCHEMA and trust.get("version") == 1,
            "unrecognized independent trust registry")
    roles = trust.get("roles")
    require(isinstance(roles, dict) and set(roles) == set(ROLES),
            "all four external owners must be trusted")
    principals = set()
    keys = set()
    key_ids = set()
    for role in ROLES:
        key = roles[role]
        require(isinstance(key, dict) and set(key) ==
                {"key_id", "public_key_ed25519_hex", "principal"}, "invalid trust fields")
        require(is_sha(key["public_key_ed25519_hex"]) and
                isinstance(key["key_id"], str) and key["key_id"] and
                isinstance(key["principal"], str) and key["principal"], "invalid pinned public key")
        require(key["principal"] not in principals and
                key["public_key_ed25519_hex"] not in keys and
                key["key_id"] not in key_ids, "role owner must be independently keyed and named")
        principals.add(key["principal"])
        keys.add(key["public_key_ed25519_hex"])
        key_ids.add(key["key_id"])
    return roles


def verify_report(manifest_path, comparison_path, trusted_sha, trust_path, envelopes):
    """Verify signed issuer claims tied to exact manifest/comparison/receipt bytes.

    False NDU gain is a legitimate failed experiment and not invalid evidence.
    Regardless of gains, this function grants zero authority. A real evaluator
    must independently replay source/labels and a host must attest physical steps.
    """
    require(is_sha(trusted_sha), "operator pinned trust file SHA missing")
    require(sha_file(trust_path) == trusted_sha, "trust file differs from operator pin")
    trust = verify_trust(read_json(trust_path))
    manifest = read_json(manifest_path)
    comparison = read_json(comparison_path)
    require(manifest.get("schema") == SCHEMA and manifest.get("family") in ARMS,
            "invalid trial manifest")
    family = manifest["family"]
    require(comparison.get("schema") == SCHEMA and comparison.get("family") == family and
            comparison.get("diagnostic_comparison") is True and
            comparison.get("promotion_authorized") is False and
            comparison.get("ndu_selection_authorized") is False and
            comparison.get("production_evidence_verified") is False,
            "comparison claims an inappropriate authority")
    baseline = comparison.get("baseline_sha256")
    require(is_sha(baseline), "baseline was not frozen")
    receipt_hashes = comparison.get("receipt_sha256")
    require(isinstance(receipt_hashes, dict) and set(receipt_hashes) == set(ARMS[family]) and
            all(is_sha(v) for v in receipt_hashes.values()), "full receipt set not bound")
    require(isinstance(envelopes, dict) and set(envelopes) == set(ROLES),
            "external evidence incomplete")
    results = {}
    for role in ROLES:
        obj = read_json(envelopes[role])
        body = verify_signature(obj, trust)
        for name, expected in (
                ("manifest_sha256", sha_file(manifest_path)),
                ("comparison_sha256", sha_file(comparison_path)),
                ("baseline_sha256", baseline),
                ("source_sha", manifest["source_sha"]),
                ("host_profile_digest", manifest["host_profile_digest"]),
                ("sealed_dataset_sha256", manifest["dataset_sha256"])):
            require(body.get(name) == expected, f"{role} binding mismatch: {name}")
        require(body.get("family") == family and type(body.get("signed_at_ms")) is int and
                body["signed_at_ms"] > 0 and
                body.get("principal") == trust[role]["principal"],
                f"invalid {role} principal or timestamp")
        results[role] = body

    shadow = results["shadow"]
    require(shadow.get("run_receipt_sha256") == receipt_hashes and
            shadow.get("shadow_only") is True and shadow.get("effect_count") == 0 and
            is_sha(shadow.get("shadow_execution_log_sha256")),
            "shadow host observations insufficient")
    evaluator = results["evaluator"]
    require(evaluator.get("holdout_sealed") is True and
            evaluator.get("windows_independently_scored") == ["holdout", "future_1", "future_2"] and
            is_sha(evaluator.get("independent_scoring_code_sha256")) and
            is_sha(evaluator.get("sealed_metrics_sha256")),
            "independent evaluator claims incomplete")
    recovery = results["recovery"]
    require(is_sha(recovery.get("physical_replay_log_sha256")) and
            all(recovery.get(name) is True for name in (
                "journal_cas_recovered", "generation_fence_passed", "old_route_rejected",
                "rollback_passed", "tombstone_no_resurrection_passed")),
            "rollback/replay claims incomplete")
    ndu = results["ndu"]
    require(ndu.get("baseline_receipt_sha256") == baseline and
            ndu.get("selected_no_change_as_baseline") is True and
            ndu.get("resources_measured") is True and ndu.get("retention_measured") is True and
            ndu.get("negative_transfer_measured") is True and
            is_sha(ndu.get("underlying_ndu_receipt_sha256")), "NDU evidence incomplete")
    gains = ndu.get("net_gain_q24_by_window")
    require(isinstance(gains, dict) and set(gains) == set(ARMS[family][1:]),
            "NDU missing candidate arms")
    for arm, windows in gains.items():
        require(isinstance(windows, dict) and set(windows) == {"future_1", "future_2"} and
                all(type(v) is int and -(8 << 24) <= v <= (8 << 24) for v in windows.values()),
                f"invalid NDU windows for {arm}")
    passing = {arm: all(delta > 0 for delta in windows.values()) for arm, windows in gains.items()}
    return {
        "schema": EVIDENCE_SCHEMA,
        "diagnostic_attestation_check": True,
        "manifest_sha256": sha_file(manifest_path),
        "comparison_sha256": sha_file(comparison_path),
        "trust_sha256": trusted_sha,
        "signed_owner_claims_verified": True,
        "positive_signed_ndu_claims": passing,
        "eligible_for_independent_operator_review": any(passing.values()),
        "physical_truth_independently_observed_by_this_script": False,
        "production_evidence_verified": False,
        "ndu_selection_authorized": False,
        "promotion_authorized": False,
        "reason": "Signature verification is not physical truth; an operator must independently verify source, seals, host, NDU and recovery.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--trust", type=Path, required=True)
    parser.add_argument("--trust-sha256", required=True)
    for role in ROLES:
        parser.add_argument(f"--{role}", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify_report(args.manifest, args.comparison, args.trust_sha256,
                               args.trust, {role: getattr(args, role) for role in ROLES})
        write_new(args.output, report)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f"blocked: {error}\n")


if __name__ == "__main__":
    main()
