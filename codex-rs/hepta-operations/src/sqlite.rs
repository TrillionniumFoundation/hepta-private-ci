use std::path::Path;

use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use sqlx::SqlitePool;

use crate::DurableOperationError;

/// Open one owner-controlled FULL/WAL SQLite database through the repository
/// connection shim. Callers remain responsible for their migration lineage.
pub(crate) async fn open_durable_pool(path: &Path) -> Result<SqlitePool, DurableOperationError> {
    let parent = path
        .parent()
        .filter(|candidate| !candidate.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    std::fs::create_dir_all(parent)
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;
    let canonical_parent = parent
        .canonicalize()
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;
    let filename = path.file_name().ok_or_else(|| {
        DurableOperationError::Unavailable("SQLite path has no file name".to_owned())
    })?;
    let canonical_path = canonical_parent.join(filename);
    let sqlite_home = AbsolutePathBuf::try_from(canonical_parent)
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;
    SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(&canonical_path)
        .await
        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))
}
