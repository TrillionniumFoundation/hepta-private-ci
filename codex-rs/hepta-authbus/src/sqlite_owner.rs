//! The single SQLite pool-construction boundary owned by AuthBus.
//!
//! AuthBus is a lower-level authority contract and intentionally does not take
//! a dependency on the broader state runtime. Keeping the two approved pool
//! profiles here prevents individual stores from selecting weaker durability,
//! foreign-key, or busy-timeout settings.

use std::path::Path;
use std::time::Duration;

use sqlx::Error;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteJournalMode;
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::sqlite::SqliteSynchronous;

#[expect(
    clippy::disallowed_methods,
    reason = "AuthBus owner-local SQLite construction is centralized in this function"
)]
pub(crate) async fn open_in_memory_pool() -> Result<SqlitePool, Error> {
    SqlitePoolOptions::new()
        .max_connections(1)
        .connect("sqlite::memory:")
        .await
}

#[expect(
    clippy::disallowed_methods,
    reason = "AuthBus owner-local SQLite construction is centralized in this function"
)]
pub(crate) async fn open_durable_pool(path: &Path) -> Result<SqlitePool, Error> {
    let options = SqliteConnectOptions::new()
        .filename(path)
        .create_if_missing(true)
        .journal_mode(SqliteJournalMode::Wal)
        .synchronous(SqliteSynchronous::Full)
        .foreign_keys(true)
        .busy_timeout(Duration::from_secs(5));
    SqlitePoolOptions::new()
        .max_connections(5)
        .connect_with(options)
        .await
}
