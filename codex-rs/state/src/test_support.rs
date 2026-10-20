//! Test-only SQLite fixtures shared by migration and schema convergence tests.

#![expect(
    clippy::disallowed_methods,
    reason = "the in-memory pool is an isolated fixture and never a production owner"
)]

use sqlx::Error;
use sqlx::SqlitePool;
use sqlx::sqlite::SqlitePoolOptions;

/// Open a single-connection in-memory pool for isolated schema fixtures.
///
/// The pool is intentionally not part of SqliteConfig: it has no durable
/// owner, path, migration policy, or production authority.
pub async fn open_in_memory_pool_for_testing() -> Result<SqlitePool, Error> {
    SqlitePoolOptions::new()
        .max_connections(1)
        .connect("sqlite::memory:")
        .await
}
