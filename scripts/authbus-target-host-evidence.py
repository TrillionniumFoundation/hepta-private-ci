#!/usr/bin/env python3
"""Validate raw AuthBus target-host fault receipts and bind them to one candidate."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "docs/modules/auth.authbus/CRASH_CONSISTENCY_MATRIX.json"
SCENARIOS = {
    "enospc": "disk-full",
    "power-loss": "checkpoint-directory-fsync-failure",
    "permission-loss": "owner-lease-missing-or-replaced",
    "restore-old-snapshot": "restore-old-database-with-new-checkpoint",
    "owner-collision": "paused-owner-second-owner",
    "wal-corruption": "wal-corruption",
    "backup-race": "backup-concurrent-with-mutation",
    "trust-generation-mismatch": "trust-material-generation-mismatch",
    "fsync-failure": "checkpoint-file-fsync-failure",
    "rename-failure": "checkpoint-rename-failure",
    "checkpoint-corruption": "checkpoint-content-corruption",
}
SCHEMA = "hepta.authbus.target-host-scenario.v2"


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
        raise ValueError(f"{path}: receipt must be an object")
    return value


def literal(value: Any, kind: type, label: str) -> Any:
    if type(value) is not kind:
        raise ValueError(f"{label}: expected {kind.__name__}")
    return value


def nonempty(value: Any, label: str) -> str:
    value = literal(value, str, label)
    if not value or len(value) > 4096:
        raise ValueError(f"{label}: empty or oversized")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def matrix_rows() -> dict[str, dict[str, Any]]:
    matrix = load_json(MATRIX_PATH)
    if matrix.get("schema") != "hepta.authbus.crash-consistency-matrix.v2":
        raise ValueError("crash consistency matrix schema mismatch")
    scenarios = matrix.get("scenarios")
    if not isinstance(scenarios, list):
        raise ValueError("crash consistency matrix has no scenarios")
    rows = {
        str(row["id"]): row
        for row in scenarios
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    missing = sorted(set(SCENARIOS.values()) - set(rows))
    if missing:
        raise ValueError(f"target scenarios missing from crash matrix: {missing}")
    return rows


def validate_receipt(
    path: Path,
    expected_scenario: str,
    matrix_id: str,
    matrix: dict[str, dict[str, Any]],
    candidate_sha: str,
    target_profile: str,
) -> dict[str, Any]:
    row = load_json(path)
    if row.get("schema") != SCHEMA:
        raise ValueError(f"{path}: wrong schema")
    if row.get("scenario") != expected_scenario:
        raise ValueError(f"{path}: scenario substitution")
    if row.get("matrixScenarioId") != matrix_id:
        raise ValueError(f"{path}: crash-matrix scenario substitution")
    if row.get("candidateSha") != candidate_sha:
        raise ValueError(f"{path}: candidate SHA drift")
    if row.get("targetProfile") != target_profile:
        raise ValueError(f"{path}: target profile drift")
    if row.get("passed") is not True:
        raise ValueError(f"{path}: scenario did not pass")

    target_identity = nonempty(row.get("targetIdentity"), f"{path}: targetIdentity")
    started_boot = nonempty(row.get("startedBootId"), f"{path}: startedBootId")
    completed_boot = nonempty(row.get("completedBootId"), f"{path}: completedBootId")
    nonempty(row.get("kernelRelease"), f"{path}: kernelRelease")
    nonempty(row.get("filesystem"), f"{path}: filesystem")
    nonempty(row.get("mountIdentity"), f"{path}: mountIdentity")
    nonempty(row.get("faultInjectionId"), f"{path}: faultInjectionId")
    nonempty(row.get("observedResult"), f"{path}: observedResult")
    if row.get("faultObserved") is not True:
        raise ValueError(f"{path}: injected fault was not observed")
    if row.get("recoveryObserved") is not True:
        raise ValueError(f"{path}: recovery behavior was not observed")
    if expected_scenario == "power-loss" and started_boot == completed_boot:
        raise ValueError(f"{path}: power-loss receipt did not cross a boot identity")

    expected = matrix[matrix_id]
    semantic_fields = {
        "observedCommitState": "commitState",
        "observedRetryRule": "retryRule",
        "observedStartupDetection": "startupDetection",
        "observedRecoveryAction": "recoveryAction",
        "observedReadService": "readService",
    }
    for receipt_field, matrix_field in semantic_fields.items():
        observed = nonempty(row.get(receipt_field), f"{path}: {receipt_field}")
        if observed != expected[matrix_field]:
            raise ValueError(
                f"{path}: {receipt_field} does not match the repository crash contract"
            )

    return {
        "scenario": expected_scenario,
        "matrixScenarioId": matrix_id,
        "path": str(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "targetIdentity": target_identity,
        "startedBootId": started_boot,
        "completedBootId": completed_boot,
        "faultInjectionId": row["faultInjectionId"],
        "observedResult": row["observedResult"],
        "contract": {
            "commitState": expected["commitState"],
            "retryRule": expected["retryRule"],
            "startupDetection": expected["startupDetection"],
            "recoveryAction": expected["recoveryAction"],
            "readService": expected["readService"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--target-profile", required=True)
    parser.add_argument("--receipt-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if len(args.candidate_sha) != 40 or any(
        character not in "0123456789abcdef" for character in args.candidate_sha
    ):
        raise SystemExit("candidate SHA must be a lowercase 40-character SHA-1")
    if (
        not args.target_profile
        or len(args.target_profile) > 128
        or any(
            not (character.isalnum() or character in "._-")
            for character in args.target_profile
        )
    ):
        raise SystemExit("invalid target profile")
    if not args.receipt_dir.is_dir():
        raise SystemExit("receipt directory is missing")

    try:
        matrix = matrix_rows()
        receipts = [
            validate_receipt(
                args.receipt_dir / f"{scenario}.json",
                scenario,
                matrix_id,
                matrix,
                args.candidate_sha,
                args.target_profile,
            )
            for scenario, matrix_id in SCENARIOS.items()
        ]
    except (KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"target-host evidence validation failed: {error}") from error

    identities = {receipt["targetIdentity"] for receipt in receipts}
    if len(identities) != 1:
        raise SystemExit("scenario receipts name different target identities")
    injection_ids = {receipt["faultInjectionId"] for receipt in receipts}
    if len(injection_ids) != len(receipts):
        raise SystemExit("fault injection identities must be unique per scenario")

    manifest = {
        "schema": "hepta.authbus.target-host-qualification.v2",
        "candidateSha": args.candidate_sha,
        "targetProfile": args.target_profile,
        "targetIdentity": receipts[0]["targetIdentity"],
        "generatedAt": dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "crashConsistencyMatrixSha256": sha256(MATRIX_PATH),
        "scenarios": receipts,
        "scenarioCount": len(receipts),
        "independentSecurityAcceptance": False,
        "operatorActivation": False,
        "release": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
