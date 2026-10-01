//! Shared, bounded connection policies for independently migrated evidence stores.
use std::path::Path;
use std::time::Duration;

use log::LevelFilter;
use sqlx::ConnectOptions;
use sqlx::Error;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteJournalMode;
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::sqlite::SqliteSynchronous;

/// An evidence owner's connection budget. Both policies retain WAL, FULL
/// synchronization, foreign keys and the shared five-second busy timeout.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableSqlitePoolCapacity {
    /// Retain the four-connection budget of existing operation stores.
    FourConnections,
    /// The existing five-connection evidence-store default.
    Default,
}

/// Open an evidence database through the central SQLite connection shim.
///
/// The caller owns migration, validation and recovery; this function never
/// rebuilds a corrupt authoritative database or weakens its durability policy.
pub async fn open_durable_evidence_pool_with_capacity(
    path: &Path,
    capacity: DurableSqlitePoolCapacity,
) -> Result<SqlitePool, Error> {
    let max_connections = match capacity {
        DurableSqlitePoolCapacity::FourConnections => 4,
        DurableSqlitePoolCapacity::Default => 5,
    };
    let options = SqliteConnectOptions::new()
        .filename(path)
        .create_if_missing(true)
        .journal_mode(SqliteJournalMode::Wal)
        .synchronous(SqliteSynchronous::Full)
        .foreign_keys(true)
        .busy_timeout(Duration::from_secs(5))
        .log_statements(LevelFilter::Off);
    SqlitePoolOptions::new()
        .max_connections(max_connections)
        .connect_with(options)
        .await
}

#[cfg(test)]
#[path = "sqlite_evidence_tests.rs"]
mod tests;
