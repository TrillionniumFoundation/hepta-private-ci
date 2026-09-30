#!/usr/bin/env python3
"""Build and verify signed AuthBus production-acceptance payloads."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs/modules/auth.authbus/PRODUCTION_ACCEPTANCE.json"
HEX = set("0123456789abcdef")


def load_json(path: Path) -> dict[str, Any]:
    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"{path}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def bounded_string(value: Any, label: str, limit: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"{label}: expected a non-empty bounded string")
    return value


def sha256_string(value: Any, label: str) -> str:
    value = bounded_string(value, label, 64)
    if len(value) != 64 or any(character not in HEX for character in value):
        raise ValueError(f"{label}: expected lowercase SHA-256")
    return value


def exact_int(value: Any, label: str, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label}: expected an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label}: expected an integer <= {maximum}")
    return value


def require_candidate(candidate_sha: str) -> None:
    if len(candidate_sha) != 40 or any(character not in HEX for character in candidate_sha):
        raise ValueError("candidate SHA must be a lowercase 40-character SHA-1")


def validate_exact_receipt(path: Path, candidate_sha: str, kind: str) -> dict[str, Any]:
    value = load_json(path)
    if value.get("schema") != "hepta.authbus.exact-head-evidence.v2":
        raise ValueError(f"{path}: exact evidence schema mismatch")
    candidate = value.get("candidate")
    if not isinstance(candidate, dict) or candidate.get("kind") != kind:
        raise ValueError(f"{path}: candidate kind mismatch")
    if value.get("qualificationComplete") is not True:
        raise ValueError(f"{path}: qualification is not complete")
    if value.get("activation") is not False or value.get("release") is not False:
        raise ValueError(f"{path}: source evidence improperly claims activation")
    if kind == "exact_head":
        if candidate.get("commit") != candidate_sha:
            raise ValueError(f"{path}: exact-head candidate drift")
    else:
        parents = candidate.get("parents")
        if not isinstance(parents, list) or len(parents) != 2 or parents[1] != candidate_sha:
            raise ValueError(f"{path}: synthetic merge does not name the candidate as second parent")
    bounded_string(candidate.get("tree"), f"{path}: tree", 64)
    return value


def validate_target(path: Path, candidate_sha: str) -> tuple[dict[str, Any], str]:
    value = load_json(path)
    if value.get("schema") != "hepta.authbus.target-host-qualification.v2":
        raise ValueError("target-host manifest schema mismatch")
    if value.get("candidateSha") != candidate_sha:
        raise ValueError("target-host candidate drift")
    target_identity = bounded_string(value.get("targetIdentity"), "targetIdentity")
    exact_int(value.get("scenarioCount"), "target scenarioCount", 11)
    if value.get("operatorActivation") is not False or value.get("release") is not False:
        raise ValueError("target-host evidence improperly claims activation")
    return value, target_identity


def validate_performance(
    path: Path,
    candidate_sha: str,
    target_identity: str,
) -> dict[str, Any]:
    value = load_json(path)
    if value.get("schema") != "hepta.authbus.performance-evidence.v1":
        raise ValueError("performance manifest schema mismatch")
    if value.get("candidateSha") != candidate_sha:
        raise ValueError("performance candidate drift")
    if value.get("targetIdentity") != target_identity:
        raise ValueError("performance target identity drift")
    exact_int(value.get("caseCount"), "performance caseCount", 16)
    if value.get("activation") is not False or value.get("release") is not False:
        raise ValueError("performance evidence improperly claims activation")
    return value


def validate_drill(
    path: Path,
    candidate_sha: str,
    target_identity: str,
    expected_drill: str,
) -> dict[str, Any]:
    value = load_json(path)
    if value.get("schema") != "hepta.authbus.external-drill.v1":
        raise ValueError(f"{path}: external drill schema mismatch")
    if value.get("drill") != expected_drill:
        raise ValueError(f"{path}: external drill substitution")
    if value.get("candidateSha") != candidate_sha:
        raise ValueError(f"{path}: candidate drift")
    if value.get("targetIdentity") != target_identity:
        raise ValueError(f"{path}: target identity drift")
    if value.get("passed") is not True:
        raise ValueError(f"{path}: drill did not pass")
    sha256_string(value.get("evidenceSha256"), f"{path}: evidenceSha256")
    bounded_string(value.get("providerIdentity"), f"{path}: providerIdentity")
    bounded_string(value.get("observedResult"), f"{path}: observedResult")
    bounded_string(value.get("startedAt"), f"{path}: startedAt", 128)
    bounded_string(value.get("completedAt"), f"{path}: completedAt", 128)
    return value


def validate_activation_plan(
    path: Path,
    candidate_sha: str,
    target_identity: str,
) -> dict[str, Any]:
    value = load_json(path)
    if value.get("schema") != "hepta.authbus.activation-plan.v1":
        raise ValueError("activation plan schema mismatch")
    if value.get("candidateSha") != candidate_sha or value.get("targetIdentity") != target_identity:
        raise ValueError("activation plan identity drift")
    exact_int(value.get("canaryPercent"), "activation canaryPercent", 1, 10)
    exact_int(value.get("observationWindowMinutes"), "activation observationWindowMinutes", 30)
    sha256_string(value.get("sloPolicySha256"), "activation sloPolicySha256")
    bounded_string(value.get("alertRoute"), "activation alertRoute")
    bounded_string(value.get("promotionOwner"), "activation promotionOwner")
    bounded_string(value.get("rollbackOwner"), "activation rollbackOwner")
    if value.get("productionActivation") is not False:
        raise ValueError("activation plan must not claim production activation before acceptance")
    return value


def validate_rollback_plan(
    path: Path,
    candidate_sha: str,
    target_identity: str,
) -> dict[str, Any]:
    value = load_json(path)
    if value.get("schema") != "hepta.authbus.rollback-plan.v1":
        raise ValueError("rollback plan schema mismatch")
    if value.get("candidateSha") != candidate_sha or value.get("targetIdentity") != target_identity:
        raise ValueError("rollback plan identity drift")
    exact_int(value.get("rollbackWindowMinutes"), "rollback rollbackWindowMinutes", 30)
    sha256_string(value.get("commandsSha256"), "rollback commandsSha256")
    sha256_string(value.get("testReceiptSha256"), "rollback testReceiptSha256")
    bounded_string(value.get("restoredCheckpointPolicy"), "rollback restoredCheckpointPolicy")
    bounded_string(value.get("dataLossPolicy"), "rollback dataLossPolicy")
    if value.get("tested") is not True:
        raise ValueError("rollback plan has not been tested")
    return value


def verify_ed25519(public_key: Path, signature: Path, payload: bytes, label: str) -> None:
    if not public_key.is_file() or not signature.is_file():
        raise ValueError(f"{label}: public key or signature is missing")
    with tempfile.TemporaryDirectory(prefix="authbus-acceptance-") as directory:
        payload_path = Path(directory) / "payload.json"
        payload_path.write_bytes(payload)
        result = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                str(public_key),
                "-rawin",
                "-in",
                str(payload_path),
                "-sigfile",
                str(signature),
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ValueError(f"{label}: Ed25519 signature verification failed: {detail}")


def require_path(path: Path | None, label: str) -> Path:
    if path is None:
        raise ValueError(f"{label}: required for this phase")
    return path


def build_payloads(args: argparse.Namespace) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, str],
    str,
]:
    contract = load_json(CONTRACT_PATH)
    if contract.get("schema") != "hepta.authbus.production-acceptance-contract.v1":
        raise ValueError("production acceptance contract schema mismatch")
    exact = validate_exact_receipt(args.exact_receipt, args.candidate_sha, "exact_head")
    merge = validate_exact_receipt(args.merge_receipt, args.candidate_sha, "synthetic_merge")
    target, target_identity = validate_target(args.target_manifest, args.candidate_sha)
    performance = validate_performance(
        args.performance_manifest,
        args.candidate_sha,
        target_identity,
    )
    drills = {
        "kmsHsm": (args.kms_hsm, "kms_hsm_composition"),
        "keyRotationRevocation": (
            args.rotation,
            "key_rotation_revocation_recovery",
        ),
        "backupRestore": (args.backup_restore, "backup_restore"),
        "dualOwnerMount": (args.owner_mount, "dual_owner_and_mount"),
    }
    drill_values = {
        name: validate_drill(path, args.candidate_sha, target_identity, drill)
        for name, (path, drill) in drills.items()
    }
    validate_activation_plan(args.activation_plan, args.candidate_sha, target_identity)
    validate_rollback_plan(args.rollback_plan, args.candidate_sha, target_identity)

    evidence_digests = {
        "exactHead": sha256(args.exact_receipt),
        "syntheticMerge": sha256(args.merge_receipt),
        "targetHost": sha256(args.target_manifest),
        "performance": sha256(args.performance_manifest),
        "kmsHsm": sha256(args.kms_hsm),
        "keyRotationRevocation": sha256(args.rotation),
        "backupRestore": sha256(args.backup_restore),
        "dualOwnerMount": sha256(args.owner_mount),
        "activationPlan": sha256(args.activation_plan),
        "rollbackPlan": sha256(args.rollback_plan),
    }
    security_payload = {
        "schema": "hepta.authbus.security-acceptance-payload.v1",
        "candidateSha": args.candidate_sha,
        "candidateTree": exact["candidate"]["tree"],
        "syntheticMergeTree": merge["candidate"]["tree"],
        "targetIdentity": target_identity,
        "evidenceSha256": evidence_digests,
        "performanceCaseCount": performance["caseCount"],
        "targetScenarioCount": target["scenarioCount"],
        "externalDrills": {
            name: {
                "drill": value["drill"],
                "providerIdentity": value["providerIdentity"],
                "evidenceSha256": value["evidenceSha256"],
            }
            for name, value in sorted(drill_values.items())
        },
    }
    security_payload_sha = hashlib.sha256(canonical(security_payload)).hexdigest()
    operator_payload = {
        "schema": "hepta.authbus.operator-acceptance-payload.v1",
        "candidateSha": args.candidate_sha,
        "targetIdentity": target_identity,
        "securityPayloadSha256": security_payload_sha,
        "securitySignatureSha256": (
            sha256(args.security_signature) if args.security_signature is not None else None
        ),
        "activationPlanSha256": evidence_digests["activationPlan"],
        "rollbackPlanSha256": evidence_digests["rollbackPlan"],
        "decision": "approved_for_canary",
    }
    return security_payload, operator_payload, evidence_digests, target_identity


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase",
        required=True,
        choices=("security-payload", "operator-payload", "verify"),
    )
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--exact-receipt", required=True, type=Path)
    parser.add_argument("--merge-receipt", required=True, type=Path)
    parser.add_argument("--target-manifest", required=True, type=Path)
    parser.add_argument("--performance-manifest", required=True, type=Path)
    parser.add_argument("--kms-hsm", required=True, type=Path)
    parser.add_argument("--rotation", required=True, type=Path)
    parser.add_argument("--backup-restore", required=True, type=Path)
    parser.add_argument("--owner-mount", required=True, type=Path)
    parser.add_argument("--activation-plan", required=True, type=Path)
    parser.add_argument("--rollback-plan", required=True, type=Path)
    parser.add_argument("--security-reviewer-id")
    parser.add_argument("--operator-id")
    parser.add_argument("--security-public-key", type=Path)
    parser.add_argument("--operator-public-key", type=Path)
    parser.add_argument("--security-signature", type=Path)
    parser.add_argument("--operator-signature", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        require_candidate(args.candidate_sha)
        security_payload, operator_payload, evidence_digests, target_identity = (
            build_payloads(args)
        )
        if args.phase == "security-payload":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(canonical(security_payload))
            return

        security_key = require_path(args.security_public_key, "security public key")
        security_signature = require_path(
            args.security_signature,
            "security signature",
        )
        security_reviewer_id = bounded_string(
            args.security_reviewer_id,
            "security reviewer id",
            256,
        )
        verify_ed25519(
            security_key,
            security_signature,
            canonical(security_payload),
            "independent security review",
        )
        operator_payload["securitySignatureSha256"] = sha256(security_signature)
        if args.phase == "operator-payload":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(canonical(operator_payload))
            return

        operator_key = require_path(args.operator_public_key, "operator public key")
        operator_signature = require_path(args.operator_signature, "operator signature")
        operator_id = bounded_string(args.operator_id, "operator id", 256)
        if security_reviewer_id == operator_id:
            raise ValueError("security reviewer and activation operator must be distinct")
        verify_ed25519(
            operator_key,
            operator_signature,
            canonical(operator_payload),
            "operator activation approval",
        )
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise SystemExit(f"production acceptance validation failed: {error}") from error

    output = {
        "schema": "hepta.authbus.production-acceptance.v1",
        "candidateSha": args.candidate_sha,
        "targetIdentity": target_identity,
        "contractSha256": sha256(CONTRACT_PATH),
        "evidenceSha256": evidence_digests,
        "securityReview": {
            "reviewerId": security_reviewer_id,
            "payloadSha256": hashlib.sha256(canonical(security_payload)).hexdigest(),
            "signatureSha256": sha256(security_signature),
            "verified": True,
        },
        "operatorApproval": {
            "operatorId": operator_id,
            "payloadSha256": hashlib.sha256(canonical(operator_payload)).hexdigest(),
            "signatureSha256": sha256(operator_signature),
            "verified": True,
        },
        "activationDecision": "approved_for_canary",
        "productionActivated": False,
        "canaryPromotion": False,
        "release": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
