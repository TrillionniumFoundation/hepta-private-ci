#!/usr/bin/env python3
"""Bind channel.matrix source composition and documentation to one candidate.

`IMPLEMENTATION_MAP.sourceBase` is historical provenance. A map cannot contain
its own future commit/tree without a self-reference paradox, so this verifier
emits the exact HEAD/tree, map digest and every inspected source/document blob.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs/modules/channel.matrix/IMPLEMENTATION_MAP.json"
DOC_ROOT = ROOT / "docs/modules/channel.matrix"
REQUIRED_DOCS = (
    "ARCHITECTURE.md",
    "STATE_MACHINE.md",
    "STORAGE_SCHEMA.md",
    "MATRIX_PROTOCOL.md",
    "CONFIGURATION.md",
    "FAILURE_AND_RECOVERY.md",
    "OPERATIONS_RUNBOOK.md",
    "SECURITY_MODEL.md",
    "QUALIFICATION_MATRIX.md",
)
SOURCE_MARKERS = {
    "codex-rs/hepta-supervisor/src/matrix.rs": (
        "fn start_matrix_companion(",
        "spawn_matrixd(&spec)",
    ),
    "codex-rs/hepta-matrixd/src/runner.rs": (
        "pub async fn run(",
        "MatrixFinalUseBroker::open(&config.layout)",
        "run_outbox_sender(",
    ),
    "codex-rs/hepta-matrix-sdk/src/outbound.rs": (
        "record_dispatch_authority_claim(",
        "refresh_revocations()",
        "enter_verified_use(token, &request.binding)",
        "record_outbox_transport_accepted(",
    ),
    "codex-rs/hepta-matrix-sdk/src/authority.rs": (
        "pub struct MatrixFinalUseRequest",
        "pub trait MatrixOutboundAuthorizer",
        "build_matrix_final_use_request(",
    ),
    "codex-rs/hepta-matrix-store/src/dispatch.rs": (
        "pub async fn prepare_outbox_dispatch(",
        "pub(crate) async fn observe_outbound_event_tx(",
        "pub(crate) async fn apply_dispatch_redaction_tx(",
    ),
    "codex-rs/hepta-matrix-store/src/sync_v2.rs": (
        "observe_outbound_event_tx(",
        "apply_dispatch_redaction_tx(",
    ),
    "codex-rs/hepta-matrix-store/migrations/0006_matrix_dispatch_ledger.sql": (
        "CREATE TABLE matrix_dispatch_ledger",
        "CREATE TABLE matrix_dispatch_observations",
        "CREATE TABLE matrix_dispatch_authority_claims",
        "matrix_dispatch_ledger_identity_immutable",
        "matrix_dispatch_succeeded_requires_authority_claim",
    ),
}


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=check
    )


def rev(value: str) -> str:
    return run_git("rev-parse", value).stdout.strip()


def file_receipt(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    relative = str(path.relative_to(ROOT))
    return {
        "path": relative,
        "gitBlob": rev(f"HEAD:{relative}"),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }


def require_markers(path: str, markers: tuple[str, ...]) -> dict[str, object]:
    local = ROOT / path
    if not local.is_file():
        raise RuntimeError(f"missing source path: {path}")
    text = local.read_text(encoding="utf-8")
    missing = [marker for marker in markers if marker not in text]
    if missing:
        raise RuntimeError(f"{path} lacks required marker(s): {missing}")
    return file_receipt(local)


def verify(expected_sha: str | None) -> dict[str, object]:
    head = rev("HEAD")
    tree = rev("HEAD^{tree}")
    if expected_sha is not None and head != expected_sha:
        raise RuntimeError(f"candidate mismatch: expected {expected_sha}, got {head}")

    row = json.loads(MAP.read_text(encoding="utf-8"))
    if row.get("module") != "channel.matrix":
        raise RuntimeError("implementation-map module identity mismatch")
    source_base = row.get("sourceBase")
    if not isinstance(source_base, dict):
        raise RuntimeError("implementation map lacks sourceBase")
    anchor = source_base.get("commit")
    anchor_tree = source_base.get("tree")
    if not isinstance(anchor, str) or not isinstance(anchor_tree, str):
        raise RuntimeError("invalid sourceBase commit/tree")
    if rev(f"{anchor}^{{tree}}") != anchor_tree:
        raise RuntimeError("sourceBase tree does not match its commit")
    if run_git("merge-base", "--is-ancestor", anchor, head, check=False).returncode:
        raise RuntimeError("sourceBase is not an ancestor of candidate")

    if row.get("productCallerState") != "source_composed_unqualified":
        raise RuntimeError("supervisor/runner caller exists but map is not source-composed")
    if row.get("productionWriterState") != "durable_store_established_unqualified":
        raise RuntimeError("durable Matrix writer state is not recorded")
    callers = row.get("productCallers")
    if not isinstance(callers, list) or len(callers) < 2:
        raise RuntimeError("implementation map lacks supervisor and matrixd callers")

    operations = row.get("operations")
    if not isinstance(operations, list):
        raise RuntimeError("implementation map lacks operations")
    for operation in operations:
        if not isinstance(operation, dict):
            raise RuntimeError("invalid operation record")
        source = operation.get("sourcePath")
        symbol = operation.get("nativeSymbol")
        if not isinstance(source, str) or not isinstance(symbol, str):
            raise RuntimeError("operation lacks native source/symbol")
        source_text = (ROOT / source).read_text(encoding="utf-8")
        if symbol not in source_text:
            raise RuntimeError(f"mapped symbol is absent: {source}: {symbol}")
        callees = operation.get("delegatedCallees", [])
        if not callees:
            raise RuntimeError(
                f"operation {operation.get('operation')} has no concrete callsite/delegate"
            )
        for callee in callees:
            if not isinstance(callee, dict):
                raise RuntimeError("delegated callee must be typed")
            path = callee.get("path")
            marker = callee.get("symbol")
            if not isinstance(path, str) or not isinstance(marker, str):
                raise RuntimeError("delegated callee lacks path/symbol")
            if marker not in (ROOT / path).read_text(encoding="utf-8"):
                raise RuntimeError(f"delegated callsite is absent: {path}: {marker}")

    observer = (ROOT / "codex-rs/hepta-matrixd/src/send_observer.rs").read_text(
        encoding="utf-8"
    )
    forbidden = ("BTreeMap", "struct MatrixSendObserver", "fn prepare_send(", "fn observe_send(")
    present = [token for token in forbidden if token in observer]
    if present:
        raise RuntimeError(f"second in-memory send ledger returned: {present}")
    if "MatrixDispatchState" not in observer:
        raise RuntimeError("send observer does not delegate to durable dispatch state")

    docs = []
    for name in REQUIRED_DOCS:
        path = DOC_ROOT / name
        if not path.is_file() or path.stat().st_size < 256:
            raise RuntimeError(f"missing or empty executable documentation: {name}")
        docs.append(file_receipt(path))

    sources = [
        require_markers(path, markers) for path, markers in SOURCE_MARKERS.items()
    ]
    sources.append(file_receipt(ROOT / "codex-rs/hepta-matrixd/src/send_observer.rs"))

    claims = row.get("claimBoundary")
    if not isinstance(claims, dict):
        raise RuntimeError("implementation map lacks claimBoundary")
    if claims.get("nativeSourceMappingComplete") is not True:
        raise RuntimeError("native source mapping is not marked complete")
    for denied in (
        "productExecutionProved",
        "deploymentQualificationComplete",
        "independentAcceptance",
        "activation",
        "release",
    ):
        if claims.get(denied) is True:
            raise RuntimeError(f"unqualified execution claim is true: {denied}")

    return {
        "schema": "hepta.channel-matrix-candidate-receipt.v1",
        "status": "PASS_CHANNEL_MATRIX_CANDIDATE_BINDING",
        "candidate": {"commit": head, "tree": tree},
        "map": {
            **file_receipt(MAP),
            "sourceAnchor": {"commit": anchor, "tree": anchor_tree},
        },
        "sourceComposition": sources,
        "documentation": docs,
        "claims": {
            "productCallerState": row.get("productCallerState"),
            "productionWriterState": row.get("productionWriterState"),
            "productExecutionProved": bool(claims.get("productExecutionProved", False)),
            "deploymentQualificationComplete": bool(
                claims.get("deploymentQualificationComplete", False)
            ),
            "independentAcceptance": bool(claims.get("independentAcceptance", False)),
            "activation": bool(claims.get("activation", False)),
            "release": bool(claims.get("release", False)),
        },
        "authorityGranted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        receipt = verify(args.expected_sha)
    except (OSError, ValueError, subprocess.CalledProcessError, RuntimeError) as exc:
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
