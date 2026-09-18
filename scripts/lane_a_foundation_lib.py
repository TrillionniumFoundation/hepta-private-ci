"""Lane A matrix, receipt and self-test helpers."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from lane_a_foundation_core import *  # noqa: F403

OPS_CAPABILITY_MAP_PATH = (
    ROOT / "docs/lane-a-foundation/kernel.operations/CAPABILITY_EVIDENCE_V2.json"
)
REFERENCE_OPERATIONS_CAPABILITIES = {
    "kernel.operations.bounded-state-model.v1",
    "kernel.operations.bounded-outbox-model.v1",
    "kernel.operations.fenced-terminal-model.v1",
}
REFERENCE_OPERATIONS_SUMMARY = (
    "deterministic in-memory reference oracle retained for transition parity"
)


def _validate_capability_row(
    owner: str,
    row: dict[str, Any],
    state: dict[str, Any],
    root: Path,
    *,
    require_module_state: bool,
) -> None:
    capability_id = row.get("capabilityId")
    summary = row.get("summary")
    if not isinstance(capability_id, str) or not capability_id:
        raise VerificationError(f"{owner}: invalid capability ID")
    if not isinstance(summary, str) or not summary:
        raise VerificationError(f"{capability_id}: invalid summary")
    if require_module_state:
        if (
            row.get("durability") != state["durability"]
            or row.get("activation") != state["activation"]
        ):
            raise VerificationError(f"{capability_id}: matrix state mismatch")
    elif (
        row.get("durability") != "not_implemented"
        or row.get("activation") != "inactive"
    ):
        raise VerificationError(f"{capability_id}: reference capability state drift")
    if row.get("productionCaller") is not None:
        raise VerificationError(f"{capability_id}: unproven production caller")
    if row.get("receiptStatus") != "native_workflow_required":
        raise VerificationError(f"{capability_id}: invalid receipt status")
    symbols = row.get("publicSymbols")
    if (
        not isinstance(symbols, list)
        or not symbols
        or not all(isinstance(value, str) and value for value in symbols)
    ):
        raise VerificationError(f"{capability_id}: public symbols required")
    for field in ("sourceEvidence", "positiveTests", "negativeTests"):
        anchors = row.get(field)
        if not isinstance(anchors, list) or not anchors:
            raise VerificationError(f"{capability_id}: {field} required")
        for anchor in anchors:
            validate_anchor(f"{capability_id}/{field}", anchor, root)


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
    extension = read_json(root / OPS_CAPABILITY_MAP_PATH.relative_to(ROOT))
    extension_entries = extension.get("entries")
    if (
        extension.get("schemaVersion") != 1
        or extension.get("module") != "kernel.operations"
        or extension.get("role") != "durable_current_capability_extension"
        or not isinstance(extension_entries, list)
        or extension.get("entryCount") != len(extension_entries)
        or not extension_entries
    ):
        raise VerificationError("kernel.operations capability extension mismatch")

    by_name = {row["module"]: row for row in matrix["modules"]}
    base_by_module: dict[str, list[dict[str, Any]]] = {
        module: [] for module in EXPECTED_MODULES
    }
    ids: set[str] = set()
    for row in entries:
        if not isinstance(row, dict):
            raise VerificationError("capability evidence row must be an object")
        module = row.get("module")
        if module not in base_by_module:
            raise VerificationError(f"{row.get('capabilityId')}: invalid module")
        capability_id = row.get("capabilityId")
        if not isinstance(capability_id, str) or capability_id in ids:
            raise VerificationError(f"invalid/duplicate capability ID {capability_id!r}")
        ids.add(capability_id)
        base_by_module[module].append(row)

    durable_operations: list[dict[str, Any]] = []
    for row in extension_entries:
        if not isinstance(row, dict):
            raise VerificationError("kernel.operations extension row must be an object")
        capability_id = row.get("capabilityId")
        if not isinstance(capability_id, str) or capability_id in ids:
            raise VerificationError(f"invalid/duplicate capability ID {capability_id!r}")
        ids.add(capability_id)
        durable_operations.append(row)

    expected = [
        (module["module"], capability)
        for module in matrix["modules"]
        for capability in module["currentCapabilities"]
    ]
    observed: list[tuple[str, str]] = []
    for module in EXPECTED_MODULES:
        state = by_name[module]["states"]
        if module == "kernel.operations":
            for row in durable_operations:
                _validate_capability_row(module, row, state, root, require_module_state=True)
                observed.append((module, row["summary"]))
            reference_rows = base_by_module[module]
            if {row.get("capabilityId") for row in reference_rows} != REFERENCE_OPERATIONS_CAPABILITIES:
                raise VerificationError("kernel.operations reference capability set drift")
            for row in reference_rows:
                _validate_capability_row(
                    module, row, state, root, require_module_state=False
                )
            observed.append((module, REFERENCE_OPERATIONS_SUMMARY))
            continue
        for row in base_by_module[module]:
            _validate_capability_row(module, row, state, root, require_module_state=True)
            observed.append((module, row["summary"]))
    if observed != expected:
        raise VerificationError(
            "capability maps do not exactly cover ordered current capabilities"
        )


def validate_source_specific(root: Path = ROOT) -> None:
    required = {
        "codex-rs/hepta-types/src/lib.rs": ["pub use identity::IdentityError;"],
        "codex-rs/hepta-wire/src/envelope.rs": ["const WIRE_VERSION: u16 = 1;"],
        "codex-rs/hepta-operations/src/lib.rs": [
            "pub use durable_store::DurableOperationStore;",
            "pub use dispatcher::DurableDispatcher;",
            "pub use destination_dedupe::DestinationDedupeStore;",
            "pub use model::ReferenceAuthorityWitness;",
        ],
        "codex-rs/hepta-operations/src/durable_store.rs": [
            "pub struct DurableOperationStore",
            'begin_with("BEGIN IMMEDIATE")',
            "pub async fn authorize_dispatch(",
            "pub async fn observe_terminal(",
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


def validate_matrix(matrix: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    if (
        matrix.get("schemaVersion") != 2
        or matrix.get("lane") != "LANE-A-FOUNDATION"
        or matrix.get("documentationPolicy")
        != "docs/lane-a-foundation/BOUNDARY_POLICY.md"
        or matrix.get("capabilityEvidenceMap")
        != "docs/lane-a-foundation/CAPABILITY_EVIDENCE_MAP.json"
        or matrix.get("nativeBindingOverride")
        != "qualification/module-execution-dossiers/NATIVE_BINDINGS_LANE_A.json"
        or matrix.get("moduleCoverage") != 7
        or matrix.get("statusAxes") != AXES
    ):
        raise VerificationError("truth-matrix header mismatch")
    expected_closure = {
        "repositoryControlledDocumentationGaps": "closed",
        "currentImplementationTruth": "source_and_test_anchored",
        "automatedDriftGate": "closed",
        "nativeQualification": "workflow_required",
        "targetArchitectureImplementation": "partial",
        "productionActivation": "not_claimed",
        "externalAcceptance": "not_claimed",
    }
    if matrix.get("closure") != expected_closure:
        raise VerificationError("truth-matrix closure overclaims or drifts")
    policy = read_text(root / "docs/lane-a-foundation/BOUNDARY_POLICY.md")
    for phrase in (
        "Current executable contract",
        "Target architecture",
        "Executed evidence",
        "Forbidden implications",
        "Capability traceability rule",
    ):
        if phrase not in policy:
            raise VerificationError(f"boundary policy missing {phrase!r}")
    modules = matrix.get("modules")
    if (
        not isinstance(modules, list)
        or [row.get("module") for row in modules if isinstance(row, dict)]
        != EXPECTED_MODULES
    ):
        raise VerificationError("closed-world module order mismatch")
    for row in modules:
        module = row["module"]
        states = row.get("states")
        if (
            not isinstance(states, dict)
            or list(states) != AXES
            or states["source"] != "implemented"
            or states["acceptance"] != "not_granted"
            or row.get("formalGuideRole") != "target_architecture"
            or row.get("currentSpecificationRole") != "current_executable_contract"
        ):
            raise VerificationError(f"{module}: role/state mismatch")
        for field in ("formalGuide", "currentSpecification", "implementationDetail"):
            if not isinstance(row.get(field), str) or not (root / row[field]).is_file():
                raise VerificationError(f"{module}: missing {field}")
        current = read_text(root / row["currentSpecification"])
        positions = [current.find(heading) for heading in SECTIONS]
        if -1 in positions or positions != sorted(positions):
            raise VerificationError(
                f"{module}: current-contract sections missing/out of order"
            )
        current_caps = row.get("currentCapabilities")
        target_caps = row.get("targetOnlyCapabilities")
        if (
            not isinstance(current_caps, list)
            or not current_caps
            or not isinstance(target_caps, list)
            or set(current_caps) & set(target_caps)
        ):
            raise VerificationError(f"{module}: capability boundary mismatch")
        anchors = row.get("sourceAnchors")
        if not isinstance(anchors, list) or not anchors:
            raise VerificationError(f"{module}: source anchors required")
        for anchor in anchors:
            validate_anchor(module, anchor, root)
    by_name = {row["module"]: row for row in modules}
    exact = {
        (
            "kernel.operations",
            "implementation",
        ): "sqlite_durable_operations_with_reference_oracle",
        (
            "kernel.operations",
            "durability",
        ): "sqlite_wal_full_transactional",
        ("auth.authbus", "implementation"): "signed_admission_with_legacy_replay",
        (
            "auth.authbus",
            "durability",
        ): "sqlite_admission_outbox_and_process_local_legacy",
        ("platform.wire", "implementation"): "fixed_v1_codec",
        ("kernel.authority", "implementation"): "final_use_and_authority_lease_owner",
        ("kernel.evidence", "durability"): "sqlite_migrations_0001_0010",
        ("secrets.heptabao", "implementation"): "bounded_kv_v2_reader_with_registered_final_use_host",
    }
    for (module, axis), value in exact.items():
        if by_name[module]["states"][axis] != value:
            raise VerificationError(f"{module}: {axis} drift")
    capability = read_json(root / "docs/lane-a-foundation/CAPABILITY_EVIDENCE_MAP.json")
    validate_capability_map(matrix, capability, root)
    native = validate_native_bindings(root)
    validate_wire_vector(root)
    validate_source_specific(root)
    return native["currentSourceBinding"]


def git_value(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise VerificationError(f"git {' '.join(args)} failed: {error}") from error
    return result.stdout.strip()


def command_value(*args: str) -> str:
    try:
        result = subprocess.run(
            args,
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise VerificationError(f"{' '.join(args)} failed: {error}") from error
    return result.stdout.strip()


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def exact_source(expected: str | None) -> tuple[str, str]:
    source = git_value("rev-parse", "HEAD")
    if expected is not None and source != expected:
        raise VerificationError(
            f"exact source mismatch: expected {expected}, got {source}"
        )
    return source, git_value("rev-parse", "HEAD^{tree}")


def write_receipt(output: Path, expected: str | None, native: bool) -> None:
    matrix = read_json(MATRIX_PATH)
    binding = validate_matrix(matrix)
    source, tree = exact_source(expected)
    if (source, tree) != (binding["sourceSha"], binding["sourceTree"]):
        raise VerificationError("checkout changed while producing source receipt")
    if native:
        receipt: dict[str, Any] = {
            "schemaVersion": 1,
            "lane": "LANE-A-FOUNDATION",
            "receiptClass": "native-qualification",
            "sourceSha": source,
            "sourceTree": tree,
            "packages": PACKAGES,
            "cargoVersion": command_value("cargo", "--version"),
            "rustcVersion": command_value("rustc", "--version"),
            "status": "passed_in_current_job",
            "githubRunId": os.environ.get("GITHUB_RUN_ID"),
            "githubRunAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "productionActivation": "not_claimed",
            "externalAcceptance": "not_claimed",
        }
    else:
        capabilities = read_json(CAPABILITY_MAP_PATH)
        operations_capabilities = read_json(OPS_CAPABILITY_MAP_PATH)
        bindings = read_json(NATIVE_BINDINGS_PATH)
        receipt = {
            "schemaVersion": 2,
            "lane": "LANE-A-FOUNDATION",
            "receiptClass": "source-truth",
            "sourceSha": source,
            "sourceTree": tree,
            "matrixSha256": hashlib.sha256(canonical(matrix)).hexdigest(),
            "capabilityMapSha256": hashlib.sha256(canonical(capabilities)).hexdigest(),
            "kernelOperationsCapabilityExtensionSha256": hashlib.sha256(
                canonical(operations_capabilities)
            ).hexdigest(),
            "nativeBindingsSha256": hashlib.sha256(canonical(bindings)).hexdigest(),
            "boundaryPolicySha256": hashlib.sha256(
                BOUNDARY_POLICY_PATH.read_bytes()
            ).hexdigest(),
            "currentSpecificationSha256": {
                row["module"]: hashlib.sha256(
                    (ROOT / row["currentSpecification"]).read_bytes()
                ).hexdigest()
                for row in matrix["modules"]
            },
            "moduleCoverage": 7,
            "capabilityCoverage": capabilities["entryCount"]
            + operations_capabilities["entryCount"],
            "repositoryControlledDocumentationGaps": "closed",
            "currentImplementationTruth": "source_and_test_anchored",
            "nativeQualification": "separate_exact_candidate_receipt_required",
            "targetArchitectureImplementation": "partial",
            "productionActivation": "not_claimed",
            "externalAcceptance": "not_claimed",
        }
    receipt["nativeSourceObservations"] = binding["observations"]
    receipt["nativeSourceObservationSha256"] = hashlib.sha256(
        canonical(binding)
    ).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_source_receipt(output: Path, expected: str | None) -> None:
    write_receipt(output, expected, native=False)


def self_test() -> None:
    matrix = read_json(MATRIX_PATH)
    validate_matrix(matrix)
    for mutation in (
        lambda value: value["modules"][3]["states"].__setitem__(
            "durability", "not_implemented"
        ),
        lambda value: value["closure"].__setitem__("externalAcceptance", "closed"),
    ):
        invalid = deepcopy(matrix)
        mutation(invalid)
        try:
            validate_matrix(invalid)
        except VerificationError:
            pass
        else:
            raise VerificationError("self-test accepted a matrix overclaim")
    capability = read_json(CAPABILITY_MAP_PATH)
    for mutation in (
        lambda value: value["entries"].pop(),
        lambda value: value["entries"][0].__setitem__("productionCaller", "unproven"),
    ):
        invalid = deepcopy(capability)
        mutation(invalid)
        try:
            validate_capability_map(matrix, invalid)
        except VerificationError:
            pass
        else:
            raise VerificationError("self-test accepted invalid capability evidence")
