use std::path::Path;
use std::time::Duration;

use sqlx::SqlitePool;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteJournalMode;
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::sqlite::SqliteSynchronous;

use crate::AuthBusAuthorityError;
use crate::authority_store::storage;

/// Open the one durable SQLite pool owned by AuthBus.
///
/// Persistent store call sites must use this private constructor rather than
/// selecting connection policy independently. The exception is deliberately
/// localized here until AuthBus can consume the workspace state shim without
/// importing the unrelated architecture candidate and lockfile graph into this
/// bounded platform.wire convergence branch.
#[allow(
    clippy::disallowed_methods,
    reason = "single audited AuthBus durable SQLite construction boundary"
)]
pub(crate) async fn open_durable_pool(path: &Path) -> Result<SqlitePool, AuthBusAuthorityError> {
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
        .map_err(storage)
}
