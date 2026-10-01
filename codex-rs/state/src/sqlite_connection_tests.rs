use super::*;
use crate::runtime::test_support::unique_temp_dir;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn read_write_pool_cold_connections_observe_under_external_writer_and_preserve_vacuum_modes()
-> anyhow::Result<()> {
    for (vacuum_mode, maintenance) in [
        (0_i64, "PRAGMA auto_vacuum=NONE; VACUUM"),
        (1, "PRAGMA auto_vacuum=FULL; VACUUM"),
        (2, "PRAGMA auto_vacuum=INCREMENTAL; VACUUM"),
    ] {
        let home = unique_temp_dir();
        std::fs::create_dir(&home)?;
        let sqlite = SqliteConfig::new_for_testing(home.as_path().abs());
        let path = sqlite.state_db_path();
        let seed = sqlite.open_read_write_pool(&path).await?;
        let initial_mode: i64 = sqlx::query_scalar("PRAGMA auto_vacuum")
            .fetch_one(&seed)
            .await?;
        assert_eq!(initial_mode, 2, "new databases use incremental vacuum");
        sqlx::query("CREATE TABLE committed(value TEXT); INSERT INTO committed VALUES ('before')")
            .execute(&seed)
            .await?;
        // Construct actual existing layouts, including NONE which requires
        // deliberate maintenance to retrofit. Production never runs VACUUM.
        sqlx::query(maintenance).execute(&seed).await?;
        seed.close().await;

        let writer_pool = sqlite.open_read_write_pool(&path).await?;
        let mut writer = writer_pool.begin_with("BEGIN IMMEDIATE").await?;
        sqlx::query("UPDATE committed SET value='uncommitted'")
            .execute(&mut *writer)
            .await?;
        let observer = tokio::time::timeout(
            Duration::from_secs(/*secs*/ 1),
            sqlite.open_read_write_pool(&path),
        )
        .await
        .expect("opening an existing WAL pool must not take the SQLite writer lock")?;
        let mut connections = Vec::new();
        for _ in 0..5 {
            // Retain every acquired connection so the next one must open a
            // cold physical connection while another pool holds the writer.
            let mut connection =
                tokio::time::timeout(Duration::from_secs(/*secs*/ 1), observer.acquire())
                    .await
                    .expect("cold read connection must not take the SQLite writer lock")?;
            let value: String = sqlx::query_scalar("SELECT value FROM committed")
                .fetch_one(&mut *connection)
                .await?;
            let mode: i64 = sqlx::query_scalar("PRAGMA auto_vacuum")
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
            assert_eq!(value, "before");
            assert_eq!(
                (mode, synchronous, foreign_keys, busy_timeout),
                (vacuum_mode, 1, 1, 5000)
            );
            connections.push(connection);
        }
        writer.rollback().await?;
        drop(connections);
        observer.close().await;
        writer_pool.close().await;
        std::fs::remove_dir_all(home)?;
    }
    Ok(())
}

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
