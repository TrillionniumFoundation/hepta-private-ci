//! The non-authoritative in-memory SQLite schema oracle.
//! Durable authority storage uses the central profile in `sqlite`.

use sqlx::Error;
use sqlx::SqlitePool;
use sqlx::sqlite::SqlitePoolOptions;

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
