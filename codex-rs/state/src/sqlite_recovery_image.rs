//! A bounded copy of a retained cold descriptor, never a source-file writer.
//!
//! Identity checks detect drift, not an atomic snapshot. The consumer MUST
//! validate a complete independent current-cut witness on the immutable copy
//! before trusting any result. No WAL/journal replay or source mutation occurs.

use super::ExistingSqliteRecoveryGuard;
use super::SqliteConfig;
use super::SqliteRecoveryError;
use sqlx::SqlitePool;

impl SqliteConfig {
    /// Copy at most 128 MiB from the retained descriptor, with no sidecars
    /// present, into a read-only SQLite memory image. Unix only.
    ///
    /// This low-level pool does not authenticate its contents or grant recovery
    /// authority. Every replacement connection receives the SAME copied bytes;
    /// no connection ever reopens the source filename. Its main database cannot
    /// be written even if query_only is disabled. The trusted consumer must keep
    /// the pool private and compare the complete canonical cut before use.
    /// The 128 MiB limit is on input bytes, not total memory: the retained copy
    /// and SQLite-owned copy consume up to 256 MiB together, plus SQLite caches,
    /// query results and validation allocations. It is not a latency guarantee.
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
