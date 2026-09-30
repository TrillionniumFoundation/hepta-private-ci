#!/usr/bin/env python3
"""Validate an exact-candidate AuthBus end-to-end performance receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs/modules/auth.authbus/PERFORMANCE_QUALIFICATION.json"
RECEIPT_SCHEMA = "hepta.authbus.performance-receipt.v1"
HEX = set("0123456789abcdef")


def load_json(path: Path) -> dict[str, Any]:
    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"{path}: duplicate JSON key {key!r}")
            value[key] = item
        return value

    loaded = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: expected an object")
    return loaded


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def exact_string(value: Any, label: str, limit: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"{label}: expected a non-empty bounded string")
    return value


def exact_int(value: Any, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label}: expected an integer >= {minimum}")
    return value


def valid_sha1(value: str) -> bool:
    return len(value) == 40 and all(character in HEX for character in value)


def validate_percentiles(
    stage: dict[str, Any],
    label: str,
    minimum_samples: int,
) -> dict[str, int]:
    required = {"count", "p50Us", "p95Us", "p99Us", "maxUs"}
    if set(stage) != required:
        raise ValueError(f"{label}: latency fields must be exactly {sorted(required)}")
    count = exact_int(stage["count"], f"{label}.count", minimum_samples)
    p50 = exact_int(stage["p50Us"], f"{label}.p50Us")
    p95 = exact_int(stage["p95Us"], f"{label}.p95Us")
    p99 = exact_int(stage["p99Us"], f"{label}.p99Us")
    maximum = exact_int(stage["maxUs"], f"{label}.maxUs")
    if not (p50 <= p95 <= p99 <= maximum):
        raise ValueError(f"{label}: percentiles are not monotonic")
    return {
        "count": count,
        "p50Us": p50,
        "p95Us": p95,
        "p99Us": p99,
        "maxUs": maximum,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--control-sha", required=True)
    parser.add_argument("--target-profile", required=True)
    parser.add_argument("--expected-target-identity", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if not valid_sha1(args.candidate_sha):
        raise SystemExit("candidate SHA must be a lowercase 40-character SHA-1")
    if not valid_sha1(args.control_sha):
        raise SystemExit("control SHA must be a lowercase 40-character SHA-1")
    if not args.receipt.is_file():
        raise SystemExit("performance receipt is missing")

    try:
        contract = load_json(CONTRACT_PATH)
        receipt = load_json(args.receipt)
        if contract.get("schema") != "hepta.authbus.performance-contract.v1":
            raise ValueError("performance contract schema mismatch")
        if receipt.get("schema") != RECEIPT_SCHEMA:
            raise ValueError("performance receipt schema mismatch")
        if receipt.get("candidateSha") != args.candidate_sha:
            raise ValueError("performance receipt candidate drift")
        if receipt.get("controlSha") != args.control_sha:
            raise ValueError("performance receipt trusted-controller drift")
        if receipt.get("targetProfile") != args.target_profile:
            raise ValueError("performance receipt target-profile drift")
        target_identity = exact_string(
            receipt.get("targetIdentity"), "performance.targetIdentity"
        )
        if target_identity != args.expected_target_identity:
            raise ValueError("performance receipt target identity drift")
        exact_string(
            receipt.get("environmentFingerprint"),
            "performance.environmentFingerprint",
        )
        raw_samples_sha = exact_string(
            receipt.get("rawSamplesSha256"), "performance.rawSamplesSha256", 64
        )
        if len(raw_samples_sha) != 64 or any(
            character not in HEX for character in raw_samples_sha
        ):
            raise ValueError("performance.rawSamplesSha256 is not lowercase SHA-256")
        if receipt.get("completed") is not True:
            raise ValueError("performance harness did not complete")

        minimum_samples = exact_int(
            contract.get("minimumSamplesPerCase"),
            "contract.minimumSamplesPerCase",
            1,
        )
        required_stages = contract.get("requiredStages")
        if not isinstance(required_stages, list) or not required_stages:
            raise ValueError("performance contract has no required stages")
        required_stage_set = set(required_stages)
        contract_rows = contract.get("caseContracts")
        if not isinstance(contract_rows, list):
            raise ValueError("performance contract has no cases")
        contract_by_id = {
            exact_string(row.get("id"), "contract case id"): row
            for row in contract_rows
            if isinstance(row, dict)
        }
        required_ids = set(contract.get("requiredCaseIds", []))
        if set(contract_by_id) != required_ids:
            raise ValueError("performance contract required-case list drift")

        profiles = contract.get("databaseProfiles")
        if not isinstance(profiles, dict):
            raise ValueError("performance database profiles are missing")
        receipt_rows = receipt.get("cases")
        if not isinstance(receipt_rows, list):
            raise ValueError("performance receipt has no cases")
        observed: dict[str, dict[str, Any]] = {}
        for row in receipt_rows:
            if not isinstance(row, dict):
                raise ValueError("performance case is not an object")
            case_id = exact_string(row.get("id"), "performance case id")
            if case_id in observed:
                raise ValueError(f"duplicate performance case {case_id}")
            expected = contract_by_id.get(case_id)
            if expected is None:
                raise ValueError(f"unexpected performance case {case_id}")
            for field in ("databaseProfile", "concurrency", "storageMode", "faultMode"):
                if row.get(field) != expected.get(field):
                    raise ValueError(f"{case_id}: {field} does not match contract")
            profile_name = exact_string(
                row.get("databaseProfile"), f"{case_id}.databaseProfile"
            )
            profile = profiles.get(profile_name)
            if not isinstance(profile, dict):
                raise ValueError(f"{case_id}: unknown database profile")
            history_rows = exact_int(
                row.get("historyRows"), f"{case_id}.historyRows"
            )
            active_reservations = exact_int(
                row.get("activeReservations"), f"{case_id}.activeReservations"
            )
            if history_rows < exact_int(
                profile.get("minimumHistoryRows"),
                f"profile {profile_name}.minimumHistoryRows",
            ):
                raise ValueError(f"{case_id}: history profile is undersized")
            if active_reservations < exact_int(
                profile.get("minimumActiveReservations"),
                f"profile {profile_name}.minimumActiveReservations",
            ):
                raise ValueError(f"{case_id}: active-reservation profile is undersized")
            sample_count = exact_int(
                row.get("sampleCount"), f"{case_id}.sampleCount", minimum_samples
            )
            stages = row.get("stages")
            if not isinstance(stages, dict) or set(stages) != required_stage_set:
                raise ValueError(f"{case_id}: stage set does not match contract")
            stage_projection = {
                stage_name: validate_percentiles(
                    stage,
                    f"{case_id}.{stage_name}",
                    minimum_samples,
                )
                for stage_name, stage in stages.items()
                if isinstance(stage, dict)
            }
            if len(stage_projection) != len(required_stage_set):
                raise ValueError(f"{case_id}: malformed stage payload")
            if stage_projection["endToEnd"]["count"] != sample_count:
                raise ValueError(f"{case_id}: end-to-end sample count drift")
            dispositions = row.get("dispositions")
            if not isinstance(dispositions, dict):
                raise ValueError(f"{case_id}: mutation dispositions are missing")
            disposition_projection = {
                name: exact_int(value, f"{case_id}.dispositions.{name}")
                for name, value in dispositions.items()
            }
            if sum(disposition_projection.values()) != sample_count:
                raise ValueError(f"{case_id}: disposition counts do not equal samples")
            if expected["faultMode"] == "none" and disposition_projection.get(
                "success", 0
            ) != sample_count:
                raise ValueError(f"{case_id}: normal case did not fully succeed")
            observed[case_id] = {
                "id": case_id,
                "databaseProfile": profile_name,
                "concurrency": row["concurrency"],
                "storageMode": row["storageMode"],
                "faultMode": row["faultMode"],
                "historyRows": history_rows,
                "activeReservations": active_reservations,
                "sampleCount": sample_count,
                "stages": stage_projection,
                "dispositions": disposition_projection,
            }

        if set(observed) != required_ids:
            missing = sorted(required_ids - set(observed))
            extra = sorted(set(observed) - required_ids)
            raise ValueError(
                f"performance matrix incomplete: missing={missing}, extra={extra}"
            )
    except (KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"performance evidence validation failed: {error}") from error

    manifest = {
        "schema": "hepta.authbus.performance-evidence.v1",
        "candidateSha": args.candidate_sha,
        "controlSha": args.control_sha,
        "targetProfile": args.target_profile,
        "targetIdentity": target_identity,
        "contractSha256": sha256(CONTRACT_PATH),
        "rawReceiptSha256": sha256(args.receipt),
        "rawSamplesSha256": raw_samples_sha,
        "caseCount": len(observed),
        "cases": [observed[case_id] for case_id in sorted(observed)],
        "thresholdDecision": "external_activation_owner",
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
