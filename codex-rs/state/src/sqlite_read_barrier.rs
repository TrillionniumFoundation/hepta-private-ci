//! Lock-only access to an existing owner database, never a second writer.

use crate::SqliteConfig;
use log::LevelFilter;
use sqlx::ConnectOptions;
use sqlx::Error;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::sqlite::SqliteSynchronous;
use std::path::Path;
use std::time::Duration;

/// Shares its owner's database and lifetime guard. Its private connections can
/// take SQLite's writer lock, but every commit is permanently rejected. Ordinary
/// observations should still use a physically read-only connection instead.
#[derive(Clone)]
pub struct SqliteReadBarrier {
    pool: SqlitePool,
}

impl SqliteConfig {
    /// Open only an existing owner database. This supplies neither an owner nor
    /// a recovery witness; the caller must retain the original recovery guard.
    pub async fn open_durable_read_barrier(&self, path: &Path) -> Result<SqliteReadBarrier, Error> {
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(false)
            .synchronous(SqliteSynchronous::Full)
            .foreign_keys(true)
            .busy_timeout(Duration::from_secs(5))
            .pragma("query_only", "ON")
            .log_statements(LevelFilter::Off);
        let pool = SqlitePoolOptions::new()
            .max_connections(1)
            .after_connect(|connection, _metadata| {
                Box::pin(async move {
                    connection.lock_handle().await?.set_commit_hook(|| false);
                    Ok(())
                })
            })
            .connect_with(options)
            .await?;
        Ok(SqliteReadBarrier { pool })
    }
}

impl SqliteReadBarrier {
    /// Hold the actual SQLite writer lock while allowing reads only. READONLY
    /// open flags silently make BEGIN IMMEDIATE a read transaction; query_only
    /// must instead be enabled after this READWRITE connection takes the lock.
    /// Every intermediate cancellation closes the connection, so the temporary
    /// query_only=OFF state can never return to the pool or a caller.
    pub async fn begin(&self) -> Result<Transaction<'static, Sqlite>, Error> {
        let mut connection = self.pool.acquire().await?;
        connection.close_on_drop();
        sqlx::query("PRAGMA query_only=OFF")
            .execute(&mut *connection)
            .await?;
        let mut transaction =
            Transaction::begin(connection, Some("BEGIN IMMEDIATE".into())).await?;
        sqlx::query("PRAGMA query_only=ON")
            .execute(&mut *transaction)
            .await?;
        Ok(transaction)
    }

    /// Drain all lock-only connections before releasing the owner's guard.
    pub async fn close(&self) {
        self.pool.close().await;
    }
}
