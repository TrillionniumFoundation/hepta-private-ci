#!/usr/bin/env python3
"""Exact follow-up patches for the runtime.supervisor six-phase materializer."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]


def apply(
    root: Path,
    read: Callable[[Path], str],
    write: Callable[[Path, str], None],
) -> None:
    """Apply reviewed follow-ups using the caller's staged edit transaction."""
    src = root / "codex-rs" / "hepta-supervisor" / "src"
    docs = root / "docs" / "modules" / "runtime.supervisor"

    def replace_once(path: Path, old: str, new: str, *, sentinel: str) -> None:
        text = read(path)
        if sentinel in text:
            return
        # Match exact relative indentation at either source indentation level.
        # Main materialization inserts dedented methods; rustfmt indents them.
        old_lines = dedent(old).strip("\n").splitlines()
        new_lines = dedent(new).strip("\n").splitlines()
        lines = text.splitlines(keepends=True)
        for start in range(len(lines) - len(old_lines) + 1):
            first = lines[start].rstrip("\n")
            prefix = first[: len(first) - len(first.lstrip())]
            if all(
                lines[start + offset].rstrip("\n") == (prefix + line if line else "")
                for offset, line in enumerate(old_lines)
            ):
                lines[start : start + len(old_lines)] = [
                    (prefix + line if line else "") + "\n" for line in new_lines
                ]
                write(path, "".join(lines))
                return
        raise SystemExit(f"follow-up marker changed in {path}: {old_lines[0]!r}")

    execution = src / "daemon_execution.rs"
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

    robrix = src / "robrix_protocol.rs"
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

    client = src / "daemon_client.rs"
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

    retry_doc = docs / "MUTATION_RETRY_PROTOCOL.md"
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
        if marker not in read(path):
            raise SystemExit(f"follow-up verification failed for {path}: {marker}")


def main() -> None:
    if __package__:
        from . import runtime_supervisor_six_phase_materialize as materializer
    else:
        import runtime_supervisor_six_phase_materialize as materializer
    materializer.transact(lambda: apply(ROOT, materializer.read, materializer.write))


if __name__ == "__main__":
    main()
