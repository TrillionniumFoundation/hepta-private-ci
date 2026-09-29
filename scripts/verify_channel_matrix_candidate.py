#!/usr/bin/env python3
"""Exact Git/source navigation receipt, never native or deployment acceptance.

sourceBase is immutable provenance. An external receipt binds the current
candidate and map bytes; a commit cannot contain its own future Git identity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = "docs/modules/channel.matrix/IMPLEMENTATION_MAP.json"
DOC_ROOT = "docs/modules/channel.matrix"
REQUIRED_DOCS = (
    "ARCHITECTURE.md", "STATE_MACHINE.md", "STORAGE_SCHEMA.md",
    "MATRIX_PROTOCOL.md", "CONFIGURATION.md", "FAILURE_AND_RECOVERY.md",
    "OPERATIONS_RUNBOOK.md", "SECURITY_MODEL.md", "QUALIFICATION_MATRIX.md",
    "FINAL_CONTENT_BOUNDARY_V2.md", "OPTIMIZATION_CONTRACT.md",
)
SOURCE_MARKERS = {
    "codex-rs/hepta-supervisor/src/matrix.rs": ("fn start_matrix_companion(", "spawn_matrixd(&spec)"),
    "codex-rs/hepta-matrixd/src/runner.rs": ("pub async fn run(", "MatrixFinalUseBroker::open(&config.layout)", "run_outbox_sender("),
    "codex-rs/hepta-matrixd/src/final_use.rs": ("HOST_CONFIG_SCHEMA_VERSION: u32 = 1", "BROKER_WIRE_SCHEMA_VERSION: u32 = MATRIX_FINAL_USE_REQUEST_SCHEMA_VERSION", "response.schema_version != BROKER_WIRE_SCHEMA_VERSION"),
    "codex-rs/hepta-matrix-sdk/src/lib.rs": ("mod outbound_v2;", "pub use outbound_v2::run_outbox_sender;", "pub use outbound_v2::MatrixRawSendSeal;"),
    "codex-rs/hepta-matrix-sdk/src/outbound_v2/mod.rs": (
        "claim_outbox_fenced(", "Admission::Entered(entered)",
        "settle_entered(store, &entered", "TelemetryWindow::new()",
        "trait MatrixAuthorizedTransport", "permit.validate(record, &identity)",
        "Ok(self.send(record, MatrixRawSendSeal { _private: () }))"),
    "codex-rs/hepta-matrix-sdk/src/outbound_v2/admission.rs": (
        "prepare_outbox_dispatch(record, prepared_at_ms)", "pin_outbox_content(",
        "record_outbox_authorized(", "record_outbox_dispatching(",
        "refresh_revocations()", "enter_verified_use(token, &request.binding, stats)"),
    "codex-rs/hepta-matrix-sdk/src/outbound_v2/settlement.rs": (
        "entered: &EnteredSend<'_>", "finish_outbox_transport_accepted(",
        "finish_outbox_indeterminate("),
    "codex-rs/hepta-matrix-sdk/src/outbound_v2/gate.rs": (
        "pub(super) async fn enter_verified_use(", "MatrixSendPermit::new(",
        "send_authorized(self.record, permit)", "outbound_payload_digest(self.record)",
        "async fn continue_entered(", ") -> EnteredSend<'claim> {",
        "let mut permit = Some(permit)", "let mut send: Option<MatrixSendFuture<'_>> = None",
        "self.preflight(grant, stats)", "self.require_live_window(grant.expires_at_ms)"),
    "codex-rs/hepta-matrix-sdk/src/outbound_v2/telemetry.rs": (
        "hepta.channel-matrix-runtime-metrics.v1", "post_entry_failures",
        "payload_digest_checks", "dynamic_checks"),
    "codex-rs/hepta-matrix-sdk/src/outbound_v2/permit.rs": ("pub(super) struct MatrixSendPermit", "proof.matches(&self.binding)", "outbound_payload_digest(record)"),
    "codex-rs/hepta-matrix-sdk/src/outbound_v2/retry.rs": ("classified_retry_at(", "stable_jitter_ms(", "MatrixAttemptFailureClass::RateLimited", "MatrixAttemptFailureClass::ResponseLost"),
    "codex-rs/hepta-matrix-sdk/src/authority.rs": ("MATRIX_FINAL_USE_REQUEST_SCHEMA_VERSION: u32 = 2", "pub struct MatrixFinalUseRequest", "pub trait MatrixOutboundAuthorizer", "outbound_payload_digest(record)"),
    "codex-rs/hepta-matrix-sdk/src/content.rs": ("hepta.matrix.canonical-outbound-content.v1", "m.new_content", "m.relates_to", "event_id", "sort_unstable_by"),
    "codex-rs/hepta-matrix-sdk/src/sdk.rs": ("mod implementation", "fn send<'a>(", "_seal: MatrixRawSendSeal", "outbound_message_content(body", "disable_retry()"),
    "codex-rs/hepta-matrix-sdk/src/sdk_implementation.rs": ("ErrorKind::LimitExceeded", "RetryAfter::Delay", "MatrixTransportError::Dns", "MatrixTransportError::Tls", "MatrixTransportError::ResponseLost"),
    "codex-rs/hepta-matrix-store/src/claim/store.rs": ("claim_outbox_fenced(", "record_outbox_authorized(", "record_outbox_dispatching(", "record_outbox_entered_use(", "finish_outbox_indeterminate(", "matrix_dispatch_authority_witnesses", "matrix_dispatch_attempt_events", "matrix_dispatch_use_entries"),
    "codex-rs/hepta-matrix-store/src/claim/content.rs": ("pin_outbox_content(", "require_live_active_claim_tx", "matrix_dispatch_content_bindings", "matrix_dispatch_legacy_content_holds", "unsafe_prior"),
    "codex-rs/hepta-matrix-store/src/store.rs": ("MATRIX_DISPATCH_SCHEMA_SOURCES", "FROM matrix_sendable_outbox_v2 AS outbox", "matrix_dispatch_legacy_content_holds AS hold"),
    "codex-rs/hepta-matrix-store/src/dispatch.rs": ("pub async fn prepare_outbox_dispatch(", "pub(crate) async fn observe_outbound_event_tx(", "pub(crate) async fn apply_dispatch_redaction_tx("),
    "codex-rs/hepta-matrix-store/src/sync_v2.rs": ("observe_outbound_event_tx(", "apply_dispatch_redaction_tx("),
    "codex-rs/hepta-matrix-store/migrations/0006_matrix_dispatch_ledger.sql": ("CREATE TABLE matrix_dispatch_ledger", "CREATE TABLE matrix_dispatch_observations", "CREATE TABLE matrix_dispatch_authority_claims", "matrix_dispatch_ledger_identity_immutable", "matrix_dispatch_succeeded_requires_authority_claim"),
    "codex-rs/hepta-matrix-store/migrations/0007_matrix_claim_fencing.sql": ("CREATE TABLE matrix_dispatch_attempt_claims", "CREATE TABLE matrix_dispatch_active_claims", "CREATE TABLE matrix_dispatch_authority_witnesses", "CREATE TABLE matrix_dispatch_attempt_events", "Matrix attempt history is append-only"),
    "codex-rs/hepta-matrix-store/migrations/0008_matrix_content_binding.sql": ("CREATE TABLE matrix_dispatch_content_bindings", "matrix_dispatch_content_bindings_no_update", "matrix_dispatch_content_bindings_no_delete"),
    "codex-rs/hepta-matrix-store/migrations/0009_matrix_legacy_content_holds.sql": ("CREATE TABLE matrix_dispatch_legacy_content_holds", "message.attempts > 0", "matrix_dispatch_legacy_content_holds_no_insert", "matrix_dispatch_legacy_content_holds_no_delete"),
    "codex-rs/hepta-matrix-store/migrations/0010_matrix_entered_use_proofs.sql": ("CREATE TABLE matrix_dispatch_use_entries", "matrix_dispatch_use_entries_no_update", "CREATE TRIGGER matrix_dispatch_succeeded_requires_authority_claim", "qualified Matrix success requires a durable entered-use proof", "FROM matrix_dispatch_use_entries AS entry"),
    "codex-rs/hepta-matrix-store/migrations/0011_matrix_legacy_hold_remediation.sql": ("INSERT INTO matrix_dispatch_ledger", "9223372036854775807", "matrix_dispatch_legacy_hold_no_reactivate"),
    "codex-rs/hepta-matrix-store/migrations/0012_matrix_terminal_any_entered_attempt.sql": ("entry.attempt <= NEW.attempts", "matrix_dispatch_succeeded_requires_authority_claim", "matrix_dispatch_redacted_requires_authority_claim"),
    "codex-rs/hepta-matrix-store/migrations/0013_matrix_inbox_recovery.sql": ("CREATE TABLE matrix_inbox_recovery", "matrix_inbox_recovery_identity_guard", "matrix_inbox_recovery_no_delete"),
    "codex-rs/hepta-matrix-store/src/recovery.rs": ("pub async fn due_inbox_recovery(", "pub async fn inbox_recovery_for_thread(", "pub async fn begin_inbox_recovery(", "pub async fn finish_inbox_recovery("),
    "codex-rs/hepta-matrixd/src/runtime/recovery.rs": ("dispatch_for_projection(", "MatrixRecoveryPurpose::Projection", "recovery_disposition("),
    "scripts/channel_matrix_qualification.py": ("parse_junit(", "registry is not bound to tested source", "not_executed"),
    "scripts/channel_matrix_diagnostics.py": ("query_only=ON", "?mode=ro", "not_in_snapshot"),
    "scripts/channel_matrix_status.py": ("command_state(", "workingDirectory", "independent_acceptance"),
    "codex-rs/state/src/capability_random.rs": ("pub fn random_capability_bytes() -> [u8; 32]", "Uuid::new_v4()"),
}
DENIED_CLAIMS = (
    "productionImplementation", "productExecutionComplete", "productExecutionProved",
    "deploymentQualificationComplete", "independentAcceptanceComplete",
    "independentAcceptance", "activation", "release",
)


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=check)


def rev(value: str) -> str:
    return run_git("rev-parse", value).stdout.strip()


def local_path(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"non-repository path: {relative}")
    resolved = (ROOT / path).resolve()
    if not resolved.is_relative_to(ROOT.resolve()):
        raise RuntimeError(f"source path escapes repository: {relative}")
    return resolved


def file_receipt(path: Path) -> dict[str, object]:
    relative = path.relative_to(ROOT).as_posix()
    payload = local_path(relative).read_bytes()
    blob = rev(f"HEAD:{relative}")
    actual = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
    if actual != blob:
        raise RuntimeError(f"worktree differs from candidate blob: {relative}")
    return {"path": relative, "gitBlob": blob,
            "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}


def require_markers(path: str, markers: tuple[str, ...]) -> dict[str, object]:
    local = local_path(path)
    text = local.read_text(encoding="utf-8")
    missing = [marker for marker in markers if marker not in text]
    if missing:
        raise RuntimeError(f"{path} lacks required marker(s): {missing}")
    return file_receipt(ROOT / path)


def require_false_claims(claims: object) -> None:
    if not isinstance(claims, dict):
        raise RuntimeError("implementation map lacks typed claimBoundary")
    for name in DENIED_CLAIMS:
        if claims.get(name) is not False:
            raise RuntimeError(f"unqualified claim must be explicit false: {name}")


def checked_observation(value: object, head: str, label: str) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise RuntimeError(f"missing {label}")
    commit, tree = value.get("commit"), value.get("tree")
    if not all(isinstance(v, str) and re.fullmatch(r"[0-9a-f]{40}", v) for v in (commit, tree)):
        raise RuntimeError(f"invalid {label} identity")
    if rev(f"{commit}^{{tree}}") != tree:
        raise RuntimeError(f"{label} commit/tree mismatch")
    if run_git("merge-base", "--is-ancestor", commit, head, check=False).returncode:
        raise RuntimeError(f"{label} is not an ancestor of candidate")
    return commit, tree


def load_implementation_map(payload: str) -> dict[str, object]:
    """Reject ambiguous JSON and untyped schema identities before using a map."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeError(f"duplicate implementation-map key: {key}")
            result[key] = value
        return result

    row = json.loads(payload, object_pairs_hook=unique)
    if not isinstance(row, dict):
        raise RuntimeError("implementation map must be an object")
    if (row.get("schema") != "hepta.module-implementation-map.v3"
            or type(row.get("schemaVersion")) is not int
            or row["schemaVersion"] != 3):
        raise RuntimeError("unsupported implementation-map schema")
    return row


def require_operation_inventory(operations: object) -> None:
    """All three owner operations are mandatory; duplicates are not coverage."""
    expected = {"admit_event", "prepare_send", "observe_send"}
    if not isinstance(operations, list):
        raise RuntimeError("implementation map lacks typed operations")
    observed = []
    for operation in operations:
        if not isinstance(operation, dict):
            raise RuntimeError("implementation operation must be an object")
        name = operation.get("operation")
        if not isinstance(name, str) or name != operation.get("designOperation"):
            raise RuntimeError("implementation operation/design identity mismatch")
        observed.append(name)
    if len(observed) != len(expected) or set(observed) != expected:
        raise RuntimeError("implementation map must cover each Matrix operation exactly once")


def verify(expected_sha: str | None) -> dict[str, object]:
    head, tree = rev("HEAD"), rev("HEAD^{tree}")
    if expected_sha is not None and head != expected_sha:
        raise RuntimeError(f"candidate mismatch: expected {expected_sha}, got {head}")
    map_file = ROOT / MAP_PATH
    row = load_implementation_map(map_file.read_text(encoding="utf-8"))
    if row.get("module") != "channel.matrix":
        raise RuntimeError("implementation-map module identity mismatch")
    if row.get("candidateBindingPolicy") != "immutable_source_anchor_plus_exact_head_receipt":
        raise RuntimeError("implementation map lacks exact-head binding policy")
    anchor, anchor_tree = checked_observation(row.get("sourceBase"), head, "sourceBase")
    observed, observed_tree = checked_observation(row.get("observedAtHead"), head, "observedAtHead")
    if row.get("productCallerState") != "source_composed_unqualified":
        raise RuntimeError("supervisor/runner caller exists but map is not source-composed")
    if row.get("productionWriterState") != "durable_store_established_unqualified":
        raise RuntimeError("durable Matrix writer state is not recorded")
    callers = row.get("productCallers")
    if not isinstance(callers, list) or len(callers) < 2:
        raise RuntimeError("implementation map lacks supervisor and matrixd callers")
    for caller in callers:
        require_markers(caller["sourcePath"], (caller["nativeSymbol"],))
    operations = row.get("operations")
    if not isinstance(operations, list) or not operations:
        raise RuntimeError("implementation map lacks operations")
    require_operation_inventory(operations)
    for operation in operations:
        source, symbol = operation["sourcePath"], operation["nativeSymbol"]
        require_markers(source, (symbol,))
        if operation.get("sourceBlob") not in (rev(f"{observed}:{source}"), rev(f"HEAD:{source}")):
            raise RuntimeError(f"mapped source blob has no candidate/observation binding: {source}")
        callees = operation.get("delegatedCallees")
        if not isinstance(callees, list) or not callees:
            raise RuntimeError(f"operation lacks concrete callsites: {source}")
        for callee in callees:
            require_markers(callee["path"], (callee["symbol"],))
    object_receipts = []
    for obj in row.get("sourceObjects", []):
        path = obj["path"]
        local_path(path)
        observed_object = rev(f"{observed}:{path}")
        if obj["object"] != observed_object:
            raise RuntimeError(f"stale observed source object: {path}")
        object_receipts.append({"path": path, "observedObject": observed_object,
                                "candidateObject": rev(f"HEAD:{path}")})
    if not object_receipts:
        raise RuntimeError("implementation map lacks source object identities")
    sdk_lib = local_path("codex-rs/hepta-matrix-sdk/src/lib.rs").read_text()
    if "mod outbound;" in sdk_lib or "pub use outbound::" in sdk_lib:
        raise RuntimeError("legacy unfenced outbound module is exported")
    if "pub use outbound_v2::MatrixSendPermit;" in sdk_lib:
        raise RuntimeError("final-use permit escaped the private outbound gate")
    transport_boundary = local_path(
        "codex-rs/hepta-matrix-sdk/src/outbound_v2/mod.rs"
    ).read_text()
    trait_start = transport_boundary.find("pub trait MatrixOutboundTransport")
    trait_end = transport_boundary.find(
        "\n}\n\n/// Final, module-private permit adapter", trait_start
    )
    if trait_start < 0 or trait_end < 0:
        raise RuntimeError("Matrix transport trait/private adapter boundary is ambiguous")
    if "send_authorized" in transport_boundary[trait_start:trait_end]:
        raise RuntimeError("public transport trait can override authorized permit validation")
    if "pub use permit::MatrixSendPermit" in transport_boundary:
        raise RuntimeError("outbound module publicly re-exports its final-use permit")
    facade = local_path("codex-rs/hepta-matrix-sdk/src/sdk.rs").read_text()
    if re.search(r"pub\s+(?:async\s+)?fn\s+client\s*\(", facade) or "Deref for MatrixSdkClient" in facade:
        raise RuntimeError("raw SDK client escaped the governed facade")
    if "fn send_authorized" in facade:
        raise RuntimeError("SDK transport overrides the final authorized adapter")
    observer_path = "codex-rs/hepta-matrixd/src/send_observer.rs"
    observer = local_path(observer_path).read_text()
    for token in ("BTreeMap", "struct MatrixSendObserver", "fn prepare_send(", "fn observe_send("):
        if token in observer:
            raise RuntimeError(f"second in-memory send ledger returned: {token}")
    if "MatrixDispatchState" not in observer:
        raise RuntimeError("send observer does not delegate to durable dispatch state")
    docs = []
    for name in REQUIRED_DOCS:
        path = ROOT / DOC_ROOT / name
        if not path.is_file() or path.stat().st_size < 256:
            raise RuntimeError(f"missing or empty implementation documentation: {name}")
        docs.append(file_receipt(path))
    sources = [require_markers(path, markers) for path, markers in SOURCE_MARKERS.items()]
    sources.append(file_receipt(ROOT / observer_path))
    claims = row.get("claimBoundary")
    require_false_claims(claims)
    if row.get("productionImplementation") is not False:
        raise RuntimeError("top-level production claim must be explicit false")
    if claims.get("nativeSourceMappingComplete") is not True:
        raise RuntimeError("native source navigation mapping is incomplete")
    return {
        "schema": "hepta.channel-matrix-candidate-receipt.v1",
        "status": "PASS_CHANNEL_MATRIX_CANDIDATE_BINDING",
        "evidenceScope": "static_source_navigation_not_native_execution",
        "candidate": {"commit": head, "tree": tree},
        "map": {**file_receipt(map_file),
                "sourceAnchor": {"commit": anchor, "tree": anchor_tree},
                "observedAtHead": {"commit": observed, "tree": observed_tree},
                "bindingPolicy": row["candidateBindingPolicy"]},
        "sourceObjects": object_receipts,
        "sourceComposition": sources, "documentation": docs,
        "claims": {**{name: False for name in DENIED_CLAIMS},
                   "productCallerState": row["productCallerState"],
                   "productionWriterState": row["productionWriterState"]},
        "authorityGranted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        receipt = verify(args.expected_sha)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError, RuntimeError) as exc:
        raise SystemExit(f"FAIL_CHANNEL_MATRIX_CANDIDATE_BINDING: {exc}") from exc
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(encoded, end="")
    else:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
