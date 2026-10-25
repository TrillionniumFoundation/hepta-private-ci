use pretty_assertions::assert_eq;
use std::time::Duration;

use super::SqliteConfig;

#[tokio::test]
async fn schema_fixture_pool_is_single_connection_isolated_and_closes() -> Result<(), sqlx::Error> {
    let pool = SqliteConfig::open_in_memory_pool_for_testing().await?;
    assert_eq!(pool.options().get_max_connections(), 1);
    let mut connection = pool.acquire().await?;
    assert!(pool.try_acquire().is_none());
    // No idle connection alone does not establish capacity: a real second
    // acquire must remain blocked while the only permitted slot is held.
    assert!(
        tokio::time::timeout(Duration::from_secs(1), pool.acquire())
            .await
            .is_err()
    );
    sqlx::query("CREATE TABLE fixture_identity (value INTEGER NOT NULL)")
        .execute(&mut *connection)
        .await?;
    sqlx::query("INSERT INTO fixture_identity VALUES (7)")
        .execute(&mut *connection)
        .await?;
    drop(connection);
    let released = tokio::time::timeout(Duration::from_secs(5), pool.acquire())
        .await
        .expect("released single-connection slot must become available")?;
    drop(released);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT value FROM fixture_identity")
            .fetch_one(&pool)
            .await?,
        7
    );

    let independent = SqliteConfig::open_in_memory_pool_for_testing().await?;
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM sqlite_schema WHERE name = 'fixture_identity'"
        )
        .fetch_one(&independent)
        .await?,
        0
    );
    independent.close().await;
    pool.close().await;
    assert!(independent.is_closed());
    assert!(pool.is_closed());
    assert!(matches!(pool.acquire().await, Err(sqlx::Error::PoolClosed)));
    Ok(())
}
