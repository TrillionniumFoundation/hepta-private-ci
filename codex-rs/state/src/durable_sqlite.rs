#![expect(
    clippy::disallowed_methods,
    reason = "this is the centralized SQLite connection shim"
)]

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

/// Open an authoritative SQLite owner database with the caller's explicit,
/// bounded connection budget while retaining the shared durability policy.
///
/// This is the low-level form used by owner crates whose resource contract is
/// narrower than [`crate::SqliteConfig::open_durable_evidence_pool`]. All pool
/// construction remains centralized in `codex-state`.
pub async fn open_durable_evidence_pool_with_limit(
    path: &Path,
    max_connections: u32,
) -> Result<SqlitePool, Error> {
    if max_connections == 0 {
        return Err(Error::Protocol(
            "durable SQLite connection limit must be nonzero".to_string(),
        ));
    }
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
