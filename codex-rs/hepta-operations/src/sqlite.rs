use std::path::Path;

use codex_state::open_durable_evidence_pool_with_limit;
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
    let sqlite_home = AbsolutePathBuf::try_from(canonical_parent)
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;
    let file_name = path
        .file_name()
        .ok_or(DurableOperationError::Invalid("database file name"))?;
    let absolute_path = sqlite_home.as_path().join(file_name);
    // Keep the operations owner's four-connection capacity/fault contract while
    // retaining the shared SQLite durability and foreign-key policy.
    open_durable_evidence_pool_with_limit(&absolute_path, /*max_connections*/ 4)
        .await
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))
}
