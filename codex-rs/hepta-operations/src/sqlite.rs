use std::path::Path;

use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
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
    let sqlite_home = AbsolutePathBuf::try_from(canonical_parent.clone())
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;
    let file_name = path
        .file_name()
        .ok_or(DurableOperationError::Invalid("database file name"))?;
    let absolute_path = canonical_parent.join(file_name);
    SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(&absolute_path)
        .await
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))
}
