#!/usr/bin/env python3
"""One-shot deterministic repair for automation.taskflow qualification blockers."""

from __future__ import annotations

from pathlib import Path


def replace_once(path_name: str, old: str, new: str) -> None:
    path = Path(path_name)
    body = path.read_text(encoding="utf-8")
    count = body.count(old)
    if count != 1:
        raise SystemExit(f"{path_name}: expected one repair anchor, found {count}")
    path.write_text(body.replace(old, new, 1), encoding="utf-8")


def repair_agentd_test() -> None:
    path = "codex-rs/hepta-agentd/src/automation_service_tests.rs"
    replace_once(
        path,
        "use codex_hepta_automation::AutomationQueueReceipt;\n",
        "use codex_hepta_automation::AutomationQueueReceipt;\n"
        "use codex_hepta_automation::AutomationRuntimePolicyV1;\n",
    )
    replace_once(
        path,
        """    let mut task = tokio::spawn(run_scheduler_loop(
        scheduler,
        Arc::clone(&fixture.state),
        stop.clone(),
        Duration::from_millis(1),
    ));""",
        """    let mut task = tokio::spawn(run_scheduler_loop(
        scheduler,
        Arc::clone(&fixture.state),
        stop.clone(),
        Duration::from_millis(1),
        AutomationRuntimePolicyV1::default(),
    ));""",
    )


def repair_operations_manifest() -> None:
    replace_once(
        "codex-rs/hepta-operations/Cargo.toml",
        """codex-hepta-contracts = { workspace = true }
codex-hepta-types = { workspace = true }
sqlx = { workspace = true }
""",
        """codex-hepta-contracts = { workspace = true }
codex-hepta-types = { workspace = true }
codex-state = { workspace = true }
codex-utils-absolute-path = { workspace = true }
sqlx = { workspace = true }
""",
    )


def repair_sqlite_owner(path_name: str, invalid_label: str) -> None:
    replace_once(path_name, "use std::time::Duration;\n", "")
    replace_once(
        path_name,
        """use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteJournalMode;
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::sqlite::SqliteSynchronous;
""",
        """use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
""",
    )
    replace_once(
        path_name,
        """        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Full)
            .foreign_keys(true)
            .busy_timeout(Duration::from_secs(5));
        let pool = SqlitePoolOptions::new()
            .max_connections(4)
            .connect_with(options)
            .await
            .map_err(sqlx_error)?;""",
        f"""        let parent = path
            .parent()
            .ok_or(DurableOperationError::Invalid(\"{invalid_label}\"))?;
        let sqlite_home = parent
            .canonicalize()
            .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;
        let sqlite_home = AbsolutePathBuf::try_from(sqlite_home)
            .map_err(|_| DurableOperationError::Invalid(\"{invalid_label}\"))?;
        let pool = SqliteConfig::from_sqlite_home(sqlite_home)
            .open_durable_evidence_pool(path)
            .await
            .map_err(sqlx_error)?;""",
    )


def repair_clippy_if() -> None:
    replace_once(
        "codex-rs/hepta-operations/src/durable_store.rs",
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
                    \"UPDATE cross_owner_outbox SET state = 'acked', fence = ?, worker_id = NULL,
                     lease_until_ms = NULL, acknowledgement_digest = ?, updated_at_ms = ?,
                     terminal_at_ms = COALESCE(terminal_at_ms, ?)
                     WHERE destination = ? AND scope_id = ? AND operation_id = ?\",
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
        }
""",
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
                \"UPDATE cross_owner_outbox SET state = 'acked', fence = ?, worker_id = NULL,
                 lease_until_ms = NULL, acknowledgement_digest = ?, updated_at_ms = ?,
                 terminal_at_ms = COALESCE(terminal_at_ms, ?)
                 WHERE destination = ? AND scope_id = ? AND operation_id = ?\",
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
""",
    )


def repair_document_anchor() -> None:
    path = "docs/modules/automation.taskflow/TECHNICAL.md"
    replace_once(
        path,
        "### 4.4 External-effect product path\n",
        """### 4.4 Durable choice, checkpoint and effect ordering

A DecisionCell choice and its exact runtime profile are recorded before an organ,
wait boundary or external-effect intent may advance. Checkpoint publication
precedes provider contact. A wait resumes from the recorded choice rather than
re-evaluating a changed policy, and an effect crosses only the existing
final-use-authorized seam. An unknown provider outcome remains reconciliation
work; neither lease expiry nor host replacement authorizes blind redispatch.

### 4.5 External-effect product path
""",
    )
    replace_once(
        path,
        "### 4.5 Design records and failure semantics\n",
        "### 4.6 Design records and failure semantics\n",
    )


def main() -> None:
    repair_agentd_test()
    repair_operations_manifest()
    repair_sqlite_owner(
        "codex-rs/hepta-operations/src/destination_dedupe.rs",
        "destination dedupe path",
    )
    repair_sqlite_owner(
        "codex-rs/hepta-operations/src/durable_store.rs",
        "operation store path",
    )
    repair_clippy_if()
    repair_document_anchor()


if __name__ == "__main__":
    main()
