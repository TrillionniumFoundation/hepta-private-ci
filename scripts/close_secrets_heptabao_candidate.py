#!/usr/bin/env python3
'''Materialize one reviewable secrets.heptabao source candidate.

This development-only transformation is deterministic and idempotent. It may
change source and canonical documentation, but it never runs qualification and
is never invoked by the read-only qualification workflows. The commit produced
from these bytes is the only object eligible for exact-source review.
'''
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/modules/secrets.heptabao/MODULE_MANIFEST_V1.json"

STATUS_START = "<!-- secrets-heptabao-sqlite-source-status:v1 -->"
STATUS_END = "<!-- /secrets-heptabao-sqlite-source-status:v1 -->"
STATUS_BLOCK = f'''{STATUS_START}
## SQLite source and qualification status

The current source candidate contains `SqliteBaoOwnerV1` and
`SqliteBaoProductRuntimeV1`, including revision-CAS transitions, generation-
fenced recovery claims, schema-4 reference import, immutable terminal archive
and external-checkpoint hashing/publication hooks. This is a **source-presence**
fact only. Exact-head compilation/qualification, storage-profile qualification,
a named product caller, target-host qualification, activation, operator
acceptance and release remain false until independently proved for one exact
SHA. The fixed provider remains KV-v2-read-only; generic dynamic issue, renew
and revoke remain fail-closed.
{STATUS_END}
'''


def append_unique(values: list[str], additions: list[str]) -> list[str]:
    result = list(values)
    for value in additions:
        if value not in result:
            result.append(value)
    return result


def upsert_named(rows: list[dict[str, Any]], key: str, row: dict[str, Any]) -> None:
    for index, existing in enumerate(rows):
        if existing.get(key) == row[key]:
            rows[index] = row
            return
    rows.append(row)


def box_product_errors() -> None:
    constructor = re.compile(
        r"BaoProductHostError::(OutcomePending|TerminalFailure)"
        r"\((?!Box::new\()"
        r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"
        r"\)"
    )
    for relative in (
        "codex-rs/hepta-bao-adapter/src/final_use_host.rs",
        "codex-rs/hepta-bao-adapter/src/sqlite_product_runtime.rs",
    ):
        path = ROOT / relative
        text = path.read_text(encoding="utf-8")
        text = text.replace(
            "OutcomePending(BaoConsumptionOperationV1)",
            "OutcomePending(Box<BaoConsumptionOperationV1>)",
        ).replace(
            "TerminalFailure(BaoConsumptionOperationV1)",
            "TerminalFailure(Box<BaoConsumptionOperationV1>)",
        )
        text = constructor.sub(
            lambda match: (
                f"BaoProductHostError::{match.group(1)}"
                f"(Box::new({match.group(2)}))"
            ),
            text,
        )
        if re.search(
            r"BaoProductHostError::(?:OutcomePending|TerminalFailure)"
            r"\((?!Box(?:::new\(|<))",
            text,
        ):
            raise SystemExit(f"unboxed product-error constructor remains in {relative}")
        path.write_text(text, encoding="utf-8")


def materialize_manifest() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    manifest.setdefault("documents", {}).update(
        {
            "productionReadiness": (
                "docs/modules/secrets.heptabao/PRODUCTION_READINESS.md"
            ),
            "readinessPolicy": (
                "docs/modules/secrets.heptabao/READINESS_POLICY_V1.json"
            ),
        }
    )
    manifest["buildSurface"] = {
        "kind": "single_complete",
        "cargoFeatures": [],
        "statement": (
            "The adapter is one complete Cargo build surface. Qualification "
            "must not pass undeclared synthetic feature names."
        ),
    }
    manifest["states"] = {
        "source": "implemented_candidate",
        "implementation": "registered_read_saga_with_sqlite_owner_source_present",
        "durability": "sqlite_owner_source_present_unqualified",
        "qualification": "exact_source_and_deterministic_merge_required",
        "activation": "not_product_composed",
        "acceptance": "not_granted",
    }
    manifest["readinessDimensions"] = {
        "sourcePresent": True,
        "sourceCompiled": "unproved_for_exact_head",
        "sourceQualified": False,
        "storageProfileQualified": False,
        "productComposed": False,
        "targetHostQualified": False,
        "activated": False,
        "operatorAccepted": False,
        "released": False,
    }

    manifest["currentCapabilities"] = append_unique(
        manifest.get("currentCapabilities", []),
        [
            (
                "transactional SQLite metadata-owner source with revision CAS, "
                "append-only transitions, reconciliation claims, terminal archive "
                "and checkpoint hashing"
            ),
            (
                "SQLite product-runtime source with atomic forward execution "
                "leases, bounded recovery claims and secret-free metrics"
            ),
            (
                "schema-4 JSON reference-owner import into the SQLite owner with "
                "an immutable import receipt"
            ),
        ],
    )
    target_only = [
        value
        for value in manifest.get("targetOnlyCapabilities", [])
        if not value.startswith("transactional SQLite production owner")
        and not value.startswith("bounded fair recovery worker")
    ]
    manifest["targetOnlyCapabilities"] = append_unique(
        target_only,
        [
            (
                "exact-head and deterministic-merge qualification of the SQLite "
                "owner/runtime source"
            ),
            "selected Agentd or App Server production bootstrap",
            (
                "independently operated trusted-time settlement and key-rotation "
                "services"
            ),
            (
                "external anti-rollback checkpoint service and disaster-recovery "
                "ceremony"
            ),
            "target-host power-loss and long-history archival qualification",
            "selected-host metrics export alerting and retention policy",
            "independent operator acceptance promotion and release",
        ],
    )
    manifest["nonclaims"] = append_unique(
        manifest.get("nonclaims", []),
        [
            (
                "SQLite owner and runtime source presence is not exact-head "
                "qualification, product composition, activation or deployment."
            ),
            (
                "Qualification workflows are read-only and never materialize, "
                "commit or push source."
            ),
            (
                "The adapter intentionally has one complete Cargo build surface; "
                "undeclared feature names are not a product boundary."
            ),
        ],
    )

    operations = manifest.setdefault("operations", [])
    for row in (
        {
            "operation": "sqlite_owner_open_and_verify",
            "symbol": "SqliteBaoOwnerV1::open",
            "path": "codex-rs/hepta-bao-adapter/src/sqlite_owner.rs",
            "class": "sqlite_owner_source_present_unqualified",
        },
        {
            "operation": "sqlite_reference_import",
            "symbol": "SqliteBaoOwnerV1::import_reference_snapshot",
            "path": "codex-rs/hepta-bao-adapter/src/sqlite_owner.rs",
            "class": "schema4_reference_import_source_present",
        },
        {
            "operation": "sqlite_reconciliation_claims",
            "symbol": "SqliteBaoOwnerV1::claim_due_reconciliation",
            "path": "codex-rs/hepta-bao-adapter/src/sqlite_owner.rs",
            "class": "bounded_generation_fenced_recovery_claims",
        },
        {
            "operation": "sqlite_checkpoint_publication",
            "symbol": "SqliteBaoOwnerV1::publish_checkpoint_with",
            "path": "codex-rs/hepta-bao-adapter/src/sqlite_owner.rs",
            "class": "caller_owned_external_checkpoint_boundary",
        },
        {
            "operation": "sqlite_terminal_archive",
            "symbol": "SqliteBaoOwnerV1::archive_terminal_before",
            "path": "codex-rs/hepta-bao-adapter/src/sqlite_owner.rs",
            "class": "bounded_immutable_terminal_archive",
        },
        {
            "operation": "sqlite_product_runtime",
            "symbol": "SqliteBaoProductRuntimeV1",
            "path": "codex-rs/hepta-bao-adapter/src/sqlite_product_runtime.rs",
            "class": "product_runtime_source_present_not_composed",
        },
    ):
        upsert_named(operations, "operation", row)

    anchors = manifest.setdefault("sourceAnchors", [])
    for row in (
        {
            "path": "codex-rs/hepta-bao-adapter/src/sqlite_owner.rs",
            "mustContain": [
                "pub struct SqliteBaoOwnerV1",
                "pub async fn import_reference_snapshot",
                "pub async fn claim_due_reconciliation",
                "pub async fn publish_checkpoint_with",
                "pub async fn archive_terminal_before",
                "BEGIN IMMEDIATE",
            ],
        },
        {
            "path": "codex-rs/hepta-bao-adapter/src/sqlite_product_runtime.rs",
            "mustContain": [
                "pub struct SqliteBaoProductRuntimeV1",
                "claim_consumption_for_execution",
                "reconcile_due",
                "record_claimed_reconciliation_failure",
            ],
        },
        {
            "path": "codex-rs/hepta-bao-adapter/migrations/0001_bao_owner_v1.sql",
            "mustContain": [
                "CREATE TABLE bao_operation",
                "CREATE TABLE bao_consumption",
                "CREATE TABLE bao_transition",
                "CREATE TABLE bao_terminal_archive",
            ],
        },
        {
            "path": "codex-rs/hepta-bao-adapter/migrations/0002_reconciliation_claims.sql",
            "mustContain": [
                "claim_owner",
                "claim_until_unix_ms",
                "claim_generation",
                "bao_reference_import",
            ],
        },
        {
            "path": "codex-rs/hepta-bao-adapter/src/sqlite_owner_tests.rs",
            "mustContain": [
                "private_owner_opens_reopens_and_binds_external_checkpoint",
                "success_path_reopens_archives_and_preserves_exact_retry_identity",
                "concurrent_cas_allows_only_one_changed_reservation_identity",
            ],
        },
    ):
        upsert_named(anchors, "path", row)

    identity = manifest.setdefault("candidateIdentity", {})
    identity.update(
        {
            "binding": "external_read_only_ci_attestation",
            "identityRule": (
                "candidateSha == testedSha == documentedSha == "
                "artifactSourceSha == qualificationSha"
            ),
            "requiredFields": [
                "sourceCommitSha",
                "sourceTreeSha",
                "baseSha",
                "deterministicMergeSha",
                "workflowSha",
                "workflowRunId",
                "workflowAttempt",
                "rustToolchain",
                "targetTriple",
                "dependencyLockSha256",
                "migrationSha256",
                "schemaSha256",
                "testSetSha256",
                "documentationSha256",
                "artifactHashes",
            ],
            "selfReferentialCommitInDocument": False,
        }
    )

    MANIFEST.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def optional_rewrite(relative: str, substitutions: list[tuple[str, str]]) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    for pattern, replacement in substitutions:
        text = re.sub(pattern, replacement, text, flags=re.MULTILINE)
    path.write_text(text, encoding="utf-8")


def upsert_status(relative: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if STATUS_START in text and STATUS_END in text:
        prefix, remainder = text.split(STATUS_START, 1)
        _, suffix = remainder.split(STATUS_END, 1)
        text = prefix.rstrip() + "\n\n" + STATUS_BLOCK + suffix.lstrip("\n")
    else:
        text = text.rstrip() + "\n\n" + STATUS_BLOCK
    path.write_text(text, encoding="utf-8")


def materialize_documents() -> None:
    optional_rewrite(
        "docs/modules/secrets.heptabao/LEASE_OWNER_V3.md",
        [
            (
                r"This is the current implementation contract for PR #998 on\n"
                r"`codex/secrets-heptabao-convergence`\.",
                "This is the current durable-owner contract for the canonical "
                "`secrets.heptabao` candidate.",
            ),
            (
                r"The Bao metadata owner in this document remains the JSON reference "
                r"owner; an\s+AuthBus SQLite dependency is not a Bao production writer\.",
                "The JSON profile remains the reference and migration oracle. The "
                "candidate also contains a Bao-owned SQLite writer/runtime source; "
                "source presence is not product composition or production qualification.",
            ),
        ],
    )
    optional_rewrite(
        "docs/modules/secrets.heptabao/CONSUMPTION_SAGA_V4.md",
        [
            (
                r"A production SQLite replacement is still pending in this source "
                r"candidate\.",
                "A transactional SQLite owner/runtime source is present in this "
                "candidate but remains exact-head and storage-profile unqualified.",
            ),
        ],
    )
    optional_rewrite(
        "docs/modules/secrets.heptabao/OPERATIONS_AND_CAPACITY_V1.md",
        [
            (
                r"A production SQLite owner remains target-only\.",
                "A transactional SQLite owner/runtime source is present, but exact-head, "
                "storage-profile, target-host and product-composition qualification "
                "remain open.",
            ),
        ],
    )
    optional_rewrite(
        "codex-rs/hepta-bao-adapter/README.md",
        [
            (
                r"A production SQLite\s+owner is still target-only:",
                "The transactional SQLite owner/runtime source is present but remains "
                "unqualified and uncomposed:",
            ),
        ],
    )

    for relative in (
        "docs/modules/secrets.heptabao/TECHNICAL.md",
        "docs/lane-a-foundation/secrets.heptabao/CURRENT_IMPLEMENTATION.md",
        "docs/modules/secrets.heptabao/CONSUMPTION_SAGA_V4.md",
        "docs/modules/secrets.heptabao/LEASE_OWNER_V3.md",
        "docs/modules/secrets.heptabao/OPERATIONS_AND_CAPACITY_V1.md",
        "codex-rs/hepta-bao-adapter/README.md",
    ):
        upsert_status(relative)

    policy_path = ROOT / "docs/modules/secrets.heptabao/READINESS_POLICY_V1.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy.update(
        {
            "schema": "hepta.secrets-heptabao-readiness-policy.v2",
            "module": "secrets.heptabao",
            "buildSurface": "single_complete",
            "cargoFeatures": [],
            "identityRule": (
                "candidateSha == testedSha == documentedSha == "
                "artifactSourceSha == qualificationSha"
            ),
            "aggregationRule": (
                "one workflow run and one attempt; cross-SHA and cross-attempt "
                "stitching forbidden"
            ),
            "productCallerState": "not_composed",
            "productionQualified": False,
            "mergeReady": False,
        }
    )
    policy_path.write_text(
        json.dumps(policy, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    readiness = ROOT / "docs/modules/secrets.heptabao/PRODUCTION_READINESS.md"
    readiness.write_text(
        """# `secrets.heptabao` production-readiness boundary

This document accompanies `READINESS_POLICY_V1.json` and the read-only
CI-generated `hepta.secrets-heptabao-readiness.v2` receipt.

## Exact-candidate rule

Source, tests, documentation, artifacts and qualification must refer to one Git
commit and one workflow attempt. Results from another SHA or attempt cannot be
combined. Qualification checks out the exact review object with persisted Git
credentials disabled and must leave the complete worktree unchanged.

## Build surface

`codex-hepta-bao-adapter` is one complete Cargo build surface. SQLite, AuthBus,
HTTPS and registered-host code are not represented by undeclared synthetic
feature names. The qualifier runs `cargo metadata --locked --no-deps` and the
normal full package targets.

## Current source truth

`SqliteBaoOwnerV1` and `SqliteBaoProductRuntimeV1` are source-present. The owner
contains revision CAS, append-only transitions, bounded generation-fenced
recovery claims, schema-4 import, immutable terminal archival and checkpoint
hashing/publication hooks. No non-test Agentd or App Server binary currently
selects this runtime.

Consequently source presence is true while source qualification,
storage-profile qualification, product composition, target-host qualification,
activation, operator acceptance and release remain false until independently
proved for one exact SHA.

## Deployment topology

| Deployment | Current state | Required proof |
|---|---|---|
| One process, local filesystem | source candidate | exact-head tests, schema verification, anti-rollback operation |
| Multiple processes, one host | unqualified | writer exclusion, stale-claim takeover and shutdown drain |
| Multiple pods on one volume | denied by default | independently qualified filesystem lock and fencing semantics |
| Multiple hosts/network filesystem | denied | independent storage qualification |
| Active/passive failover | target-only | owner epoch and stale-writer rejection |
| Restored database copy | target-only | checkpoint CAS, rollback detection and explicit recovery ceremony |

The fixed HeptaBao provider remains qualified only for exact KV-v2 reads.
Generic dynamic issue, renew and revoke remain fail-closed.
""",
        encoding="utf-8",
    )


def main() -> int:
    box_product_errors()
    materialize_manifest()
    materialize_documents()
    print("materialized reviewable secrets.heptabao source candidate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
