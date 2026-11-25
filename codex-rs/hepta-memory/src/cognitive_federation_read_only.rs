//! Read-only connections to already-private federation sources.
//!
//! Retained Windows handles keep the checked root and file open while a reader
//! uses its pool. This is an ordinary live reader, not a cold recovery image or
//! an independently authenticated current-cut witness.

use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use sqlx::SqlitePool;

use crate::CognitiveStoreError;
use crate::cognitive_store::unavailable;

pub(super) struct SourceGuard {
    #[cfg(windows)]
    _file: std::fs::File,
    #[cfg(windows)]
    _directory: codex_utils_path::windows_private::PrivateSqliteDirectory,
}

pub(super) async fn open_pool(
    path: &Path,
) -> Result<(SqlitePool, Arc<SourceGuard>), CognitiveStoreError> {
    let (path, source_guard) = inspect_source(path)?;
    let sqlite_home = AbsolutePathBuf::try_from(
        path.parent()
            .ok_or_else(|| {
                CognitiveStoreError::Invalid(
                    "federated cognitive database has no parent directory".to_string(),
                )
            })?
            .to_path_buf(),
    )
    .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_private_read_only_pool(&path)
        .await
        .map_err(unavailable)?;
    sqlx::query("PRAGMA query_only = ON")
        .execute(&pool)
        .await
        .map_err(unavailable)?;
    let query_only: i64 = sqlx::query_scalar("PRAGMA query_only")
        .fetch_one(&pool)
        .await
        .map_err(unavailable)?;
    if query_only != 1 {
        return Err(CognitiveStoreError::Corrupt(
            "federated cognitive connection is not query-only".to_string(),
        ));
    }
    Ok((pool, Arc::new(source_guard)))
}

#[cfg(not(windows))]
fn inspect_source(path: &Path) -> Result<(PathBuf, SourceGuard), CognitiveStoreError> {
    let metadata = std::fs::metadata(path).map_err(unavailable)?;
    let canonical = crate::cognitive_path::canonical_path_without_redirection(path)
        .map_err(unavailable)?
        .filter(|_| metadata.is_file())
        .ok_or_else(|| {
            CognitiveStoreError::Invalid(
                "federated cognitive database must be an existing canonical regular file"
                    .to_string(),
            )
        })?;
    Ok((canonical, SourceGuard {}))
}

#[cfg(windows)]
fn inspect_source(path: &Path) -> Result<(PathBuf, SourceGuard), CognitiveStoreError> {
    use codex_utils_path::windows_private::Access;
    use codex_utils_path::windows_private::PrivateSqliteDirectory;

    let parent = path.parent().ok_or_else(|| {
        CognitiveStoreError::Invalid("federated cognitive database has no parent".to_string())
    })?;
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| {
            CognitiveStoreError::Invalid("federated cognitive database leaf is invalid".to_string())
        })?;
    // Existing-only and read-only: never create a directory/file or repair ACLs.
    // Native opens reject reparse ancestors, wrong owners and broad ACLs before
    // deriving the canonical spelling from the same retained directory handle.
    let directory = PrivateSqliteDirectory::inspect(parent).map_err(unavailable)?;
    let file = directory.open(name, Access::Read).map_err(unavailable)?;
    let canonical = directory.canonical_path().map_err(unavailable)?.join(name);
    Ok((
        canonical,
        SourceGuard {
            _file: file,
            _directory: directory,
        },
    ))
}
