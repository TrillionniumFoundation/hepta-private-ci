//! A bounded copy of a retained cold descriptor, never a source-file writer.
//!
//! Identity checks detect drift, not an atomic snapshot. The consumer MUST
//! validate a complete independent current-cut witness on the immutable copy
//! before trusting any result. No WAL/journal replay or source mutation occurs.

use super::ExistingSqliteRecoveryGuard;
use super::SqliteConfig;
use super::SqliteRecoveryError;
use sqlx::SqlitePool;
use std::path::Path;
use std::sync::Arc;

/// One bounded immutable byte image captured from a retained SQLite descriptor.
///
/// The same bytes can be opened read-only for independent current-cut
/// verification and, only after that verification, written to a *new* private
/// file. The source database is never reopened by pathname and this type never
/// replaces or mutates it. Publishing/replacing a canonical route remains an
/// owner-layer operation that requires its own external writer fence.
#[derive(Clone, Debug)]
pub struct ColdSqliteRecoveryImage {
    bytes: Arc<[u8]>,
    guard: ExistingSqliteRecoveryGuard,
}

impl SqliteConfig {
    /// Capture at most 128 MiB from the retained descriptor with no SQLite
    /// sidecars present. Unix only.
    ///
    /// The returned bytes are normalized from a checkpointed WAL header to a
    /// rollback-journal header on the *copy* so the fresh image does not depend
    /// on absent WAL/SHM files. The complete logical current-cut witness still
    /// has to be validated by the consumer; this method grants no authority.
    pub fn capture_cold_recovery_image(
        &self,
        guard: &ExistingSqliteRecoveryGuard,
    ) -> Result<ColdSqliteRecoveryImage, SqliteRecoveryError> {
        #[cfg(unix)]
        {
            use super::RetainedOptionalObject;
            use std::os::unix::fs::FileExt;

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
            // WAL-format database. Only the retained immutable copy changes;
            // absent sidecars do NOT authenticate checkpoint completeness.
            bytes[18] = 1;
            bytes[19] = 1;
            Ok(ColdSqliteRecoveryImage {
                bytes: Arc::from(bytes),
                guard: guard.clone(),
            })
        }
        #[cfg(not(unix))]
        {
            let _ = guard;
            Err(SqliteRecoveryError::Unavailable)
        }
    }

    /// Copy at most 128 MiB from the retained descriptor, with no sidecars
    /// present, into a read-only SQLite memory image. Unix only.
    ///
    /// This compatibility entrypoint captures one immutable image and opens
    /// exactly those bytes. Consumers that may subsequently restore a fresh
    /// owner should call [`SqliteConfig::capture_cold_recovery_image`] directly
    /// so verification and fresh-file materialization use the same byte image.
    pub async fn open_cold_image_read_only_pool(
        &self,
        guard: &ExistingSqliteRecoveryGuard,
    ) -> Result<SqlitePool, SqliteRecoveryError> {
        self.capture_cold_recovery_image(guard)?
            .open_read_only_pool(self)
            .await
    }
}

impl ColdSqliteRecoveryImage {
    /// Open this exact retained byte image as a single-connection, read-only
    /// in-memory SQLite database. The source pathname is never opened.
    #[cfg_attr(
        unix,
        expect(
            clippy::disallowed_methods,
            reason = "this is codex-state's retained-descriptor cold-image connection shim"
        )
    )]
    pub async fn open_read_only_pool(
        &self,
        config: &SqliteConfig,
    ) -> Result<SqlitePool, SqliteRecoveryError> {
        #[cfg(unix)]
        {
            let image = Arc::clone(&self.bytes);
            self.guard.revalidate_for(config)?;
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
            if let Err(error) = self.guard.revalidate_for(config) {
                pool.close().await;
                return Err(error);
            }
            Ok(pool)
        }
        #[cfg(not(unix))]
        {
            let _ = config;
            Err(SqliteRecoveryError::Unavailable)
        }
    }

    /// Write these already-captured bytes to a new private file in the same
    /// configured SQLite home. The target MUST NOT exist and MUST NOT be the
    /// bound source path. The caller owns atomic publication/quarantine policy.
    ///
    /// The complete source identity is checked immediately before creating the
    /// new file. Afterwards only the bound database and sidecar identities are
    /// rechecked: creating the fresh sibling necessarily changes the parent
    /// directory timestamp, but it must not change the suspect source object.
    pub fn write_fresh_copy(
        &self,
        config: &SqliteConfig,
        target: &Path,
    ) -> Result<(), SqliteRecoveryError> {
        #[cfg(unix)]
        {
            use std::io::Write;
            use std::os::unix::fs::OpenOptionsExt;

            if target.parent() != Some(config.home())
                || target == self.guard.inner.database_path.as_path()
            {
                return Err(SqliteRecoveryError::Indeterminate);
            }
            self.guard.revalidate_for(config)?;
            let result = (|| {
                let mut file = std::fs::OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .mode(0o600)
                    .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
                    .open(target)
                    .map_err(super::indeterminate)?;
                file.write_all(self.bytes.as_ref())
                    .map_err(super::indeterminate)?;
                file.sync_all().map_err(super::indeterminate)?;
                let metadata = file.metadata().map_err(super::indeterminate)?;
                super::FileSnapshot::validated(&metadata, super::ObjectKind::PrivateFile)?;
                if metadata.len() != self.bytes.len() as u64 {
                    return Err(SqliteRecoveryError::Indeterminate);
                }
                Ok(())
            })();
            if result.is_err() {
                let _ = std::fs::remove_file(target);
                return result;
            }
            let source_result = self
                .guard
                .inner
                .database
                .revalidate()
                .and_then(|_| {
                    for sidecar in &self.guard.inner.sidecars {
                        sidecar.revalidate()?;
                    }
                    Ok(())
                });
            if let Err(error) = source_result {
                let _ = std::fs::remove_file(target);
                return Err(error);
            }
            Ok(())
        }
        #[cfg(not(unix))]
        {
            let _ = (config, target);
            Err(SqliteRecoveryError::Unavailable)
        }
    }
}

#[cfg(all(test, unix))]
#[path = "sqlite_recovery_image_tests.rs"]
mod tests;
