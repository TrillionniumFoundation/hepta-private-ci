"""Lane A closed-world current-contract verification helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "qualification/module-execution-dossiers"))
from native_source_bindings import BindingError, observe_native_bindings

LANE = ROOT / "docs/lane-a-foundation"
MATRIX_PATH = LANE / "MODULE_TRUTH_MATRIX.json"
CAPABILITY_MAP_PATH = LANE / "CAPABILITY_EVIDENCE_MAP.json"
OPS_CAPABILITY_MAP_PATH = LANE / "kernel.operations/CAPABILITY_EVIDENCE_V2.json"
PROTOCOL_REGISTRY_PATH = LANE / "PROTOCOL_REGISTRY_V1.json"
BOUNDARY_POLICY_PATH = LANE / "BOUNDARY_POLICY.md"
NATIVE_BINDINGS_PATH = (
    ROOT / "qualification/module-execution-dossiers/NATIVE_BINDINGS_LANE_A.json"
)
EXPECTED_MODULES = [
    "platform.types",
    "platform.wire",
    "kernel.authority",
    "kernel.operations",
    "kernel.evidence",
    "auth.authbus",
    "secrets.heptabao",
]
AXES = [
    "source",
    "implementation",
    "durability",
    "qualification",
    "activation",
    "acceptance",
]
SECTIONS = [
    "## Current executable contract",
    "## Public symbols and source bindings",
    "## Durability and activation",
    "## Target-only design",
    "## Known limits and non-claims",
    "## Verification",
    "## Integration prerequisites",
]
MIGRATIONS = [
    "0001_governance.sql",
    "0002_provider_evidence.sql",
    "0003_provider_host_binding.sql",
    "0004_memory_mutation_shadow.sql",
    "0005_channel_ingress_evidence.sql",
    "0006_provider_ephemeral_input.sql",
    "0007_provider_effect_evidence.sql",
    "0008_provider_effect_ack_source.sql",
    "0009_authbus_replay.sql",
    "0010_authbus_outbox.sql",
    "0011_qualification_evidence.sql",
    "0012_authbus_recovery.sql",
]
PACKAGES = [
    "codex-hepta-types",
    "codex-hepta-wire",
    "codex-hepta-contracts",
    "codex-hepta-operations",
    "codex-hepta-evidence",
    "codex-hepta-authbus",
    "codex-hepta-bao-adapter",
]
OPERATIONS_PRODUCT_SOURCES = {
    "kernel.operations.bounded-state-model.v1": "codex-rs/hepta-operations/src/ledger.rs",
    "kernel.operations.bounded-outbox-model.v1": "codex-rs/hepta-operations/src/outbox.rs",
    "kernel.operations.fenced-terminal-model.v1": "codex-rs/hepta-operations/src/ledger.rs",
    "kernel.operations.durable-owner.v1": "codex-rs/hepta-memory/src/production_writer.rs",
    "kernel.operations.durable-claim-lease.v1": "codex-rs/hepta-memory/src/operation_claims.rs",
    "kernel.operations.final-use-cas-reconcile.v1": "codex-rs/hepta-memory/src/production_cognitive_source_target.rs",
    "kernel.operations.agentd-daemon-composition.v1": "codex-rs/hepta-agentd/src/runtime.rs",
}
OPS_SOURCE_CAPABILITIES = {
    "kernel.operations.atomic-durable-ledger-outbox.v1": "atomic durable operation ledger and source outbox co-commit",
    "kernel.operations.leased-fenced-outbox.v1": "bounded leased outbox claims with generation fencing and crash-reopen takeover",
    "kernel.operations.final-use-reconciliation.v1": "final-use authority dispatch admission with indeterminate recovery and terminal reconciliation",
    "kernel.operations.destination-transaction-dedupe.v1": "destination-owner transaction dedupe primitive with immutable apply receipts",
    "kernel.operations.retention-observability.v1": "bounded retention tombstones and backlog metrics",
}
PROTOCOL_IDENTITIES = [
    ("platform.types", "hepta.platform.types.primitives.v1"),
    ("platform.wire", "hepta.platform.wire.versioned-envelope.v2"),
    ("kernel.authority", "hepta.kernel.authority.final-use.v1"),
    ("kernel.operations", "hepta.kernel.operations.durable-ledger-outbox.v1"),
    ("kernel.operations", "hepta.kernel.operations.durable-owner.v1"),
    ("kernel.evidence", "hepta.kernel.evidence.sqlite-lineage.v1"),
    ("auth.authbus", "hepta.authbus.signed-message.v1"),
    ("secrets.heptabao", "hepta.secrets.heptabao.kv-v2-read.v1"),
]


class VerificationError(RuntimeError):
    """Repository truth and a Lane A claim diverged."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise VerificationError(f"JSON object required: {path}")
    return value


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise VerificationError(f"cannot read UTF-8 {path}: {error}") from error


def validate_anchor(owner: str, item: Any, root: Path = ROOT) -> None:
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        raise VerificationError(f"{owner}: invalid source/test anchor")
    source = read_text(root / item["path"])
    for field, required in (("mustContain", True), ("mustNotContain", False)):
        needles = item.get(field, [])
        if not isinstance(needles, list) or not all(
            isinstance(x, str) and x for x in needles
        ):
            raise VerificationError(f"{owner}: invalid {field}")
        for needle in needles:
            if (needle in source) != required:
                state = "missing" if required else "forbidden"
                raise VerificationError(
                    f"{owner}: {state} {needle!r} in {item['path']}"
                )


def validate_capability_map(
    matrix: dict[str, Any], value: dict[str, Any], root: Path = ROOT
) -> None:
    entries = value.get("entries")
    if (
        value.get("schemaVersion") != 1
        or value.get("lane") != "LANE-A-FOUNDATION"
        or value.get("closureScope") != "current executable capabilities only"
        or value.get("coverageScope") != "product_current_capabilities"
        or not isinstance(entries, list)
        or value.get("entryCount") != 42
        or value.get("entryCount") != len(entries)
    ):
        raise VerificationError("capability evidence-map header mismatch")
    expected = [
        (module["module"], capability)
        for module in matrix["modules"]
        for capability in module["currentCapabilities"]
    ]
    by_module = {row["module"]: row for row in matrix["modules"]}
    observed: list[tuple[str, str]] = []
    ids: set[str] = set()
    for row in entries:
        if not isinstance(row, dict):
            raise VerificationError("capability evidence row must be an object")
        capability_id = row.get("capabilityId")
        module = row.get("module")
        summary = row.get("summary")
        if (
            not isinstance(capability_id, str)
            or not capability_id
            or capability_id in ids
        ):
            raise VerificationError(
                f"invalid/duplicate capability ID {capability_id!r}"
            )
        ids.add(capability_id)
        if module not in by_module or not isinstance(summary, str) or not summary:
            raise VerificationError(f"{capability_id}: invalid module or summary")
        observed.append((module, summary))
        state = by_module[module]["states"]
        if (
            row.get("durability") != state["durability"]
            or row.get("activation") != state["activation"]
        ):
            raise VerificationError(f"{capability_id}: matrix state mismatch")
        production_caller = row.get("productionCaller")
        allowed_callers = by_module[module].get("namedProductCallers", [])
        if production_caller is not None and production_caller not in allowed_callers:
            raise VerificationError(
                f"{capability_id}: unregistered production caller {production_caller!r}"
            )
        caller = row.get("productionCaller")
        if caller is not None:
            if not isinstance(caller, str) or not caller:
                raise VerificationError(f"{capability_id}: invalid production caller")
            caller_evidence = row.get("callerEvidence")
            if not isinstance(caller_evidence, list) or not caller_evidence:
                raise VerificationError(
                    f"{capability_id}: production caller requires callerEvidence"
                )
            for anchor in caller_evidence:
                validate_anchor(f"{capability_id}/callerEvidence", anchor, root)
        if row.get("receiptStatus") != "native_workflow_required":
            raise VerificationError(f"{capability_id}: invalid receipt status")
        symbols = row.get("publicSymbols")
        if (
            not isinstance(symbols, list)
            or not symbols
            or not all(isinstance(x, str) and x for x in symbols)
        ):
            raise VerificationError(f"{capability_id}: public symbols required")
        for field in ("sourceEvidence", "positiveTests", "negativeTests"):
            anchors = row.get(field)
            if not isinstance(anchors, list) or not anchors:
                raise VerificationError(f"{capability_id}: {field} required")
            for anchor in anchors:
                validate_anchor(f"{capability_id}/{field}", anchor, root)
        if module == "kernel.operations":
            source = OPERATIONS_PRODUCT_SOURCES.get(capability_id)
            if source is None or not any(
                anchor["path"] == source and anchor.get("mustContain")
                for anchor in row["sourceEvidence"]
            ):
                raise VerificationError(
                    f"{capability_id}: product evidence owner mismatch"
                )
    if observed != expected:
        raise VerificationError(
            "capability map does not exactly cover ordered current capabilities"
        )


def validate_operations_source_evidence(
    value: dict[str, Any], root: Path = ROOT
) -> None:
    """Check the standalone owner without adding it to product coverage."""
    entries = value.get("entries")
    if (
        value.get("schemaVersion") != 1
        or value.get("module") != "kernel.operations"
        or value.get("role") != "standalone_source_evidence"
        or value.get("owner") != "codex-rs/hepta-operations"
        or value.get("productCapabilityCoverageContribution") != 0
        or value.get("productQualification") != "not_granted"
        or value.get("entryCount") != 5
        or not isinstance(entries, list)
        or any(not isinstance(row, dict) for row in entries)
        or [(row.get("capabilityId"), row.get("summary")) for row in entries]
        != list(OPS_SOURCE_CAPABILITIES.items())
    ):
        raise VerificationError(
            "standalone operations evidence scope/ordered coverage mismatch"
        )
    owner = (root / value["owner"]).resolve()
    for row in entries:
        capability_id = row["capabilityId"]
        if (
            row.get("durability") != "sqlite_wal_full_transactional"
            or row.get("activation") != "host_composition_required"
            or row.get("productionCaller") is not None
            or row.get("receiptStatus") != "native_workflow_required"
            or not isinstance(row.get("publicSymbols"), list)
            or not row["publicSymbols"]
            or any(
                not isinstance(symbol, str) or not symbol
                for symbol in row["publicSymbols"]
            )
        ):
            raise VerificationError(f"{capability_id}: standalone owner state mismatch")
        for field in ("sourceEvidence", "positiveTests", "negativeTests"):
            anchors = row.get(field)
            if not isinstance(anchors, list) or not anchors:
                raise VerificationError(f"{capability_id}: {field} required")
            for anchor in anchors:
                validate_anchor(f"{capability_id}/{field}", anchor, root)
                if not (root / anchor["path"]).resolve().is_relative_to(owner):
                    raise VerificationError(
                        f"{capability_id}: standalone evidence owner mismatch"
                    )


def validate_protocol_registry(value: dict[str, Any], root: Path = ROOT) -> None:
    rows = value.get("protocols")
    if (
        value.get("schemaVersion") != 1
        or value.get("lane") != "LANE-A-FOUNDATION"
        or value.get("role") != "current_executable_protocol_index"
        or value.get("authority") != "none"
        or not isinstance(rows, list)
        or any(not isinstance(row, dict) for row in rows)
        or [(row.get("module"), row.get("protocolId")) for row in rows]
        != PROTOCOL_IDENTITIES
    ):
        raise VerificationError("protocol registry ordered identity mismatch")
    for row in rows:
        for field in ("source", "invariants"):
            items = row.get(field)
            if (
                not isinstance(items, list)
                or not items
                or any(not isinstance(item, str) or not item for item in items)
            ):
                raise VerificationError(f"{row['protocolId']}: {field} required")
        if any(not (root / path).exists() for path in row["source"]):
            raise VerificationError(f"{row['protocolId']}: protocol source missing")
    for row, owner, scope, source in (
        (
            rows[3],
            "codex-rs/hepta-operations",
            "standalone_source_evidence",
            "src/durable_store.rs",
        ),
        (
            rows[4],
            "codex-rs/hepta-memory",
            "product_current_contract",
            "src/production_writer.rs",
        ),
    ):
        if (
            row.get("owner") != owner
            or row.get("scope") != scope
            or f"{owner}/{source}" not in row["source"]
        ):
            raise VerificationError(
                f"{row['protocolId']}: protocol owner/scope mismatch"
            )
    if rows[3].get("legacyProtocolId") != "hepta.kernel.operations.reference-model.v1":
        raise VerificationError("standalone operations legacy protocol drift")


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def validate_native_bindings(root: Path = ROOT) -> dict[str, Any]:
    value = read_json(
        root / "qualification/module-execution-dossiers/NATIVE_BINDINGS_LANE_A.json"
    )
    rows = value.get("observations")
    if (
        value.get("schema") != "hepta.native-source-observations.lane-a.v1"
        or value.get("schemaVersion") != 1
        or value.get("lane") != "LANE-A-FOUNDATION"
        or value.get("moduleCoverage") != 7
        or value.get("closedWorldModules") != EXPECTED_MODULES
        or value.get("consumerCallsitesProved") is not False
        or value.get("productExecutionProved") is not False
        or value.get("sourceCodeCommitRole") != "provenance_only_non_authoritative"
        or value.get("candidateBinding") != "runtime_head_tree_and_source_blob_receipt"
        or not isinstance(rows, list)
        or [row.get("module") for row in rows if isinstance(row, dict)]
        != EXPECTED_MODULES
    ):
        raise VerificationError("Lane A native-binding header/module set mismatch")
    source_commit = str(value.get("sourceCodeCommit"))
    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise VerificationError("native-binding provenance commit is not exact")
    observation_digest = hashlib.sha256(
        json.dumps(
            rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    if value.get("sourceObservationDigest") != observation_digest:
        raise VerificationError("native-binding observation digest mismatch")
    try:
        current = observe_native_bindings(root, rows, EXPECTED_MODULES)
    except BindingError as error:
        raise VerificationError(str(error)) from error
    value["currentSourceBinding"] = current
    return value


def validate_wire_vector(root: Path = ROOT) -> None:
    v1 = read_json(
        root / "docs/lane-a-foundation/platform.wire/HPTA_V1_CONFORMANCE.json"
    )
    try:
        v1_frame = bytes.fromhex(v1["frameHex"])
        v1_payload = bytes.fromhex(v1["fields"]["payloadHex"])
        v1_payload_digest = v1["fields"]["payloadSha256"]
    except (KeyError, TypeError, ValueError) as error:
        raise VerificationError(f"invalid HPTA V1 vector: {error}") from error
    if (
        v1.get("schemaVersion") != 1
        or v1.get("protocol") != "HPTA"
        or v1.get("version") != 1
        or v1.get("frameLength") != 59
        or len(v1_frame) != 59
        or v1_frame[:6] != b"HPTA\x00\x01"
        or hashlib.sha256(v1_frame).hexdigest() != v1.get("frameSha256")
        or hashlib.sha256(v1_payload).hexdigest() != v1_payload_digest
    ):
        raise VerificationError("HPTA V1 conformance vector mismatch")

    v2 = read_json(
        root / "docs/lane-a-foundation/platform.wire/HPTA_V2_CONFORMANCE.json"
    )
    try:
        v2_frame = bytes.fromhex(v2["frameHex"])
        v2_digest = v2["fields"]["frameDigestSha256"]
        v2_domain = bytes.fromhex(v2["digestDomainHex"])
    except (KeyError, TypeError, ValueError) as error:
        raise VerificationError(f"invalid HPTA V2 vector: {error}") from error
    if (
        v2.get("schemaVersion") != 1
        or v2.get("protocol") != "HPTA"
        or v2.get("version") != 2
        or v2.get("frameLength") != 59
        or len(v2_frame) != 59
        or v2_frame[:6] != b"HPTA\x00\x02"
        or hashlib.sha256(v2_frame).hexdigest() != v2.get("frameSha256")
    ):
        raise VerificationError("HPTA V2 conformance vector mismatch")
    v2_preimage = v2_domain + v2_frame[:18] + v2_frame[50:54] + v2_frame[54:]
    if hashlib.sha256(v2_preimage).hexdigest() != v2_digest:
        raise VerificationError("HPTA V2 frame-digest vector mismatch")

    hptn = read_json(
        root / "docs/lane-a-foundation/platform.wire/HPTN_V1_CONFORMANCE.json"
    )
    try:
        hello = bytes.fromhex(hptn["recordHex"])
    except (KeyError, TypeError, ValueError) as error:
        raise VerificationError(f"invalid HPTN V1 vector: {error}") from error
    if (
        hptn.get("schemaVersion") != 1
        or hptn.get("protocol") != "HPTN"
        or hptn.get("formatVersion") != 1
        or hptn.get("recordLength") != 20
        or len(hello) != 20
        or hello[:6] != b"HPTN\x00\x01"
        or hashlib.sha256(hello).hexdigest() != hptn.get("recordSha256")
        or hptn.get("wireVersions") != [1, 2]
        or hptn.get("capabilities", {}).get("currentMask") != 7
    ):
        raise VerificationError("HPTN V1 conformance vector mismatch")


def validate_source_specific(root: Path = ROOT) -> None:
    required = {
        "codex-rs/hepta-types/src/lib.rs": ["pub use identity::IdentityError;"],
        "codex-rs/hepta-wire/src/envelope.rs": ["const WIRE_VERSION: u16 = 1;"],
        "codex-rs/hepta-operations/src/lib.rs": [
            "deterministic in-memory reference",
            "pub use durable_store::DurableOperationStore;",
        ],
        "codex-rs/hepta-operations/src/model.rs": [
            "pub struct ReferenceAuthorityWitness",
            "not a cryptographic credential",
        ],
        "codex-rs/hepta-operations/src/ledger.rs": [
            "MAX_MODEL_OPERATION_RECORDS",
            "In-memory deterministic reference model",
            "persistence test.",
            'InvalidDigest("dispatch")',
            "terminal_matches",
        ],
        "codex-rs/hepta-operations/src/outbox.rs": [
            "MAX_MODEL_OUTBOX_RECORDS",
            'InvalidDigest("outbox payload")',
            'InvalidDigest("outbox acknowledgement")',
        ],
        "codex-rs/hepta-authbus/src/lib.rs": [
            "pub use signed::SignedMessage;",
            "pub struct PreverifiedAuthEnvelope",
            "pub struct TrustedReplayContext",
            "BTreeMap<ReplayKey, u64>",
            "AuthorityPosture::DENY_ALL",
        ],
        "codex-rs/hepta-authbus/src/signed.rs": [
            "pub fn authenticate(",
            ".verify_strict(",
            "pub struct AuthenticatedMessage",
        ],
        "codex-rs/hepta-evidence/src/authbus_store.rs": [
            "pub async fn admit_authbus_message(",
            'begin_with("BEGIN IMMEDIATE")',
            "transaction.commit().await",
        ],
    }
    for path, needles in required.items():
        source = read_text(root / path)
        for needle in needles:
            if needle not in source:
                raise VerificationError(
                    f"source-specific check missing {needle!r} in {path}"
                )
    operations = read_text(root / "codex-rs/hepta-operations/src/model.rs")
    auth = read_text(root / "codex-rs/hepta-authbus/src/lib.rs")
    if "pub struct AuthorityWitness" in operations or "pub struct AuthEnvelope" in auth:
        raise VerificationError(
            "production-looking reference boundary was reintroduced"
        )
    envelope = auth[
        auth.index("pub struct PreverifiedAuthEnvelope") : auth.index(
            "pub struct TrustedReplayContext"
        )
    ]
    if "revoked" in envelope or any(
        value in auth for value in ("pub fn reserve(", "pub fn settle(")
    ):
        raise VerificationError(
            "AuthBus promoted an untrusted or target-only capability"
        )
    migrations = sorted(
        path.name
        for path in (root / "codex-rs/hepta-evidence/migrations").glob("*.sql")
    )
    if migrations != MIGRATIONS:
        raise VerificationError(f"evidence migration lineage drift: {migrations!r}")
    bao = read_text(root / "codex-rs/hepta-bao-adapter/src/https_consumer.rs")
    if any(
        value in bao
        for value in ("pub async fn put_", "pub async fn renew", "pub async fn revoke")
    ):
        raise VerificationError(
            "Bao mutation API promoted into current read-only slice"
        )
