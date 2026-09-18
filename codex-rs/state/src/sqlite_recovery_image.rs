//! Descriptor-bound SQLite recovery-image helpers.
//!
//! Identity checks detect drift, not currentness. Read-only cold-image opening
//! accepts only a single retained database descriptor with no sidecars. Writable
//! recovery materialization may copy retained database, WAL, and rollback-journal
//! bytes into a fresh private generation; SQLite is allowed to replay only that
//! copy. The source path is never reopened by SQLite and is never mutated.
//! Consumers still MUST authenticate a complete independently retained current
//! cut before trusting or activating any recovered generation.

use super::ExistingSqliteRecoveryGuard;
use super::SqliteConfig;
use super::SqliteRecoveryError;
use sqlx::SqlitePool;

impl SqliteConfig {
    /// Materialize one identity-bound writable recovery candidate from retained
    /// descriptors into a new private path under this SQLite home.
    ///
    /// The database descriptor is bounded to 128 MiB, each retained WAL or
    /// rollback journal to 128 MiB, and the aggregate retained bundle to
    /// 256 MiB. This helper does not authenticate currentness or grant writer
    /// authority; the cognitive owner performs exact-cut, integrity, authority,
    /// checkpoint, and activation checks before the copy can become active.
    ///
    /// The source filename is never reopened for SQLite access. Database, WAL,
    /// and rollback-journal bytes are read from the retained descriptors into a
    /// bounded immutable bundle, the guard is revalidated, and only then are
    /// new files created. SHM is deliberately not copied: SQLite rebuilds it
    /// from the copied database/WAL. The caller must open and authenticate the
    /// copy against an independent current-cut witness before it can become an
    /// authoritative writer.
    pub fn materialize_identity_bound_recovery_copy(
        &self,
        guard: &ExistingSqliteRecoveryGuard,
        target: &std::path::Path,
    ) -> Result<(), SqliteRecoveryError> {
        #[cfg(unix)]
        {
            use super::RetainedOptionalObject;
            use std::fs::OpenOptions;
            use std::io::Write;
            use std::os::unix::fs::FileExt;
            use std::os::unix::fs::OpenOptionsExt;

            const MAX_DATABASE_BYTES: u64 = 128 * 1024 * 1024;
            const MAX_SIDECAR_BYTES: u64 = 128 * 1024 * 1024;
            const MAX_BUNDLE_BYTES: u64 = 256 * 1024 * 1024;

            if target.parent() != Some(self.home())
                || target == guard.inner.database_path
                || target.file_name().is_none()
            {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            guard.revalidate_for(self)?;

            fn retained_bytes(
                object: &super::RetainedObject,
                maximum: u64,
                allow_empty: bool,
            ) -> Result<Vec<u8>, SqliteRecoveryError> {
                let size = object
                    .descriptor
                    .metadata()
                    .map_err(super::indeterminate)?
                    .len();
                if (!allow_empty && size == 0) || size > maximum {
                    return Err(SqliteRecoveryError::Unavailable);
                }
                let size = usize::try_from(size).map_err(|_| SqliteRecoveryError::Unavailable)?;
                let mut bytes = vec![0; size];
                if !bytes.is_empty() {
                    object
                        .descriptor
                        .read_exact_at(&mut bytes, 0)
                        .map_err(super::indeterminate)?;
                }
                Ok(bytes)
            }

            fn optional_bytes(
                object: &RetainedOptionalObject,
            ) -> Result<Option<Vec<u8>>, SqliteRecoveryError> {
                match object {
                    RetainedOptionalObject::Absent(_) => Ok(None),
                    RetainedOptionalObject::Present(object) => {
                        retained_bytes(object, MAX_SIDECAR_BYTES, true).map(Some)
                    }
                }
            }

            let database = retained_bytes(&guard.inner.database, MAX_DATABASE_BYTES, false)?;
            let wal = optional_bytes(&guard.inner.sidecars[0])?;
            // sidecars[1] is SHM and is intentionally not copied.
            let journal = optional_bytes(&guard.inner.sidecars[2])?;
            let total = u64::try_from(database.len())
                .ok()
                .and_then(|value| {
                    value.checked_add(
                        wal.as_ref()
                            .and_then(|bytes| u64::try_from(bytes.len()).ok())
                            .unwrap_or(0),
                    )
                })
                .and_then(|value| {
                    value.checked_add(
                        journal
                            .as_ref()
                            .and_then(|bytes| u64::try_from(bytes.len()).ok())
                            .unwrap_or(0),
                    )
                })
                .ok_or(SqliteRecoveryError::Unavailable)?;
            if total > MAX_BUNDLE_BYTES {
                return Err(SqliteRecoveryError::Unavailable);
            }
            guard.revalidate_for(self)?;

            let target_wal = super::sqlite_sidecar_path(target, "-wal");
            let target_journal = super::sqlite_sidecar_path(target, "-journal");
            let mut created = Vec::new();
            let write_private = |path: &std::path::Path,
                                 bytes: &[u8]|
             -> Result<(), SqliteRecoveryError> {
                let mut file = OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .mode(0o600)
                    .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
                    .open(path)
                    .map_err(super::indeterminate)?;
                file.write_all(bytes).map_err(super::indeterminate)?;
                file.sync_all().map_err(super::indeterminate)
            };

            let result = (|| {
                write_private(target, &database)?;
                created.push(target.to_path_buf());
                if let Some(bytes) = wal.as_deref() {
                    write_private(&target_wal, bytes)?;
                    created.push(target_wal.clone());
                }
                if let Some(bytes) = journal.as_deref() {
                    write_private(&target_journal, bytes)?;
                    created.push(target_journal.clone());
                }
                let directory = std::fs::File::open(self.home()).map_err(super::indeterminate)?;
                directory.sync_all().map_err(super::indeterminate)?;
                Ok(())
            })();
            if result.is_err() {
                for path in created.into_iter().rev() {
                    let _ = std::fs::remove_file(path);
                }
            }
            result
        }
        #[cfg(not(unix))]
        {
            let _ = (guard, target);
            Err(SqliteRecoveryError::Unavailable)
        }
    }

    #[cfg_attr(
        unix,
        expect(
            clippy::disallowed_methods,
            reason = "this is codex-state's retained-descriptor cold-image connection shim"
        )
    )]
    pub async fn open_cold_image_read_only_pool(
        &self,
        guard: &ExistingSqliteRecoveryGuard,
    ) -> Result<SqlitePool, SqliteRecoveryError> {
        #[cfg(unix)]
        {
            use super::RetainedOptionalObject;
            use std::os::unix::fs::FileExt;
            use std::sync::Arc;

            guard.revalidate_for(self)?;
            if guard
                .inner
                .sidecars
                .iter()
                .any(|sidecar| matches!(sidecar, RetainedOptionalObject::Present(_)))
            {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            let size = guard
                .inner
                .database
                .descriptor
                .metadata()
                .map_err(super::indeterminate)?
                .len();
            if !(100..=128 * 1024 * 1024).contains(&size) {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            let mut bytes = vec![0; size as usize];
            guard
                .inner
                .database
                .descriptor
                .read_exact_at(&mut bytes, 0)
                .map_err(super::indeterminate)?;
            guard.revalidate_for(self)?;
            if &bytes[..16] != b"SQLite format 3\0"
                || !matches!((bytes[18], bytes[19]), (1, 1) | (2, 2))
            {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            // SQLite's documented deserialize workaround for a checkpointed
            // WAL-format database. Only our copy changes; absent sidecars alone
            // do NOT authenticate checkpoint completeness. The caller's full
            // independent current-cut comparison must still reject stale data.
            bytes[18] = 1;
            bytes[19] = 1;
            let image = Arc::new(bytes);
            let options = sqlx::sqlite::SqliteConnectOptions::new()
                .in_memory(true)
                .foreign_keys(true)
                .pragma("temp_store", "MEMORY")
                .pragma("query_only", "ON");
            let pool = sqlx::sqlite::SqlitePoolOptions::new()
                .max_connections(1)
                .acquire_timeout(std::time::Duration::from_secs(5))
                .after_connect(move |connection, _metadata| {
                    let image = Arc::clone(&image);
                    Box::pin(async move {
                        let mut handle = connection.lock_handle().await?;
                        // SAFETY: lock_handle excludes SQLx's worker. Allocate
                        // with SQLite's allocator, then copy exactly image.len
                        // bytes into that allocation. FREEONCLOSE transfers sole
                        // ownership to SQLite on success AND on error (SQLite
                        // frees P before returning failure). There is no await
                        // or fallible operation between allocation and transfer.
                        // READONLY prevents mutation, and RESIZEABLE is absent.
                        let result = unsafe {
                            let buffer =
                                libsqlite3_sys::sqlite3_malloc64(image.len() as u64).cast::<u8>();
                            if buffer.is_null() {
                                return Err(sqlx::Error::Protocol(
                                    "cold image allocation failed".into(),
                                ));
                            }
                            std::ptr::copy_nonoverlapping(image.as_ptr(), buffer, image.len());
                            libsqlite3_sys::sqlite3_deserialize(
                                handle.as_raw_handle().as_ptr(),
                                c"main".as_ptr(),
                                buffer,
                                image.len() as i64,
                                image.len() as i64,
                                libsqlite3_sys::SQLITE_DESERIALIZE_FREEONCLOSE
                                    | libsqlite3_sys::SQLITE_DESERIALIZE_READONLY,
                            )
                        };
                        if result != libsqlite3_sys::SQLITE_OK {
                            return Err(sqlx::Error::Protocol(format!(
                                "cold image deserialize failed: {result}"
                            )));
                        }
                        Ok(())
                    })
                })
                .connect_with(options)
                .await
                .map_err(|_| SqliteRecoveryError::Indeterminate)?;
            if let Err(error) = guard.revalidate_for(self) {
                pool.close().await;
                return Err(error);
            }
            Ok(pool)
        }
        #[cfg(not(unix))]
        {
            let _ = guard;
            Err(SqliteRecoveryError::Unavailable)
        }
    }
}

#[cfg(all(test, unix))]
#[path = "sqlite_recovery_image_tests.rs"]
mod tests;
