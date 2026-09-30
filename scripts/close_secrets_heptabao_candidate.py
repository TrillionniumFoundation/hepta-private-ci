#!/usr/bin/env python3
'''Materialize the reviewable secrets.heptabao source candidate.

This is a development-time materializer. It may update source and documentation,
but it never runs qualification and is never invoked by a read-only qualifier.
The resulting commit is the only object eligible for exact-source review.
'''
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old in text:
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
        return
    if new in text:
        return
    words = old.split()
    pattern = re.compile(r"\s+".join(re.escape(word) for word in words))
    match = pattern.search(text)
    if match is None:
        raise SystemExit(
            f"materialization anchor missing in {path}: {old[:100]!r}"
        )
    target.write_text(
        text[: match.start()] + new + text[match.end() :],
        encoding="utf-8",
    )


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


def materialize_boxed_errors() -> None:
    constructor = re.compile(
        r"BaoProductHostError::(OutcomePending|TerminalFailure)"
        r"\((?!Box::new\()([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\)"
    )
    for path in (
        "codex-rs/hepta-bao-adapter/src/final_use_host.rs",
        "codex-rs/hepta-bao-adapter/src/sqlite_product_runtime.rs",
    ):
        target = ROOT / path
        text = target.read_text(encoding="utf-8")
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
        target.write_text(text, encoding="utf-8")


def materialize_manifest() -> None:
    path = ROOT / "docs/modules/secrets.heptabao/MODULE_MANIFEST_V1.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))

    manifest.setdefault("documents", {}).update(
        {
            "productionReadiness": "docs/modules/secrets.heptabao/PRODUCTION_READINESS.md",
            "readinessPolicy": "docs/modules/secrets.heptabao/READINESS_POLICY_V1.json",
        }
    )
    manifest["buildSurface"] = {
        "kind": "single_complete",
        "cargoFeatures": [],
        "statement": (
            "The adapter is one complete build surface. Qualification must not "
            "pass undeclared synthetic feature names."
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
                "SQLite product-runtime source with an atomic forward execution "
                "lease, bounded recovery claims and secret-free metrics"
            ),
            (
                "schema-4 JSON reference-owner import into the SQLite owner with "
                "an immutable import receipt"
            ),
        ],
    )
    target_only = [
        item
        for item in manifest.get("targetOnlyCapabilities", [])
        if not item.startswith("transactional SQLite production owner")
        and not item.startswith("bounded fair recovery worker")
    ]
    manifest["targetOnlyCapabilities"] = append_unique(
        target_only,
        [
            "exact-head and deterministic-merge qualification of the SQLite owner/runtime source",
            "selected Agentd or App Server production bootstrap",
            "independently operated trusted-time settlement and key-rotation services",
            "external anti-rollback checkpoint service and disaster-recovery ceremony",
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
                "The qualification workflows are read-only and never materialize, "
                "commit or push source."
            ),
            (
                "The adapter intentionally has one complete Cargo build surface; "
                "undeclared feature names are not a product boundary."
            ),
        ],
    )

    operations = manifest.setdefault("operations", [])
    sqlite_operations = [
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
    ]
    for row in sqlite_operations:
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
    identity["binding"] = "external_read_only_ci_attestation"
    identity["identityRule"] = (
        "candidateSha == testedSha == documentedSha == artifactSourceSha == qualificationSha"
    )
    identity["requiredFields"] = [
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
    ]
    identity["selfReferentialCommitInDocument"] = False

    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def materialize_documents() -> None:
    replace_once(
        "docs/modules/secrets.heptabao/TECHNICAL.md",
        (
            "These contracts\nsupersede older metadata-only lifecycle descriptions where they differ.\n"
            "Provider-native dynamic lease dispatch and normal daemon activation remain\n"
            "unqualified."
        ),
        (
            "These contracts supersede older metadata-only lifecycle descriptions where\n"
            "they differ. The source candidate also contains `SqliteBaoOwnerV1` and\n"
            "`SqliteBaoProductRuntimeV1`; those symbols are source-present but remain\n"
            "unqualified and not product-composed. Provider-native dynamic lease dispatch\n"
            "and normal daemon activation remain unqualified."
        ),
    )
    replace_once(
        "docs/modules/secrets.heptabao/TECHNICAL.md",
        (
            "A production replacement must preserve deduplication, immutable results, "
            "compare-and-swap transitions, recovery fairness, archive semantics and "
            "external anti-rollback. It must also remove synchronous snapshot work from "
            "async runtime workers. Merely changing the container format to SQLite is "
            "insufficient."
        ),
        (
            "The source candidate now includes a transactional SQLite owner and async\n"
            "product-runtime surface with revision CAS, append-only transitions, bounded\n"
            "recovery claims, terminal archival and checkpoint hashing. Source presence is\n"
            "not storage-profile qualification: exact-head and deterministic-merge native\n"
            "execution, a selected product caller, external checkpoint operation and\n"
            "target-host power-loss evidence remain required."
        ),
    )
    replace_once(
        "docs/modules/secrets.heptabao/CONSUMPTION_SAGA_V4.md",
        (
            "A production SQLite replacement is still pending in this source candidate.\n"
            "Staged, truncated or partially recovered patches are not an executable owner.\n"
            "Migration, independently retained anti-rollback state, bounded archival,\n"
            "nonblocking writer integration and target-host power-loss qualification remain\n"
            "open."
        ),
        (
            "The source candidate contains `SqliteBaoOwnerV1` and\n"
            "`SqliteBaoProductRuntimeV1`, including schema-4 import, revision CAS,\n"
            "generation-fenced recovery claims, terminal archival and checkpoint hashing.\n"
            "Those sources are not yet exact-head/storage-profile qualified and no normal\n"
            "product process composes them. Independently retained anti-rollback state,\n"
            "archive offload and target-host power-loss qualification remain open."
        ),
    )
    replace_once(
        "docs/modules/secrets.heptabao/LEASE_OWNER_V3.md",
        (
            "This is the current implementation contract for PR #998 on\n"
            "`codex/secrets-heptabao-convergence`. It complements `TECHNICAL.md` and does not\n"
            "activate a daemon, certify an external provider, or grant release authority."
        ),
        (
            "This is the current durable-owner contract for the canonical\n"
            "`secrets.heptabao` candidate. It complements `TECHNICAL.md` and does not\n"
            "activate a daemon, certify an external provider, or grant release authority."
        ),
    )
    replace_once(
        "docs/modules/secrets.heptabao/LEASE_OWNER_V3.md",
        (
            "`DurableLeaseRegistryV1` remains the single metadata writer. The historical type\n"
            "and document names are retained for source compatibility; its current persistent\n"
            "document is schema 4.\n"
            "It owns lease records, lease operation history and secret-consumption operation\n"
            "history. It never contains a provider token or secret value."
        ),
        (
            "`DurableLeaseRegistryV1` is the bounded schema-4 JSON reference owner and\n"
            "migration oracle. `SqliteBaoOwnerV1` is the transactional SQLite owner source;\n"
            "`SqliteBaoProductRuntimeV1` is its forward/recovery runtime source. Neither\n"
            "profile contains a provider token or secret value. The SQLite profile is\n"
            "source-present but remains exact-head, storage-profile and product-composition\n"
            "unqualified."
        ),
    )
    replace_once(
        "docs/modules/secrets.heptabao/LEASE_OWNER_V3.md",
        (
            "The Bao metadata owner in this document remains the JSON reference owner; an "
            "AuthBus SQLite dependency is not a Bao production writer.\n"
            "The Python qualification tests prove exit propagation and receipt binding only;\n"
            "they must not be counted as Rust/provider execution."
        ),
        (
            "The JSON profile remains the reference/migration oracle. The same candidate now\n"
            "contains a Bao-owned SQLite writer and runtime, but source presence is not\n"
            "product composition or production qualification. The Python qualification\n"
            "tests prove exit propagation and receipt binding only; they must not be counted\n"
            "as Rust/provider execution."
        ),
    )
    replace_once(
        "docs/modules/secrets.heptabao/OPERATIONS_AND_CAPACITY_V1.md",
        (
            "A production SQLite owner remains target-only. Merely storing one JSON blob in a\n"
            "SQLite row does not satisfy this gate. A replacement must preserve:"
        ),
        (
            "A transactional SQLite owner and product-runtime source now exist in this\n"
            "candidate. They do not satisfy this gate by source presence alone. Exact-head,\n"
            "deterministic-merge and selected-host qualification must prove that the source\n"
            "preserves:"
        ),
    )
    replace_once(
        "docs/modules/secrets.heptabao/OPERATIONS_AND_CAPACITY_V1.md",
        (
            "The repository's truncated phase-three staging payload is not executable source\n"
            "and must not be applied or cited as completion. Until a complete implementation\n"
            "passes the gates above, production-writer and activation claims remain false."
        ),
        (
            "The committed SQLite owner/runtime is the executable candidate; historical\n"
            "truncated staging payloads remain non-evidence. Until the exact candidate passes\n"
            "the gates above and a named product caller is composed, production-writer,\n"
            "activation and release claims remain false."
        ),
    )
    replace_once(
        "codex-rs/hepta-bao-adapter/README.md",
        (
            "The operation and production-store gates are specified in\n"
            "`docs/modules/secrets.heptabao/OPERATIONS_AND_CAPACITY_V1.md`. A production SQLite\n"
            "owner is still target-only: no truncated staging payload or SQLite-wrapped JSON\n"
            "blob is treated as implementation. Production activation remains false until a\n"
            "complete transactional owner, external monotonic checkpoint, target-host\n"
            "qualification and nonblocking host integration exist."
        ),
        (
            "The operation and production-store gates are specified in\n"
            "`docs/modules/secrets.heptabao/OPERATIONS_AND_CAPACITY_V1.md`. The source candidate\n"
            "contains a transactional SQLite owner and `SqliteBaoProductRuntimeV1`; they are\n"
            "not yet exact-head/storage-profile qualified or composed by a normal product\n"
            "binary. Production activation remains false until external monotonic checkpoint\n"
            "operation, target-host qualification and a named caller exist."
        ),
    )

    current = ROOT / "docs/lane-a-foundation/secrets.heptabao/CURRENT_IMPLEMENTATION.md"
    text = current.read_text(encoding="utf-8")
    marker = "## Target-only design\n"
    section = (
        "## SQLite source candidate\n\n"
        "`SqliteBaoOwnerV1` and `SqliteBaoProductRuntimeV1` are present in the\n"
        "reviewed source. The owner uses WAL/FULL transactions, revision CAS,\n"
        "append-only transition evidence, bounded generation-fenced recovery claims,\n"
        "terminal archival, schema-4 reference import and checkpoint hashing. The\n"
        "runtime acquires an execution lease in the same transaction as a new claim and\n"
        "performs observer-only recovery without provider redispatch.\n\n"
        "This is a source-presence statement only. Exact-head and deterministic-merge\n"
        "qualification, external checkpoint operation, target-host durability and a\n"
        "named non-test product caller remain false.\n\n"
    )
    if section not in text:
        if marker not in text:
            raise SystemExit("CURRENT_IMPLEMENTATION target section anchor missing")
        current.write_text(text.replace(marker, section + marker, 1), encoding="utf-8")


def main() -> int:
    materialize_boxed_errors()
    materialize_manifest()
    materialize_documents()
    print("materialized reviewable secrets.heptabao source candidate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
