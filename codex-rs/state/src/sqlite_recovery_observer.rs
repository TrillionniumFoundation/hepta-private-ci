//! Replay retained source bytes only in an internally owned disposable copy.
use super::ExistingSqliteRecoveryGuard;
use super::SqliteConfig;
use super::SqliteRecoveryError;
use sqlx::SqlitePool;

impl SqliteConfig {
    /// Recover a bounded retained DB/WAL bundle into an isolated READONLY memory
    /// image. The caller must authenticate its entire canonical schema and
    /// independent Current before trusting any row, then check integrity.
    /// No source SQLite connection, migration, active pointer or writer is made.
    /// The original cold API still refuses every sidecar.
    pub async fn open_wal_image_read_only_pool(
        &self,
        guard: &ExistingSqliteRecoveryGuard,
    ) -> Result<SqlitePool, SqliteRecoveryError> {
        guard.revalidate_for(self)?;
        #[cfg(unix)]
        {
            let source = guard.clone();
            // Dropping this await detaches the owned job; it must finish the
            // original SQLite close barrier before deleting its private copy.
            tokio::spawn(async move {
                let mut copy = PrivateCopy::new(&source)?;
                let config = SqliteConfig::from_sqlite_home(
                    codex_utils_absolute_path::AbsolutePathBuf::try_from(copy.path.clone())
                        .map_err(|_| SqliteRecoveryError::Indeterminate)?,
                );
                let database = copy.path.join("observer.sqlite3");
                let result = async {
                    config.materialize_retained_bundle(&source, &database)?;
                    copy.can_remove = false;
                    // This existing single-connection helper closes explicitly
                    // on success AND error. Internal copy replay/checkpoint is
                    // allowed; no external owner commit hook is bypassed.
                    let checkpoint = config.checkpoint_private_recovery_database(&database).await;
                    copy.can_remove = true;
                    checkpoint.map_err(|_| SqliteRecoveryError::Indeterminate)?;
                    let copied = config.bind_existing_recovery_database(&database)?;
                    let pool = config.open_cold_image_read_only_pool(&copied).await?;
                    if let Err(error) = source.verify_inspection_unchanged() {
                        pool.close().await;
                        return Err(error);
                    }
                    Ok(pool)
                }
                .await;
                if let Err(error) = copy.remove() {
                    if let Ok(pool) = result {
                        pool.close().await;
                    }
                    return Err(error);
                }
                result
            })
            .await
            .map_err(|_| SqliteRecoveryError::Indeterminate)?
        }
        #[cfg(not(unix))]
        {
            Err(SqliteRecoveryError::Unavailable)
        }
    }
}

#[cfg(unix)]
struct PrivateCopy {
    path: std::path::PathBuf,
    directory: std::fs::File,
    can_remove: bool,
}

#[cfg(unix)]
impl PrivateCopy {
    fn new(source: &ExistingSqliteRecoveryGuard) -> Result<Self, SqliteRecoveryError> {
        use std::os::unix::fs::DirBuilderExt;
        use std::os::unix::fs::OpenOptionsExt;
        let root = std::env::temp_dir()
            .canonicalize()
            .map_err(super::indeterminate)?;
        let source_root = source
            .inner
            .database_path
            .parent()
            .ok_or(SqliteRecoveryError::Indeterminate)?;
        if root.starts_with(source_root) {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        let path = root.join(format!(
            "codex-historical-observer-{}",
            uuid::Uuid::new_v4()
        ));
        std::fs::DirBuilder::new()
            .mode(0o700)
            .create(&path)
            .map_err(super::indeterminate)?;
        let directory = match std::fs::OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_DIRECTORY)
            .open(&path)
        {
            Ok(directory) => directory,
            Err(error) => {
                let _ = std::fs::remove_dir(&path);
                return Err(super::indeterminate(error));
            }
        };
        Ok(Self {
            path,
            directory,
            can_remove: true,
        })
    }

    fn remove(&mut self) -> Result<(), SqliteRecoveryError> {
        use std::os::unix::fs::MetadataExt;
        if !self.can_remove {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        let retained = self.directory.metadata().map_err(super::indeterminate)?;
        let current = std::fs::symlink_metadata(&self.path).map_err(super::indeterminate)?;
        if !current.is_dir() || (retained.dev(), retained.ino()) != (current.dev(), current.ino()) {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        std::fs::remove_dir_all(&self.path).map_err(super::indeterminate)?;
        self.can_remove = false;
        Ok(())
    }
}

#[cfg(unix)]
impl Drop for PrivateCopy {
    fn drop(&mut self) {
        // If a runtime shutdown/panic interrupts the SQLite close barrier,
        // leave a private orphan rather than deleting files beneath a worker.
        if self.can_remove {
            let _ = self.remove();
        }
    }
}
