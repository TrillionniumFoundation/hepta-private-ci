//! Connection settings come from the existing durable SQLite shim. Each
//! inference owner retains its own schema, pool lifetime and recovery rules.

use std::path::Path;

use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use sqlx::SqlitePool;

pub(crate) async fn open_durable_pool(path: &Path) -> Result<SqlitePool, sqlx::Error> {
    let parent = path
        .parent()
        .ok_or_else(|| sqlx::Error::Protocol("database path has no parent".into()))?;
    let home = AbsolutePathBuf::try_from(parent)
        .map_err(|error| sqlx::Error::Protocol(error.to_string()))?;
    SqliteConfig::from_sqlite_home(home)
        .open_durable_evidence_pool(path)
        .await
}
