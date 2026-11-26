use codex_hepta_operations::DestinationApplyTransaction;
use codex_hepta_operations::DestinationDedupeStore;
use codex_hepta_operations::DurableOperationError;
use codex_state::SqliteConfig;
use codex_state::SqliteReadBarrier;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;
use std::path::Path;

fn require_sqlite_codec<T>()
where
    T: sqlx::Type<Sqlite>,
    for<'query> T: sqlx::Encode<'query, Sqlite>,
    for<'row> T: sqlx::Decode<'row, Sqlite>,
{
}

async fn original_read_only_pool(
    config: &SqliteConfig,
    path: &Path,
) -> Result<SqlitePool, sqlx::Error> {
    config.open_read_only_pool(path).await
}

async fn original_history_pool(config: &SqliteConfig) -> anyhow::Result<SqlitePool> {
    codex_state::open_thread_history_db(config).await
}

async fn original_destination_pool(
    pool: SqlitePool,
) -> Result<DestinationDedupeStore, DurableOperationError> {
    DestinationDedupeStore::from_migrated_pool(pool).await
}

fn original_destination_transaction(
    apply: &mut DestinationApplyTransaction,
) -> Result<&mut Transaction<'static, Sqlite>, DurableOperationError> {
    apply.transaction()
}

async fn original_read_barrier_transaction(
    barrier: &SqliteReadBarrier,
) -> Result<Transaction<'static, Sqlite>, sqlx::Error> {
    barrier.begin().await
}

fn main() {
    require_sqlite_codec::<i64>();
    require_sqlite_codec::<Option<i64>>();
    require_sqlite_codec::<String>();
    require_sqlite_codec::<Vec<u8>>();
    let _ = original_read_only_pool;
    let _ = original_history_pool;
    let _ = original_destination_pool;
    let _ = original_destination_transaction;
    let _ = original_read_barrier_transaction;
}
