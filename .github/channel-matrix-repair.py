#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, before: str, after: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(before)
    if count != 1:
        raise SystemExit(
            f"{relative}: expected exactly one match, found {count}: {before[:120]!r}"
        )
    path.write_text(text.replace(before, after, 1), encoding="utf-8")


replace_once(
    "codex-rs/hepta-operations/Cargo.toml",
    "codex-hepta-types = { workspace = true }\nsqlx = { workspace = true }\n",
    "codex-hepta-types = { workspace = true }\n"
    "codex-state = { workspace = true }\n"
    "codex-utils-absolute-path = { workspace = true }\n"
    "sqlx = { workspace = true }\n",
)

replace_once(
    "codex-rs/hepta-operations/src/lib.rs",
    "mod outbox;\n",
    "mod outbox;\nmod sqlite;\n",
)

(ROOT / "codex-rs/hepta-operations/src/sqlite.rs").write_text(
    r'''use std::path::Path;
use std::path::PathBuf;

use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use sqlx::SqlitePool;

use crate::DurableOperationError;

/// Open an authoritative durable SQLite database through the repository's
/// single connection-policy shim. The resolved path is returned so the owner
/// never reports a different path from the database it actually opened.
pub(crate) async fn open_durable_evidence_pool(
    path: &Path,
) -> Result<(SqlitePool, PathBuf), DurableOperationError> {
    let absolute_path = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?
            .join(path)
    };
    let parent = absolute_path.parent().ok_or_else(|| {
        DurableOperationError::Unavailable("durable SQLite path has no parent".to_owned())
    })?;
    std::fs::create_dir_all(parent)
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;
    let sqlite_home = AbsolutePathBuf::try_from(parent)
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(&absolute_path)
        .await
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;
    Ok((pool, absolute_path))
}
''',
    encoding="utf-8",
)

replace_once(
    "codex-rs/hepta-operations/src/destination_dedupe.rs",
    "use std::time::Duration;\n",
    "",
)
for line in (
    "use sqlx::sqlite::SqliteConnectOptions;\n",
    "use sqlx::sqlite::SqliteJournalMode;\n",
    "use sqlx::sqlite::SqlitePoolOptions;\n",
    "use sqlx::sqlite::SqliteSynchronous;\n",
):
    replace_once("codex-rs/hepta-operations/src/destination_dedupe.rs", line, "")

replace_once(
    "codex-rs/hepta-operations/src/destination_dedupe.rs",
    '''        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;
        }
        let options = SqliteConnectOptions::new()
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
            .map_err(sqlx_error)?;
''',
    '''        let (pool, absolute_path) = crate::sqlite::open_durable_evidence_pool(path).await?;
''',
)
replace_once(
    "codex-rs/hepta-operations/src/destination_dedupe.rs",
    "            standalone_path: Some(path.to_path_buf()),\n",
    "            standalone_path: Some(absolute_path),\n",
)

for line in (
    "use sqlx::sqlite::SqliteConnectOptions;\n",
    "use sqlx::sqlite::SqliteJournalMode;\n",
    "use sqlx::sqlite::SqlitePoolOptions;\n",
    "use sqlx::sqlite::SqliteSynchronous;\n",
):
    replace_once("codex-rs/hepta-operations/src/durable_store.rs", line, "")

replace_once(
    "codex-rs/hepta-operations/src/durable_store.rs",
    '''        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;
        }
        let options = SqliteConnectOptions::new()
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
            .map_err(sqlx_error)?;
''',
    '''        let (pool, absolute_path) = crate::sqlite::open_durable_evidence_pool(path).await?;
''',
)
replace_once(
    "codex-rs/hepta-operations/src/durable_store.rs",
    "            path: path.to_path_buf(),\n",
    "            path: absolute_path,\n",
)
replace_once(
    "codex-rs/hepta-operations/src/durable_store.rs",
    '''        if let Some(status) = load_outbox_tx(
            &mut tx,
            &operation.intent.destination,
            scope_id,
            operation_id,
        )
        .await?
        {
            if status.state != DurableOutboxState::Acknowledged {
''',
    '''        if let Some(status) = load_outbox_tx(
            &mut tx,
            &operation.intent.destination,
            scope_id,
            operation_id,
        )
        .await?
            && status.state != DurableOutboxState::Acknowledged
        {
''',
)
replace_once(
    "codex-rs/hepta-operations/src/durable_store.rs",
    '''                .await
                .map_err(sqlx_error)?;
            }
        }
        let operation = load_operation_tx(&mut tx, scope_id, operation_id)
''',
    '''                .await
                .map_err(sqlx_error)?;
        }
        let operation = load_operation_tx(&mut tx, scope_id, operation_id)
''',
)

replace_once(
    "scripts/channel_matrix_evidence.py",
    '''    "codex-rs/hepta-matrix-sdk", "codex-rs/hepta-matrixd",
    "docs/modules/channel.matrix", "scripts/verify_channel_matrix_candidate.py",
''',
    '''    "codex-rs/hepta-matrix-sdk", "codex-rs/hepta-matrixd",
    "codex-rs/hepta-operations", "codex-rs/state",
    "docs/modules/channel.matrix", "scripts/verify_channel_matrix_candidate.py",
''',
)

replace_once(
    ".github/workflows/channel-matrix-preserve-unknown.yml",
    "      - 'codex-rs/hepta-contracts/**'\n",
    "      - 'codex-rs/hepta-contracts/**'\n"
    "      - 'codex-rs/hepta-operations/**'\n",
)
