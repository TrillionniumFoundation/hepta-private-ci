#!/usr/bin/env python3
"""Collect a production-acceptance candidate from real external provider commands.

This command deliberately stops before operator acceptance or canonical
``production_implementation`` changes.  It binds real provider receipts, a signed
audit checkpoint, capacity policy, and backup/restore rehearsal into one retained
candidate for an independent operator to review and sign.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import time

from control_engineering_v2.audit_checkpoint import build_audit_checkpoint
from control_engineering_v2.capacity_policy import (
    SQLiteCapacityObservation,
    SQLiteCapacityPolicy,
    evaluate_sqlite_capacity,
)
from control_engineering_v2.clock import ClockPolicy
from control_engineering_v2.control_plane import EngineeringError, EngineeringStore, semantic_digest
from control_engineering_v2.provider_adapters import (
    ProviderCommand,
    ProviderTrustStore,
    collect_external_production_evidence,
)
from control_engineering_v2.recovery_rehearsal import rehearse_backup_restore


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EngineeringError("production_acceptance_input")
    return value


def _provider(path: str, provider_id: str) -> ProviderCommand:
    return ProviderCommand(provider_id, path, production=True)


def _provider_environment(role: str) -> dict[str, str]:
    prefix = f"HEPTA_PROVIDER_{role.upper()}_"
    result: dict[str, str] = {}
    for key, value in os.environ.items():
        if key.startswith(prefix):
            result["HEPTA_PROVIDER_" + key[len(prefix):]] = value
    return result


def _verify_external_signatures(bundle, trust: ProviderTrustStore) -> None:
    receipts = (
        bundle.distributed_revocation_frontier,
        bundle.distributed_fence,
        bundle.audit_publication,
        *bundle.key_custody,
        bundle.completion,
        bundle.terminal_observation,
    )
    for receipt in receipts:
        if not trust.verify(
            receipt,
            receipt.issuer,
            receipt.signing_identity,
            receipt.signature,
        ):
            raise EngineeringError("external_provider_signature")


def build_acceptance_candidate(args: argparse.Namespace) -> dict[str, object]:
    now = time.time_ns()
    clock_policy = ClockPolicy(
        args.max_future_skew_ns,
        args.max_observation_age_ns,
        args.max_receipt_lifetime_ns,
    )
    expires = now + min(args.receipt_ttl_ns, args.max_receipt_lifetime_ns)
    signature_environment = _provider_environment("signature")
    signature_provider = _provider(args.signature_provider, "signature-provider")
    trust = ProviderTrustStore(
        signature_provider, environment=signature_environment
    )
    requests = _load(args.request_bundle)
    expected_request_keys = {
        "distributedRequest",
        "keyCustodyRequest",
        "completionRequest",
        "terminalRequest",
    }
    if set(requests) != expected_request_keys:
        raise EngineeringError("production_acceptance_request_bundle")
    policy_raw = _load(args.capacity_policy)
    observation_raw = _load(args.capacity_observation)
    policy = SQLiteCapacityPolicy(**policy_raw)
    observation = SQLiteCapacityObservation(**observation_raw)
    capacity = evaluate_sqlite_capacity(policy, observation)
    if capacity.within_hard_limits is not True:
        raise EngineeringError("production_capacity_hard_limit")

    with EngineeringStore(args.database) as store:
        checkpoint, owner_anchor = build_audit_checkpoint(
            store,
            source_commit=args.source_commit,
            source_tree=args.source_tree,
            issuer=args.checkpoint_issuer,
            signing_identity=args.checkpoint_signing_identity,
            trust_store=trust,
            clock_policy=clock_policy,
            observed_unix_ns=now,
            expires_unix_ns=expires,
            now_ns=now,
        )
    recovery = rehearse_backup_restore(
        args.database,
        args.backup,
        source_commit=args.source_commit,
        source_tree=args.source_tree,
        issuer=args.recovery_issuer,
        signing_identity=args.recovery_signing_identity,
        trust_store=trust,
        clock_policy=clock_policy,
        observed_unix_ns=now,
        expires_unix_ns=expires,
        now_ns=now,
    )
    providers = {
        "distributed": _provider(args.distributed_provider, "distributed-lease-provider"),
        "audit": _provider(args.audit_provider, "immutable-audit-provider"),
        "custody": _provider(args.key_custody_provider, "key-custody-provider"),
        "completion": _provider(args.completion_provider, "completion-observer"),
        "terminal": _provider(args.terminal_provider, "terminal-observer"),
    }
    environments = {
        providers["distributed"].provider_id: _provider_environment("distributed"),
        providers["audit"].provider_id: _provider_environment("audit"),
        providers["custody"].provider_id: _provider_environment("custody"),
        providers["completion"].provider_id: _provider_environment("completion"),
        providers["terminal"].provider_id: _provider_environment("terminal"),
    }
    bundle = collect_external_production_evidence(
        distributed_lease_provider=providers["distributed"],
        immutable_audit_provider=providers["audit"],
        key_custody_provider=providers["custody"],
        completion_observer=providers["completion"],
        terminal_observer=providers["terminal"],
        checkpoint=checkpoint,
        distributed_request=requests["distributedRequest"],
        key_custody_request=requests["keyCustodyRequest"],
        completion_request=requests["completionRequest"],
        terminal_request=requests["terminalRequest"],
        environment_by_provider=environments,
    )
    _verify_external_signatures(bundle, trust)
    body: dict[str, object] = {
        "schema": "hepta.control-engineering-production-acceptance-candidate.v1",
        "targetId": args.target_id,
        "sourceCommit": args.source_commit,
        "sourceTree": args.source_tree,
        "auditCheckpoint": asdict(checkpoint),
        "ownerStateAnchor": asdict(owner_anchor),
        "recoveryRehearsal": asdict(recovery),
        "capacityDecision": asdict(capacity),
        "externalProviderBundle": asdict(bundle),
        "operatorAcceptanceRequired": True,
        "canonicalProductionImplementation": False,
        "runtimeAuthority": False,
        "mergeAuthority": False,
        "deploymentAuthority": False,
        "releaseAuthority": False,
    }
    body["candidateDigest"] = semantic_digest(body)
    return body


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--database", type=Path, required=True)
    result.add_argument("--backup", type=Path, required=True)
    result.add_argument("--target-id", required=True)
    result.add_argument("--source-commit", required=True)
    result.add_argument("--source-tree", required=True)
    result.add_argument("--request-bundle", type=Path, required=True)
    result.add_argument("--capacity-policy", type=Path, required=True)
    result.add_argument("--capacity-observation", type=Path, required=True)
    result.add_argument("--signature-provider", required=True)
    result.add_argument("--distributed-provider", required=True)
    result.add_argument("--audit-provider", required=True)
    result.add_argument("--key-custody-provider", required=True)
    result.add_argument("--completion-provider", required=True)
    result.add_argument("--terminal-provider", required=True)
    result.add_argument("--checkpoint-issuer", required=True)
    result.add_argument("--checkpoint-signing-identity", required=True)
    result.add_argument("--recovery-issuer", required=True)
    result.add_argument("--recovery-signing-identity", required=True)
    result.add_argument("--max-future-skew-ns", type=int, default=5_000_000_000)
    result.add_argument("--max-observation-age-ns", type=int, default=300_000_000_000)
    result.add_argument("--max-receipt-lifetime-ns", type=int, default=3_600_000_000_000)
    result.add_argument("--receipt-ttl-ns", type=int, default=300_000_000_000)
    result.add_argument("--output", type=Path, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    value = build_acceptance_candidate(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"candidateDigest": value["candidateDigest"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
