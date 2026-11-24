//! Explicit creation ownership for callers that already require private files.
//!
//! This does not authenticate a pathname, bind a writer fence, or replace the
//! independent current-cut checks used by recovery. Generic SqliteConfig entry
//! points continue to select the stock VFS.

#![expect(
    clippy::disallowed_methods,
    reason = "this is the explicit private-owner branch of the centralized SQLite shim"
)]

use crate::SqliteConfig;
use log::LevelFilter;
use sqlx::ConnectOptions;
use sqlx::Error;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteAutoVacuum;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteJournalMode;
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::sqlite::SqliteSynchronous;
use std::path::Path;
use std::time::Duration;

pub(super) fn with_private_owner(
    options: SqliteConnectOptions,
) -> Result<SqliteConnectOptions, Error> {
    #[cfg(windows)]
    {
        let name = libsqlite3_sys::hepta_win32_owner_vfs_name().map_err(|code| {
            Error::Protocol(format!(
                "private SQLite creation owner is unavailable: {code}"
            ))
        })?;
        let name = name.to_str().map_err(|error| {
            Error::Protocol(format!("invalid private SQLite VFS name: {error}"))
        })?;
        Ok(options.vfs(name))
    }
    #[cfg(not(windows))]
    {
        Ok(options)
    }
}

impl SqliteConfig {
    /// Open a private writable database using the ordinary state-DB settings.
    ///
    /// The caller owns private-directory and pathname validation. On Windows
    /// creation explicitly uses the effective TokenUser owner; failure never
    /// falls back to the stock VFS. Unix behavior matches the existing opener.
    pub async fn open_private_read_write_pool(&self, path: &Path) -> Result<SqlitePool, Error> {
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Normal)
            .auto_vacuum(SqliteAutoVacuum::Incremental)
            .busy_timeout(Duration::from_secs(5))
            .log_statements(LevelFilter::Off);
        SqlitePoolOptions::new()
            .max_connections(5)
            .connect_with(with_private_owner(options)?)
            .await
    }

    /// Open an explicitly private evidence store with full synchronous durability.
    ///
    /// This adds creation ownership, not a current-cut or source-identity proof.
    /// Recovery authorities must continue to use their existing independent
    /// guards and reject unsupported identity-bound operations.
    pub async fn open_private_durable_evidence_pool(
        &self,
        path: &Path,
    ) -> Result<SqlitePool, Error> {
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Full)
            .foreign_keys(true)
            .busy_timeout(Duration::from_secs(5))
            .log_statements(LevelFilter::Off);
        SqlitePoolOptions::new()
            .max_connections(5)
            .connect_with(with_private_owner(options)?)
            .await
    }
}

#[cfg(all(test, windows))]
#[path = "sqlite_private_owner_windows_tests.rs"]
mod windows_tests;
