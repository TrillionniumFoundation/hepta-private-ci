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
