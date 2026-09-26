use super::*;

#[tokio::test]
async fn owner_pool_connections_preserve_full_durability_and_owner_schema() -> anyhow::Result<()> {
    let directory = crate::runtime::test_support::unique_temp_dir();
    std::fs::create_dir(&directory)?;
    let _cleanup = scopeguard::guard(directory.clone(), |path| {
        let _ = std::fs::remove_dir_all(path);
    });
    let path = directory.join("owner.sqlite");
    let pool = open_durable_sqlite_pool(&path, /*max_connections*/ 4).await?;
    let mut leases = Vec::new();
    for _ in 0..4 {
        leases.push(pool.acquire().await?);
    }
    for connection in &mut leases {
        let mode: String = sqlx::query_scalar("PRAGMA journal_mode")
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
            (mode.as_str(), sync, foreign_keys, busy),
            ("wal", 2, 1, 5_000)
        );
    }
    drop(leases);
    let tables: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'")
        .fetch_one(&pool)
        .await?;
    assert_eq!(
        tables, 0,
        "connection shim must not install a product schema"
    );
    sqlx::query("CREATE TABLE owner_fact (id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
        .execute(&pool)
        .await?;
    sqlx::query("INSERT INTO owner_fact VALUES (1, 'retained')")
        .execute(&pool)
        .await?;
    pool.close().await;
    let reopened = open_durable_sqlite_pool(&path, /*max_connections*/ 2).await?;
    let body: String = sqlx::query_scalar("SELECT body FROM owner_fact WHERE id = 1")
        .fetch_one(&reopened)
        .await?;
    assert_eq!(body, "retained");
    reopened.close().await;
    Ok(())
}

#[tokio::test]
async fn invalid_owner_pool_bound_does_not_create_a_database() -> anyhow::Result<()> {
    let directory = crate::runtime::test_support::unique_temp_dir();
    std::fs::create_dir(&directory)?;
    let _cleanup = scopeguard::guard(directory.clone(), |path| {
        let _ = std::fs::remove_dir_all(path);
    });
    let path = directory.join("absent.sqlite");
    assert!(
        open_durable_sqlite_pool(&path, /*max_connections*/ 0)
            .await
            .is_err()
    );
    assert!(!path.exists());
    Ok(())
}

#[tokio::test]
async fn in_memory_schema_reference_has_one_shared_connection() -> anyhow::Result<()> {
    assert!(open_in_memory_sqlite_pool(0).await.is_err());
    assert!(open_in_memory_sqlite_pool(2).await.is_err());
    let pool = open_in_memory_sqlite_pool(1).await?;
    sqlx::query("CREATE TABLE reference (id INTEGER PRIMARY KEY)")
        .execute(&pool)
        .await?;
    let tables: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM sqlite_master WHERE name = 'reference'")
            .fetch_one(&pool)
            .await?;
    assert_eq!(tables, 1);
    pool.close().await;
    Ok(())
}
