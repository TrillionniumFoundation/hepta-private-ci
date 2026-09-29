#!/usr/bin/env python3
"""Validate raw AuthBus target-host fault receipts and bind them to one candidate."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

SCENARIOS = (
    "enospc",
    "power-loss",
    "permission-loss",
    "restore-old-snapshot",
)
SCHEMA = "hepta.authbus.target-host-scenario.v1"


def load_json(path: Path) -> dict:
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"{path}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: receipt must be an object")
    return value


def literal(value, kind, label: str):
    if type(value) is not kind:
        raise ValueError(f"{label}: expected {kind.__name__}")
    return value


def nonempty(value, label: str) -> str:
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


def validate_receipt(
    path: Path,
    expected_scenario: str,
    candidate_sha: str,
    target_profile: str,
) -> dict:
    row = load_json(path)
    if row.get("schema") != SCHEMA:
        raise ValueError(f"{path}: wrong schema")
    if row.get("scenario") != expected_scenario:
        raise ValueError(f"{path}: scenario substitution")
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
    return {
        "scenario": expected_scenario,
        "path": str(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "targetIdentity": target_identity,
        "startedBootId": started_boot,
        "completedBootId": completed_boot,
        "faultInjectionId": row["faultInjectionId"],
        "observedResult": row["observedResult"],
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

    receipts = [
        validate_receipt(
            args.receipt_dir / f"{scenario}.json",
            scenario,
            args.candidate_sha,
            args.target_profile,
        )
        for scenario in SCENARIOS
    ]
    identities = {receipt["targetIdentity"] for receipt in receipts}
    if len(identities) != 1:
        raise SystemExit("scenario receipts name different target identities")
    injection_ids = {receipt["faultInjectionId"] for receipt in receipts}
    if len(injection_ids) != len(receipts):
        raise SystemExit("fault injection identities must be unique per scenario")

    manifest = {
        "schema": "hepta.authbus.target-host-qualification.v1",
        "candidateSha": args.candidate_sha,
        "targetProfile": args.target_profile,
        "targetIdentity": receipts[0]["targetIdentity"],
        "generatedAt": dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "scenarios": receipts,
        "independentSecurityAcceptance": False,
        "activation": False,
        "release": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
