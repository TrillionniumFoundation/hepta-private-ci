use super::*;
use crate::runtime::test_support::unique_temp_dir;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;
use sqlx::sqlite::SqliteAutoVacuum;

type TestResult = Result<(), Box<dyn std::error::Error>>;

#[tokio::test]
async fn fresh_database_selects_incremental_layout_before_wal_and_survives_reopen() -> TestResult {
    let home = unique_temp_dir();
    tokio::fs::create_dir_all(&home).await?;
    let sqlite = SqliteConfig::new_for_testing(home.as_path().abs());
    let path = sqlite.state_db_path();
    let pool = sqlite.open_read_write_pool(&path).await?;
    sqlx::query("CREATE TABLE original (value TEXT NOT NULL)")
        .execute(&pool)
        .await?;
    sqlx::query("INSERT INTO original VALUES ('original row')")
        .execute(&pool)
        .await?;
    let layout: i64 = sqlx::query_scalar("PRAGMA auto_vacuum")
        .fetch_one(&pool)
        .await?;
    let mode: String = sqlx::query_scalar("PRAGMA journal_mode")
        .fetch_one(&pool)
        .await?;
    assert_eq!((layout, mode), (2, "wal".to_string()));
    pool.close().await;
    let reopened = sqlite.open_read_write_pool(&path).await?;
    let row: String = sqlx::query_scalar("SELECT value FROM original")
        .fetch_one(&reopened)
        .await?;
    assert_eq!(row, "original row");
    let layout: i64 = sqlx::query_scalar("PRAGMA auto_vacuum")
        .fetch_one(&reopened)
        .await?;
    assert_eq!(layout, 2);
    reopened.close().await;
    tokio::fs::remove_dir_all(home).await?;
    Ok(())
}

#[tokio::test]
async fn existing_database_preserves_original_vacuum_layout_and_rows() -> TestResult {
    for (mode, expected) in [
        (SqliteAutoVacuum::None, 0_i64),
        (SqliteAutoVacuum::Full, 1),
        (SqliteAutoVacuum::Incremental, 2),
    ] {
        let home = unique_temp_dir();
        tokio::fs::create_dir_all(&home).await?;
        let sqlite = SqliteConfig::new_for_testing(home.as_path().abs());
        let path = sqlite.state_db_path();
        let mut original = SqliteConnectOptions::new()
            .filename(&path)
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Delete)
            .auto_vacuum(mode)
            .connect()
            .await?;
        sqlx::query("CREATE TABLE original (value TEXT NOT NULL)")
            .execute(&mut original)
            .await?;
        sqlx::query("INSERT INTO original VALUES ('retained legacy row')")
            .execute(&mut original)
            .await?;
        original.close().await?;
        let pool = sqlite.open_read_write_pool(&path).await?;
        let layout: i64 = sqlx::query_scalar("PRAGMA auto_vacuum")
            .fetch_one(&pool)
            .await?;
        let rows: Vec<String> = sqlx::query_scalar("SELECT value FROM original")
            .fetch_all(&pool)
            .await?;
        assert_eq!(
            (layout, rows),
            (expected, vec!["retained legacy row".to_string()])
        );
        pool.close().await;
        tokio::fs::remove_dir_all(home).await?;
    }
    Ok(())
}

#[tokio::test]
async fn owner_pool_limits_preserve_durability_and_read_only_observation() -> TestResult {
    let home = unique_temp_dir();
    tokio::fs::create_dir_all(&home).await?;
    let path = home.join("owner.sqlite3");
    let writer =
        SqliteConfig::open_owner_durable_evidence_pool(&path, /*max_connections*/ 4).await?;
    assert_eq!(writer.options().get_max_connections(), 4);
    // Both simultaneously retained connections must carry the owner's settings.
    let mut first = writer.acquire().await?;
    let mut second = writer.acquire().await?;
    for connection in [&mut first, &mut second] {
        let journal: String = sqlx::query_scalar("PRAGMA journal_mode")
            .fetch_one(&mut **connection)
            .await?;
        let sync: i64 = sqlx::query_scalar("PRAGMA synchronous")
            .fetch_one(&mut **connection)
            .await?;
        let foreign_keys: i64 = sqlx::query_scalar("PRAGMA foreign_keys")
            .fetch_one(&mut **connection)
            .await?;
        let busy: i64 = sqlx::query_scalar("PRAGMA busy_timeout")
            .fetch_one(&mut **connection)
            .await?;
        assert_eq!(
            (journal.as_str(), sync, foreign_keys, busy),
            ("wal", 2, 1, 5000)
        );
    }
    drop((first, second));
    sqlx::query("CREATE TABLE owner_history (value TEXT NOT NULL)")
        .execute(&writer)
        .await?;
    sqlx::query("INSERT INTO owner_history VALUES ('retained')")
        .execute(&writer)
        .await?;
    writer.close().await;

    let reader = SqliteConfig::open_owner_read_only_pool(
        &path,
        /*max_connections*/ 2,
        Duration::from_secs(1),
    )
    .await?;
    assert_eq!(reader.options().get_max_connections(), 2);
    let mut first = reader.acquire().await?;
    let mut second = reader.acquire().await?;
    for connection in [&mut first, &mut second] {
        let busy: i64 = sqlx::query_scalar("PRAGMA busy_timeout")
            .fetch_one(&mut **connection)
            .await?;
        assert_eq!(busy, 1000);
        let history: String = sqlx::query_scalar("SELECT value FROM owner_history")
            .fetch_one(&mut **connection)
            .await?;
        assert_eq!(history, "retained");
        assert!(
            sqlx::query("DELETE FROM owner_history")
                .execute(&mut **connection)
                .await
                .is_err()
        );
    }
    drop((first, second));
    reader.close().await;
    let writer =
        SqliteConfig::open_owner_durable_evidence_pool(&path, /*max_connections*/ 4).await?;
    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM owner_history")
        .fetch_one(&writer)
        .await?;
    assert_eq!(count, 1);
    writer.close().await;
    tokio::fs::remove_dir_all(home).await?;
    Ok(())
}

#[tokio::test]
async fn owner_pool_rejects_invalid_limits_and_missing_reader_without_creation() -> TestResult {
    let home = unique_temp_dir();
    tokio::fs::create_dir_all(&home).await?;
    let path = home.join("must-not-exist.sqlite3");
    assert!(matches!(
        SqliteConfig::open_owner_durable_evidence_pool(&path, /*max_connections*/ 0).await,
        Err(Error::Protocol(message)) if message == "SQLite pool requires a connection"
    ));
    assert!(!path.exists());
    for (connections, timeout) in [
        (0, Duration::from_secs(1)),
        (2, Duration::from_millis(i32::MAX as u64 + 1)),
    ] {
        assert!(matches!(
            SqliteConfig::open_owner_read_only_pool(&path, connections, timeout).await,
            Err(Error::Protocol(message)) if message == "invalid SQLite reader pool limits"
        ));
        assert!(!path.exists());
    }
    assert!(matches!(
        SqliteConfig::open_owner_read_only_pool(
            &path,
            /*max_connections*/ 2,
            Duration::from_secs(1)
        )
        .await,
        Err(Error::Database(_))
    ));
    assert!(!path.exists());
    assert_eq!(std::fs::read_dir(&home)?.count(), 0);
    tokio::fs::remove_dir_all(home).await?;
    Ok(())
}
