#!/usr/bin/env python3
"""Exact follow-up patches for the runtime.supervisor six-phase materializer."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codex-rs" / "hepta-supervisor" / "src"
DOCS = ROOT / "docs" / "modules" / "runtime.supervisor"


def replace_once(path: Path, old: str, new: str, *, sentinel: str) -> None:
    text = path.read_text(encoding="utf-8")
    if sentinel in text:
        return
    if old not in text:
        raise SystemExit(f"follow-up marker changed in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    execution = SRC / "daemon_execution.rs"
    replace_once(
        execution,
        """pub(super) async fn handle(
    state: Arc<DaemonState<UnixProcessDriver>>,
    method: SupervisordMethod,
) -> SupervisordPayload {
    handle_with_request_id(state, 1, method).await
}
""",
        """pub(super) async fn handle(
    state: Arc<DaemonState<UnixProcessDriver>>,
    method: SupervisordMethod,
) -> SupervisordPayload {
    let bytes = *uuid::Uuid::new_v4().as_bytes();
    let request_id = u64::from_be_bytes(
        bytes[..8]
            .try_into()
            .expect("UUID prefix is exactly eight bytes"),
    )
    .max(1);
    handle_with_request_id(state, request_id, method).await
}
""",
        sentinel="UUID prefix is exactly eight bytes",
    )

    robrix = SRC / "robrix_protocol.rs"
    replace_once(
        robrix,
        """            SupervisordPayload::MutationAccepted { .. }
            | SupervisordPayload::ReleaseSelection { .. }
            | SupervisordPayload::ProductionMutationStatus { .. } => {
""",
        """            SupervisordPayload::MutationAccepted { .. }
            | SupervisordPayload::ReleaseSelection { .. }
            | SupervisordPayload::ProductionMutationStatus { .. }
            | SupervisordPayload::OrdinaryMutationStatus { .. } => {
""",
        sentinel="| SupervisordPayload::OrdinaryMutationStatus { .. }",
    )

    client = SRC / "daemon_client.rs"
    replace_once(
        client,
        """    pub async fn execute_mutation_with_request_id(
        &self,
        request_id: u64,
        method: SupervisordMethod,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        if !matches!(
""",
        """    pub async fn execute_mutation_with_request_id(
        &self,
        request_id: u64,
        method: SupervisordMethod,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        if request_id == 0 {
            return Err(SupervisorError::Invalid(
                "ordinary mutation request identity must be non-zero".to_string(),
            ));
        }
        if !matches!(
""",
        sentinel="ordinary mutation request identity must be non-zero",
    )

    retry_doc = DOCS / "MUTATION_RETRY_PROTOCOL.md"
    replace_once(
        retry_doc,
        """               - `prepared`: the side effect was not entered; retrying the exact same
                 request identity is allowed.
""",
        """               - `prepared`: the side effect was not entered; retrying the exact same
                 request identity is allowed while the same supervisor epoch and accepted
                 fence remain current. After daemon replacement, query or reconcile instead.
""",
        sentinel="After daemon replacement, query or reconcile instead.",
    )

    for path, marker in (
        (execution, "handle_with_request_id(state, request_id, method).await"),
        (robrix, "SupervisordPayload::OrdinaryMutationStatus"),
        (client, "ordinary mutation request identity must be non-zero"),
    ):
        if marker not in path.read_text(encoding="utf-8"):
            raise SystemExit(f"follow-up verification failed for {path}: {marker}")


if __name__ == "__main__":
    main()
