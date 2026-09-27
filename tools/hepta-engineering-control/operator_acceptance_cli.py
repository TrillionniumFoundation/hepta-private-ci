#!/usr/bin/env python3
"""Verify an externally signed operator receipt against an acceptance candidate."""

from __future__ import annotations

import argparse
from dataclasses import fields
import json
import os
from pathlib import Path

from control_engineering_v2.clock import ClockPolicy
from control_engineering_v2.control_plane import EngineeringError, semantic_digest
from control_engineering_v2.operator_acceptance import (
    OperatorAcceptanceReceipt,
    verify_operator_acceptance,
)
from control_engineering_v2.provider_adapters import ProviderCommand, ProviderTrustStore


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EngineeringError("operator_acceptance_input")
    return value


def _typed_receipt(value: dict[str, object]) -> OperatorAcceptanceReceipt:
    expected = {field.name for field in fields(OperatorAcceptanceReceipt)}
    if set(value) != expected:
        raise EngineeringError("operator_acceptance_input")
    try:
        return OperatorAcceptanceReceipt(**value)
    except (TypeError, ValueError):
        raise EngineeringError("operator_acceptance_input") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--operator-receipt", type=Path, required=True)
    parser.add_argument("--signature-provider", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--now-ns", type=int)
    args = parser.parse_args()
    candidate = _load(args.candidate)
    receipt = _typed_receipt(_load(args.operator_receipt))
    provider = ProviderCommand("signature-provider", args.signature_provider)
    environment = {
        "HEPTA_PROVIDER_" + key[len("HEPTA_PROVIDER_SIGNATURE_"):]: value
        for key, value in os.environ.items()
        if key.startswith("HEPTA_PROVIDER_SIGNATURE_")
    }
    trust = ProviderTrustStore(provider, environment=environment)
    external = candidate.get("externalProviderBundle")
    recovery = candidate.get("recoveryRehearsal")
    capacity = candidate.get("capacityDecision")
    if not all(isinstance(value, dict) for value in (external, recovery, capacity)):
        raise EngineeringError("operator_acceptance_candidate")
    digest = verify_operator_acceptance(
        receipt,
        trust,
        ClockPolicy(5_000_000_000, 300_000_000_000, 3_600_000_000_000),
        expected_target_id=str(candidate["targetId"]),
        expected_source_commit=str(candidate["sourceCommit"]),
        expected_source_tree=str(candidate["sourceTree"]),
        expected_provider_bundle_digest=str(external["bundle_digest"]),
        expected_recovery_rehearsal_digest=semantic_digest(recovery),
        now_ns=args.now_ns,
    )
    if receipt.capacity_policy_digest != capacity["policy_digest"]:
        raise EngineeringError("operator_acceptance_capacity_policy")
    if receipt.capacity_observation_digest != capacity["observation_digest"]:
        raise EngineeringError("operator_acceptance_capacity_observation")
    value = {
        "schema": "hepta.control-engineering-operator-acceptance-verification.v1",
        "candidateDigest": candidate["candidateDigest"],
        "operatorAcceptanceDigest": digest,
        "operatorAccepted": True,
        "canonicalProductionImplementation": False,
        "releaseAuthority": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
