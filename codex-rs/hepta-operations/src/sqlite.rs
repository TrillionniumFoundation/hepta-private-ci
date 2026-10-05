use std::path::Path;

use codex_state::SqliteConfig;
use sqlx::SqlitePool;

use crate::DurableOperationError;

pub(crate) async fn open_durable_pool(path: &Path) -> Result<SqlitePool, DurableOperationError> {
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    std::fs::create_dir_all(parent)
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;
    let canonical_parent = std::fs::canonicalize(parent)
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;
    let file_name = path
        .file_name()
        .ok_or(DurableOperationError::Invalid("database file name"))?;
    let absolute_path = canonical_parent.join(file_name);
    SqliteConfig::open_operation_owner_pool(&absolute_path)
        .await
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))
}

#[cfg(test)]
#[path = "sqlite_tests.rs"]
pub(crate) mod tests;
