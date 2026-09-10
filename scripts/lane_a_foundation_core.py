"""Lane A closed-world current-contract verification helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT / "docs/lane-a-foundation"
MATRIX_PATH = LANE / "MODULE_TRUTH_MATRIX.json"
CAPABILITY_MAP_PATH = LANE / "CAPABILITY_EVIDENCE_MAP.json"
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


def _rust_source_files(root: Path) -> list[Path]:
    """Return only first-party Hepta Rust sources used by Lane A contracts."""

    return sorted((root / "codex-rs").glob("hepta-*/src/**/*.rs"))


def _rust_public_item_pattern(symbol: str) -> re.Pattern[str]:
    escaped = re.escape(symbol)
    return re.compile(
        rf"(?mx)"
        rf"^\s*pub(?:\([^)]*\))?\s+"
        rf"(?:async\s+|const\s+|unsafe\s+|extern\s+\"[^\"]+\"\s+)*"
        rf"(?:struct|enum|trait|type|fn|const|static|union|mod)\s+{escaped}\b"
    )


def _rust_impl_blocks(source: str, owner: str) -> list[str]:
    """Extract rustfmt-shaped inherent impl bodies for one concrete owner."""

    escaped = re.escape(owner)
    pattern = re.compile(
        rf"(?ms)^impl(?:\s*<[^{{}}]*>)?\s+{escaped}"
        rf"(?:\s*<[^{{}}]*>)?(?:\s+where\s+[^{{]*)?\s*\{{(.*?)^\}}"
    )
    return [match.group(1) for match in pattern.finditer(source)]


def rust_public_symbol_present(root: Path, symbol: str) -> bool:
    """Prove a capability symbol is a public Rust item or associated member.

    Capability evidence is intentionally stricter than the native observation
    table: test-function observations may be private, while every entry named
    in ``publicSymbols`` must be callable or nameable outside its defining
    module. This check rejects a private implementation key merely because its
    identifier appears in source text.
    """

    files = _rust_source_files(root)
    if "::" not in symbol:
        item_pattern = _rust_public_item_pattern(symbol)
        macro_pattern = re.compile(
            rf"(?m)^\s*monotonic_identity!\(\s*{re.escape(symbol)}\s*\)\s*;"
        )
        return any(
            item_pattern.search(source) or macro_pattern.search(source)
            for source in (read_text(path) for path in files)
        )

    owner, member = symbol.split("::", 1)
    if not owner or not member or "::" in member:
        return False
    if not rust_public_symbol_present(root, owner):
        return False
    member_pattern = re.compile(
        rf"(?mx)^\s*pub(?:\([^)]*\))?\s+"
        rf"(?:(?:async|const|unsafe)\s+)*fn\s+{re.escape(member)}\b"
        rf"|^\s*pub(?:\([^)]*\))?\s+const\s+{re.escape(member)}\b"
    )
    for path in files:
        source = read_text(path)
        if any(
            member_pattern.search(block)
            for block in _rust_impl_blocks(source, owner)
        ):
            return True
    return False


def validate_capability_map(
    matrix: dict[str, Any], value: dict[str, Any], root: Path = ROOT
) -> None:
    entries = value.get("entries")
    if (
        value.get("schemaVersion") != 1
        or value.get("lane") != "LANE-A-FOUNDATION"
        or value.get("closureScope") != "current executable capabilities only"
        or not isinstance(entries, list)
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
        if row.get("productionCaller") is not None:
            raise VerificationError(f"{capability_id}: unproven production caller")
        if row.get("receiptStatus") != "native_workflow_required":
            raise VerificationError(f"{capability_id}: invalid receipt status")
        symbols = row.get("publicSymbols")
        if (
            not isinstance(symbols, list)
            or not symbols
            or not all(isinstance(x, str) and x for x in symbols)
        ):
            raise VerificationError(f"{capability_id}: public symbols required")
        for symbol in symbols:
            if not rust_public_symbol_present(root, symbol):
                raise VerificationError(
                    f"{capability_id}: {symbol!r} is not a public Rust API symbol"
                )
        for field in ("sourceEvidence", "positiveTests", "negativeTests"):
            anchors = row.get(field)
            if not isinstance(anchors, list) or not anchors:
                raise VerificationError(f"{capability_id}: {field} required")
            for anchor in anchors:
                validate_anchor(f"{capability_id}/{field}", anchor, root)
    if observed != expected:
        raise VerificationError(
            "capability map does not exactly cover ordered current capabilities"
        )


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
        or value.get("candidateBinding")
        != "exact_head_tree_receipt_plus_current_blob_table"
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
    for row in rows:
        path = row.get("path")
        expected = str(row.get("blobSha"))
        symbols = row.get("exports")
        if (
            not isinstance(path, str)
            or re.fullmatch(r"[0-9a-f]{40}", expected) is None
            or not isinstance(symbols, list)
            or not symbols
        ):
            raise VerificationError(f"{row.get('module')}: invalid native-binding row")
        try:
            data = (root / path).read_bytes()
            source = data.decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise VerificationError(
                f"cannot read native binding {path}: {error}"
            ) from error
        if git_blob_sha(data) != expected:
            raise VerificationError(f"{row['module']}: source blob drift for {path}")
        for symbol in symbols:
            if (
                not isinstance(symbol, str)
                or re.search(r"\b" + re.escape(symbol) + r"\b", source) is None
            ):
                raise VerificationError(
                    f"{row['module']}: missing {symbol!r} in {path}"
                )
    return value


def validate_wire_vector(root: Path = ROOT) -> None:
    value = read_json(
        root / "docs/lane-a-foundation/platform.wire/HPTA_V1_CONFORMANCE.json"
    )
    try:
        frame = bytes.fromhex(value["frameHex"])
        payload = bytes.fromhex(value["fields"]["payloadHex"])
        payload_digest = value["fields"]["payloadSha256"]
    except (KeyError, TypeError, ValueError) as error:
        raise VerificationError(f"invalid HPTA V1 vector: {error}") from error
    if (
        value.get("schemaVersion") != 1
        or value.get("protocol") != "HPTA"
        or value.get("version") != 1
        or value.get("frameLength") != 59
        or len(frame) != 59
        or frame[:6] != b"HPTA\x00\x01"
        or hashlib.sha256(frame).hexdigest() != value.get("frameSha256")
        or hashlib.sha256(payload).hexdigest() != payload_digest
    ):
        raise VerificationError("HPTA V1 conformance vector mismatch")


def validate_source_specific(root: Path = ROOT) -> None:
    required = {
        "codex-rs/hepta-types/src/lib.rs": ["pub use identity::IdentityError;"],
        "codex-rs/hepta-wire/src/envelope.rs": ["const WIRE_VERSION: u16 = 1;"],
        "codex-rs/hepta-operations/src/lib.rs": [
            "In-memory reference model",
            "does not provide durable storage",
        ],
        "codex-rs/hepta-operations/src/model.rs": [
            "pub struct ReferenceAuthorityWitness",
            "not a cryptographic credential",
        ],
        "codex-rs/hepta-operations/src/ledger.rs": [
            "MAX_MODEL_OPERATION_RECORDS",
            'InvalidDigest("dispatch")',
            "terminal_matches",
        ],
        "codex-rs/hepta-operations/src/outbox.rs": [
            "MAX_MODEL_OUTBOX_RECORDS",
            'InvalidDigest("outbox payload")',
            'InvalidDigest("outbox acknowledgement")',
        ],
        "codex-rs/hepta-authbus/src/lib.rs": [
            "does not verify a signature",
            "pub struct PreverifiedAuthEnvelope",
            "pub struct TrustedReplayContext",
            "BTreeMap<ReplayKey, u64>",
            "AuthorityPosture::DENY_ALL",
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
        value in auth
        for value in ("pub fn reserve(", "pub fn settle(", "verify_strict(")
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
