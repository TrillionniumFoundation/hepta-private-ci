use std::path::Path;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Duration;

use sqlx::Connection;
use sqlx::SqliteConnection;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteJournalMode;
use sqlx::sqlite::SqliteSynchronous;

use crate::AuthBusAuthorityError;

/// Process-lifetime single-owner fence backed by an independent SQLite lock DB.
///
/// Holding an exclusive transaction on a separate database avoids blocking the
/// authority pool while still providing an OS-released cross-process lock. A
/// crash, including SIGKILL, closes the connection and releases the fence.
pub(crate) struct OwnerFence {
    _connection: Mutex<SqliteConnection>,
    _path: PathBuf,
}

impl OwnerFence {
    pub(crate) async fn acquire(
        database_path: &Path,
        owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        if owner_id.is_empty() || owner_id.len() > 256 || !database_path.is_absolute() {
            return Err(AuthBusAuthorityError::InvalidInput(
                "authority owner identity or database path is invalid",
            ));
        }
        let path = lock_path(database_path)?;
        validate_parent(&path)?;
        let options = SqliteConnectOptions::new()
            .filename(&path)
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Delete)
            .synchronous(SqliteSynchronous::Full)
            .busy_timeout(Duration::from_millis(100));
        let mut connection = SqliteConnection::connect_with(&options)
            .await
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        secure_lock_file(&path)?;
        sqlx::query("PRAGMA locking_mode = EXCLUSIVE")
            .execute(&mut connection)
            .await
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        sqlx::query("BEGIN EXCLUSIVE")
            .execute(&mut connection)
            .await
            .map_err(|_| AuthBusAuthorityError::OwnerAlreadyActive)?;
        Ok(Self {
            _connection: Mutex::new(connection),
            _path: path,
        })
    }
}

fn lock_path(database_path: &Path) -> Result<PathBuf, AuthBusAuthorityError> {
    let parent = database_path
        .parent()
        .ok_or(AuthBusAuthorityError::InvalidInput(
            "authority database has no parent directory",
        ))?;
    let mut name = database_path
        .file_name()
        .ok_or(AuthBusAuthorityError::InvalidInput(
            "authority database has no file name",
        ))?
        .to_os_string();
    name.push(".authbus-owner-lock.sqlite");
    Ok(parent.join(name))
}

#[cfg(unix)]
fn validate_parent(path: &Path) -> Result<(), AuthBusAuthorityError> {
    use std::os::unix::fs::MetadataExt;

    let parent = path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    if parent.canonicalize().map_err(storage_io)? != parent {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let metadata = std::fs::metadata(parent).map_err(storage_io)?;
    if !metadata.is_dir() || metadata.mode() & 0o077 != 0 {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_parent(_path: &Path) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn secure_lock_file(path: &Path) -> Result<(), AuthBusAuthorityError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;

    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
        .map_err(storage_io)?;
    let file = std::fs::symlink_metadata(path).map_err(storage_io)?;
    let parent = std::fs::metadata(
        path.parent()
            .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?,
    )
    .map_err(storage_io)?;
    if !file.is_file()
        || file.nlink() != 1
        || file.uid() != parent.uid()
        || file.mode() & 0o077 != 0
    {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(())
}

#[cfg(not(unix))]
fn secure_lock_file(_path: &Path) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

fn storage_io(error: std::io::Error) -> AuthBusAuthorityError {
    AuthBusAuthorityError::Storage(error.to_string())
}
