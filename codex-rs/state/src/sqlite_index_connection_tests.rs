use super::SqliteConfig;
use crate::runtime::test_support::create_private_test_directory;
use crate::runtime::test_support::unique_temp_dir;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use sqlx::Connection;

#[tokio::test]
async fn existing_index_connection_does_not_create_a_missing_database() -> anyhow::Result<()> {
    let temp = scopeguard::guard(unique_temp_dir(), |path| {
        let _ = std::fs::remove_dir_all(path);
    });
    create_private_test_directory(&temp)?;
    let config = SqliteConfig::from_sqlite_home(AbsolutePathBuf::try_from(temp.as_path())?);

    assert!(config.open_existing_state_db_connection().await.is_err());
    assert!(!config.state_db_path().exists());
    Ok(())
}

#[tokio::test]
async fn existing_index_connection_preserves_journal_and_enforces_foreign_keys()
-> anyhow::Result<()> {
    let temp = scopeguard::guard(unique_temp_dir(), |path| {
        let _ = std::fs::remove_dir_all(path);
    });
    create_private_test_directory(&temp)?;
    let config = SqliteConfig::from_sqlite_home(AbsolutePathBuf::try_from(temp.as_path())?);
    let pool = config.open_read_write_pool(&config.state_db_path()).await?;
    sqlx::raw_sql(
        "CREATE TABLE parent (id INTEGER PRIMARY KEY);
         CREATE TABLE child (parent_id INTEGER REFERENCES parent(id));
         INSERT INTO parent VALUES (7);",
    )
    .execute(&pool)
    .await?;
    let journal: String = sqlx::query_scalar("PRAGMA journal_mode=DELETE")
        .fetch_one(&pool)
        .await?;
    assert_eq!(journal, "delete");
    pool.close().await;

    let mut connection = config.open_existing_state_db_connection().await?;
    let journal: String = sqlx::query_scalar("PRAGMA journal_mode")
        .fetch_one(&mut connection)
        .await?;
    assert_eq!(journal, "delete");
    assert!(
        sqlx::query("INSERT INTO child VALUES (8)")
            .execute(&mut connection)
            .await
            .is_err()
    );
    sqlx::query("INSERT INTO child VALUES (7)")
        .execute(&mut connection)
        .await?;
    let rows: Vec<i64> = sqlx::query_scalar("SELECT parent_id FROM child")
        .fetch_all(&mut connection)
        .await?;
    assert_eq!(rows, vec![7]);
    connection.close().await?;
    Ok(())
}
