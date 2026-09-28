#!/usr/bin/env python3
"""Apply the exact native compile/lint repair for the kernel.evidence closure branch.

This script deliberately changes no qualification, deployment, acceptance, canary,
promotion, or release status. It repairs deterministic source defects observed in
the retained source-head diagnostics for 99419dedbd83684cc7a9ace31a2fb6ece0d9140f.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_exact(path: str, old: str, new: str, expected: int = 1) -> None:
    text = read(path)
    observed = text.count(old)
    if observed != expected:
        raise SystemExit(
            f"{path}: expected {expected} exact matches, observed {observed}: {old[:160]!r}"
        )
    write(path, text.replace(old, new, expected))


def replace_regex(path: str, pattern: str, replacement: str, expected: int) -> None:
    text = read(path)
    updated, observed = re.subn(pattern, replacement, text, flags=re.S)
    if observed != expected:
        raise SystemExit(
            f"{path}: expected {expected} regex matches, observed {observed}: {pattern}"
        )
    write(path, updated)


def repair_sqlx_safe_strings() -> None:
    qualification = "codex-rs/hepta-evidence/src/qualification.rs"
    replace_regex(
        qualification,
        r"sqlx::query\(&format!\((.*?)\)\)",
        r"sqlx::query(sqlx::AssertSqlSafe(format!(\1)))",
        4,
    )

    replace_exact(
        "codex-rs/hepta-evidence/src/qualification_commitment.rs",
        "sqlx::query(&statement)",
        "sqlx::query(sqlx::AssertSqlSafe(statement))",
    )
    replace_exact(
        "codex-rs/hepta-evidence/src/recovery_snapshot.rs",
        "sqlx::query(&statement)",
        "sqlx::query(sqlx::AssertSqlSafe(statement))",
    )

    runtime = "codex-rs/hepta-evidence/src/store/runtime.rs"
    replace_exact(
        runtime,
        "sqlx::query(statement).execute(&store.pool).await",
        "sqlx::query(sqlx::AssertSqlSafe(statement))\n            .execute(&store.pool)\n            .await",
    )
    replace_exact(
        runtime,
        'sqlx::query_scalar(&format!("PRAGMA max_page_count = {requested_limit}"))',
        'sqlx::query_scalar(sqlx::AssertSqlSafe(format!(\n'
        '                "PRAGMA max_page_count = {requested_limit}"\n'
        "            )))",
    )


def repair_segmented_backend_tests() -> None:
    segmented = "codex-rs/hepta-evidence/src/frontier_backend_file/segmented/tests.rs"
    replace_exact(
        segmented,
        """            std::fs::set_permissions(&identity_path, std::fs::Permissions::from_mode(0o600))
                .unwrap();
            Self {""",
        """            std::fs::set_permissions(&identity_path, std::fs::Permissions::from_mode(0o600))
                .unwrap();
            let local_root = local.path().canonicalize().unwrap();
            Self {""",
    )
    replace_exact(
        segmented,
        "                local_root: local.path().canonicalize().unwrap(),",
        "                local_root,",
    )
    replace_exact(
        segmented,
        "for generation in 1..=6 {",
        "for generation in 1_u64..=6 {",
        2,
    )
    replace_exact(
        segmented,
        "for generation in 1..=5 {",
        "for generation in 1_u64..=5 {",
    )


def repair_scoped_operations_lints() -> None:
    destination = "codex-rs/hepta-operations/src/destination_dedupe.rs"
    replace_exact(
        destination,
        "    pub async fn open_standalone(path: &Path) -> Result<Self, DurableOperationError> {",
        """    #[expect(
        clippy::disallowed_methods,
        reason = "standalone qualification store owns this isolated SQLite pool; product owners inject an already-migrated pool"
    )]
    pub async fn open_standalone(path: &Path) -> Result<Self, DurableOperationError> {""",
    )

    durable = "codex-rs/hepta-operations/src/durable_store.rs"
    replace_exact(
        durable,
        "    pub async fn open(path: &Path) -> Result<Self, DurableOperationError> {",
        """    #[expect(
        clippy::disallowed_methods,
        reason = "the durable operation ledger owns this standalone SQLite lineage and has no codex-state home binding"
    )]
    pub async fn open(path: &Path) -> Result<Self, DurableOperationError> {""",
    )
    replace_exact(
        durable,
        """        if let Some(status) = load_outbox_tx(
            &mut tx,
            &operation.intent.destination,
            scope_id,
            operation_id,
        )
        .await?
        {
            if status.state != DurableOutboxState::Acknowledged {
                let fence = status
                    .fence
                    .checked_add(1)
                    .ok_or(DurableOperationError::Capacity)?;
                sqlx::query(
                    "UPDATE cross_owner_outbox SET state = 'acked', fence = ?, worker_id = NULL,
                     lease_until_ms = NULL, acknowledgement_digest = ?, updated_at_ms = ?,
                     terminal_at_ms = COALESCE(terminal_at_ms, ?)
                     WHERE destination = ? AND scope_id = ? AND operation_id = ?",
                )
                .bind(to_i64(fence)?)
                .bind(receipt.evidence_digest.as_array().as_slice())
                .bind(now)
                .bind(now)
                .bind(operation.intent.destination.as_str())
                .bind(scope_id.as_str())
                .bind(operation_id.as_str())
                .execute(&mut *tx)
                .await
                .map_err(sqlx_error)?;
            }
        }""",
        """        if let Some(status) = load_outbox_tx(
            &mut tx,
            &operation.intent.destination,
            scope_id,
            operation_id,
        )
        .await?
            && status.state != DurableOutboxState::Acknowledged
        {
            let fence = status
                .fence
                .checked_add(1)
                .ok_or(DurableOperationError::Capacity)?;
            sqlx::query(
                "UPDATE cross_owner_outbox SET state = 'acked', fence = ?, worker_id = NULL,
                 lease_until_ms = NULL, acknowledgement_digest = ?, updated_at_ms = ?,
                 terminal_at_ms = COALESCE(terminal_at_ms, ?)
                 WHERE destination = ? AND scope_id = ? AND operation_id = ?",
            )
            .bind(to_i64(fence)?)
            .bind(receipt.evidence_digest.as_array().as_slice())
            .bind(now)
            .bind(now)
            .bind(operation.intent.destination.as_str())
            .bind(scope_id.as_str())
            .bind(operation_id.as_str())
            .execute(&mut *tx)
            .await
            .map_err(sqlx_error)?;
        }""",
    )


def remove_obsolete_transport_files() -> None:
    for path in (
        "qualification/kernel-evidence/live-fix-20260928.patch.gz.b64",
        "qualification/kernel-evidence/live-fix-20260928.patch",
        "qualification/kernel-evidence/live-fix-20260928.patch-check.txt",
    ):
        (ROOT / path).unlink(missing_ok=True)


def main() -> None:
    repair_sqlx_safe_strings()
    repair_segmented_backend_tests()
    repair_scoped_operations_lints()
    remove_obsolete_transport_files()


if __name__ == "__main__":
    main()
