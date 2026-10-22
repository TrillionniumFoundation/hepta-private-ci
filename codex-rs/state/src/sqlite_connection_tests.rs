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
