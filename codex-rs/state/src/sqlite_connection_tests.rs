use super::*;
use crate::runtime::test_support::unique_temp_dir;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn durable_owner_pools_preserve_every_connections_durability_and_capacity()
-> anyhow::Result<()> {
    for maximum in [4_u32, 5_u32] {
        let home = unique_temp_dir();
        std::fs::create_dir(&home)?;
        let pool =
            open_durable_sqlite_pool(&home.join("owner.sqlite3"), NonZeroU32::try_from(maximum)?)
                .await?;
        let mut connections = Vec::new();
        for _ in 0..maximum {
            let mut connection = pool.acquire().await?;
            let journal: String = sqlx::query_scalar("PRAGMA journal_mode")
                .fetch_one(&mut *connection)
                .await?;
            let synchronous: i64 = sqlx::query_scalar("PRAGMA synchronous")
                .fetch_one(&mut *connection)
                .await?;
            let foreign_keys: i64 = sqlx::query_scalar("PRAGMA foreign_keys")
                .fetch_one(&mut *connection)
                .await?;
            let busy_timeout: i64 = sqlx::query_scalar("PRAGMA busy_timeout")
                .fetch_one(&mut *connection)
                .await?;
            assert_eq!(
                (journal, synchronous, foreign_keys, busy_timeout),
                ("wal".to_string(), 2, 1, 5000)
            );
            connections.push(connection);
        }
        assert!(
            tokio::time::timeout(Duration::from_millis(50), pool.acquire())
                .await
                .is_err()
        );
        drop(connections);
        sqlx::query("CREATE TABLE parent(id INTEGER PRIMARY KEY); CREATE TABLE child(parent_id INTEGER REFERENCES parent(id))").execute(&pool).await?;
        assert!(
            sqlx::query("INSERT INTO child VALUES (42)")
                .execute(&pool)
                .await
                .is_err()
        );
        pool.close().await;
        let reopened =
            open_durable_sqlite_pool(&home.join("owner.sqlite3"), NonZeroU32::try_from(maximum)?)
                .await?;
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM child")
            .fetch_one(&reopened)
            .await?;
        assert_eq!(count, 0);
        reopened.close().await;
        std::fs::remove_dir_all(home)?;
    }
    Ok(())
}

#[tokio::test]
async fn schema_reference_pools_are_isolated_and_limited_to_one_connection() -> anyhow::Result<()> {
    let first = open_sqlite_schema_reference_pool().await?;
    let second = open_sqlite_schema_reference_pool().await?;
    sqlx::query("CREATE TABLE compiled_schema_only(value TEXT)")
        .execute(&first)
        .await?;
    let missing: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM sqlite_schema WHERE name='compiled_schema_only'")
            .fetch_one(&second)
            .await?;
    assert_eq!(missing, 0);
    let database: String =
        sqlx::query_scalar("SELECT file FROM pragma_database_list WHERE name='main'")
            .fetch_one(&first)
            .await?;
    assert_eq!(database, String::new());
    let connection = first.acquire().await?;
    assert!(
        tokio::time::timeout(Duration::from_millis(50), first.acquire())
            .await
            .is_err()
    );
    drop(connection);
    first.close().await;
    second.close().await;
    Ok(())
}
