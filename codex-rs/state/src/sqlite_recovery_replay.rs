//! Writable recovery staging for an identity-bound SQLite database.
//!
//! The source database is never opened by SQLite. Bytes are copied from the
//! already-retained descriptors into a fresh private sibling database. SQLite
//! is allowed to replay a retained WAL only on that isolated copy. The caller
//! must independently authenticate the complete logical cut before promoting
//! the copy over the source path.

use crate::SqliteConfig;
use sqlx::Row;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteJournalMode;
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::sqlite::SqliteSynchronous;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::time::Duration;

use super::super::ExistingSqliteRecoveryGuard;
use super::super::RetainedObject;
use super::super::RetainedOptionalObject;
use super::super::SqliteRecoveryError;
use super::super::sqlite_sidecar_path;

const COPY_CHUNK_BYTES: usize = 1024 * 1024;
const MAX_COMPONENT_BYTES: u64 = 256 * 1024 * 1024;
const MAX_TOTAL_COPY_BYTES: u64 = 384 * 1024 * 1024;

impl SqliteConfig {
    /// Materialize a descriptor-bound recovery candidate into an isolated
    /// private database and replay its WAL there.
    ///
    /// The destination must be a new sibling of the bound database. The source
    /// main/WAL/SHM descriptors are revalidated before and after copying and
    /// again after SQLite finishes replay/checkpoint on the isolated copy.
    /// Rollback journals are rejected because the authoritative cognitive store
    /// is WAL/FULL and mixing rollback-journal recovery into this path would
    /// widen the accepted physical state machine.
    ///
    /// This function does not grant recovery authority and does not replace the
    /// source database. Its returned pool is a staging image only; callers must
    /// compare an independently retained complete logical cut before promotion.
    pub async fn open_replayed_recovery_copy(
        &self,
        guard: &ExistingSqliteRecoveryGuard,
        isolated_database: &Path,
    ) -> Result<SqlitePool, SqliteRecoveryError> {
        if isolated_database.parent() != Some(self.home())
            || isolated_database == guard.inner.database_path
        {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        for suffix in ["", "-wal", "-shm", "-journal"] {
            let candidate = if suffix.is_empty() {
                isolated_database.to_path_buf()
            } else {
                sqlite_sidecar_path(isolated_database, suffix)
            };
            match std::fs::symlink_metadata(&candidate) {
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Ok(_) | Err(_) => return Err(SqliteRecoveryError::Indeterminate),
            }
        }

        guard.revalidate_for(self)?;
        if matches!(
            &guard.inner.sidecars[2],
            RetainedOptionalObject::Present(_)
        ) {
            return Err(SqliteRecoveryError::Indeterminate);
        }

        let mut copied = match copy_retained(&guard.inner.database, isolated_database) {
            Ok(value) => value,
            Err(error) => {
                cleanup_copy(isolated_database);
                return Err(error);
            }
        };
        if let RetainedOptionalObject::Present(wal) = &guard.inner.sidecars[0] {
            let wal_path = sqlite_sidecar_path(isolated_database, "-wal");
            let wal_bytes = match copy_retained(wal, &wal_path) {
                Ok(value) => value,
                Err(error) => {
                    cleanup_copy(isolated_database);
                    return Err(error);
                }
            };
            copied = match copied
                .checked_add(wal_bytes)
                .filter(|value| *value <= MAX_TOTAL_COPY_BYTES)
            {
                Some(value) => value,
                None => {
                    cleanup_copy(isolated_database);
                    return Err(SqliteRecoveryError::Indeterminate);
                }
            };
        }
        if copied > MAX_TOTAL_COPY_BYTES {
            cleanup_copy(isolated_database);
            return Err(SqliteRecoveryError::Indeterminate);
        }
        if let Err(error) = guard.revalidate_for(self) {
            cleanup_copy(isolated_database);
            return Err(error);
        }

        let options = SqliteConnectOptions::new()
            .filename(isolated_database)
            .create_if_missing(false)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Full)
            .foreign_keys(true)
            .busy_timeout(Duration::from_secs(5));
        let pool = match SqlitePoolOptions::new()
            .max_connections(1)
            .acquire_timeout(Duration::from_secs(5))
            .connect_with(options)
            .await
        {
            Ok(pool) => pool,
            Err(_) => {
                cleanup_copy(isolated_database);
                return Err(SqliteRecoveryError::Indeterminate);
            }
        };

        let validation = async {
            let checkpoint = sqlx::query("PRAGMA wal_checkpoint(TRUNCATE)")
                .fetch_one(&pool)
                .await
                .map_err(|_| SqliteRecoveryError::Indeterminate)?;
            let busy: i64 = checkpoint
                .try_get(0)
                .map_err(|_| SqliteRecoveryError::Indeterminate)?;
            if busy != 0 {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            let integrity: Vec<String> = sqlx::query_scalar("PRAGMA integrity_check(1)")
                .fetch_all(&pool)
                .await
                .map_err(|_| SqliteRecoveryError::Indeterminate)?;
            if integrity.as_slice() != ["ok"] {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            guard.revalidate_for(self)?;
            Ok(())
        }
        .await;
        if let Err(error) = validation {
            pool.close().await;
            cleanup_copy(isolated_database);
            return Err(error);
        }
        Ok(pool)
    }
}

fn copy_retained(object: &RetainedObject, destination: &Path) -> Result<u64, SqliteRecoveryError> {
    let length = object
        .descriptor
        .metadata()
        .map_err(|_| SqliteRecoveryError::Indeterminate)?
        .len();
    if length > MAX_COMPONENT_BYTES {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(destination)
        .map_err(|_| SqliteRecoveryError::Indeterminate)?;
    let mut offset = 0_u64;
    let mut buffer = vec![0_u8; COPY_CHUNK_BYTES];
    while offset < length {
        let remaining = length - offset;
        let amount = usize::try_from(remaining.min(COPY_CHUNK_BYTES as u64))
            .map_err(|_| SqliteRecoveryError::Indeterminate)?;
        object
            .descriptor
            .read_exact_at(&mut buffer[..amount], offset)
            .map_err(|_| SqliteRecoveryError::Indeterminate)?;
        output
            .write_all(&buffer[..amount])
            .map_err(|_| SqliteRecoveryError::Indeterminate)?;
        offset = offset
            .checked_add(amount as u64)
            .ok_or(SqliteRecoveryError::Indeterminate)?;
    }
    output
        .sync_all()
        .map_err(|_| SqliteRecoveryError::Indeterminate)?;
    Ok(length)
}

fn cleanup_copy(database: &Path) {
    for path in [
        database.to_path_buf(),
        sqlite_sidecar_path(database, "-wal"),
        sqlite_sidecar_path(database, "-shm"),
        sqlite_sidecar_path(database, "-journal"),
    ] {
        let _ = std::fs::remove_file(path);
    }
}
