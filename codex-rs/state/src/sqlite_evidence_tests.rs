use super::*;
use crate::SqliteConfig;
use crate::runtime::test_support::unique_temp_dir;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn bounded_evidence_pool_retains_durability_on_each_connection() -> anyhow::Result<()> {
    let root = unique_temp_dir();
    std::fs::create_dir_all(&root)?;
    scopeguard::defer! {
        let _ = std::fs::remove_dir_all(&root);
    }
    let pool = open_durable_evidence_pool_with_capacity(
        &root.join("evidence.sqlite"),
        DurableSqlitePoolCapacity::FourConnections,
    )
    .await?;
    assert_eq!(pool.options().get_max_connections(), 4);
    let mut connections = Vec::new();
    for _ in 0..4 {
        connections.push(pool.acquire().await?);
    }
    for connection in &mut connections {
        let journal: String = sqlx::query_scalar("PRAGMA journal_mode")
            .fetch_one(&mut **connection)
            .await?;
        let synchronous: i64 = sqlx::query_scalar("PRAGMA synchronous")
            .fetch_one(&mut **connection)
            .await?;
        let foreign_keys: i64 = sqlx::query_scalar("PRAGMA foreign_keys")
            .fetch_one(&mut **connection)
            .await?;
        let busy_timeout: i64 = sqlx::query_scalar("PRAGMA busy_timeout")
            .fetch_one(&mut **connection)
            .await?;
        assert_eq!(
            (journal, synchronous, foreign_keys, busy_timeout),
            ("wal".to_owned(), 2, 1, 5000)
        );
    }
    drop(connections);
    pool.close().await;
    Ok(())
}

#[tokio::test]
async fn default_evidence_pool_budget_remains_five_connections() -> anyhow::Result<()> {
    let root = unique_temp_dir();
    std::fs::create_dir_all(&root)?;
    scopeguard::defer! {
        let _ = std::fs::remove_dir_all(&root);
    }
    let config = SqliteConfig::new_for_testing(root.as_path().abs());
    let pool = config
        .open_durable_evidence_pool(&root.join("default.sqlite"))
        .await?;
    assert_eq!(pool.options().get_max_connections(), 5);
    let mut connections = Vec::new();
    for _ in 0..5 {
        connections.push(pool.acquire().await?);
    }
    assert_eq!(connections.len(), 5);
    drop(connections);
    pool.close().await;
    Ok(())
}
