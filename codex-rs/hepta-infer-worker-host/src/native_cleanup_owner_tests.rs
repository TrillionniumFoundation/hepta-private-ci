use super::*;

async fn connection(path: &Path) -> Result<sqlx::SqlitePool> {
    Ok(crate::sqlite::open_durable_pool(path).await?)
}

#[tokio::test]
async fn repeated_requests_reuse_the_owner_and_fresh_identity_changes_fail_closed() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("cleanup.sqlite3");
    let owner = NativeCleanupOwner::new(path.clone(), "agent-1".to_string(), 1);
    let first = owner.get().await?;
    first
        .enqueue(
            "operation-1".to_string(),
            "thread-1".to_string(),
            "session-1".to_string(),
        )
        .await?;
    let checked = owner
        .cached
        .lock()
        .await
        .as_ref()
        .ok_or("cached owner missing")?
        .integrity_at;
    for _ in 0..32 {
        let store = owner.get().await?;
        assert!(store.obligation("operation-1").await?.is_some());
        assert_eq!(
            owner
                .cached
                .lock()
                .await
                .as_ref()
                .ok_or("cached owner missing")?
                .integrity_at,
            checked
        );
    }
    let connection = connection(&path).await?;
    sqlx::query("UPDATE runtime_codex_cleanup_meta SET owner_id = 'other-agent'")
        .execute(&connection)
        .await?;
    assert!(owner.get().await.is_err());
    sqlx::query("UPDATE runtime_codex_cleanup_meta SET owner_id = 'agent-1'")
        .execute(&connection)
        .await?;
    assert!(owner.get().await.is_err());
    owner.maintain(Duration::from_secs(5)).await?;
    assert!(
        owner
            .get()
            .await?
            .obligation("operation-1")
            .await?
            .is_some()
    );
    Ok(())
}

#[tokio::test]
async fn full_integrity_quarantines_schema_changes_and_recovers_only_after_repair() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("cleanup.sqlite3");
    let owner = NativeCleanupOwner::new(path.clone(), "agent-1".to_string(), 1);
    owner.get().await?;
    let connection = connection(&path).await?;
    sqlx::query("DROP INDEX runtime_codex_cleanup_lease_idx")
        .execute(&connection)
        .await?;
    assert!(owner.get().await.is_err());
    assert!(owner.maintain(Duration::from_secs(5)).await.is_err());
    sqlx::query("CREATE INDEX runtime_codex_cleanup_lease_idx ON runtime_codex_cleanup_obligations(state, lease_until_ms)")
        .execute(&connection).await?;
    assert!(owner.get().await.is_err());
    owner.maintain(Duration::from_secs(5)).await?;
    assert!(owner.get().await.is_ok());
    Ok(())
}

#[cfg(unix)]
#[tokio::test]
async fn valid_atomic_file_replacement_requires_a_new_generation_owner() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("cleanup.sqlite3");
    let replacement = directory.path().join("replacement.sqlite3");
    let owner = NativeCleanupOwner::new(path.clone(), "agent-1".to_string(), 1);
    owner.get().await?;
    let connection = connection(&path).await?;
    sqlx::query("VACUUM INTO ?")
        .bind(replacement.to_string_lossy().as_ref())
        .execute(&connection)
        .await?;
    connection.close().await;
    std::fs::rename(replacement, &path)?;
    assert!(owner.get().await.is_err());
    assert!(owner.maintain(Duration::from_secs(5)).await.is_err());
    let restarted = NativeCleanupOwner::new(path, "agent-1".to_string(), 1);
    assert!(restarted.get().await.is_ok());
    Ok(())
}

#[expect(
    clippy::await_holding_invalid_type,
    reason = "holds the actual async owner gate to prove the maintenance deadline also bounds admission waiting"
)]
#[tokio::test]
async fn overdue_integrity_and_waiting_admission_obey_maintenance_budget() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let owner = NativeCleanupOwner::new(
        directory.path().join("cleanup.sqlite3"),
        "agent-1".to_string(),
        1,
    );
    owner.get().await?;
    owner
        .cached
        .lock()
        .await
        .as_mut()
        .ok_or("cached owner missing")?
        .integrity_at = Instant::now() - MAX_INTEGRITY_AGE;
    assert!(owner.get().await.is_err());
    let held = owner.cached.lock().await;
    let started = Instant::now();
    assert!(owner.maintain(Duration::from_millis(30)).await.is_err());
    assert!(started.elapsed() < Duration::from_secs(1));
    drop(held);
    owner.maintain(Duration::from_secs(5)).await?;
    assert!(owner.get().await.is_ok());
    Ok(())
}

#[cfg(unix)]
#[tokio::test]
async fn transient_invalid_file_identity_cannot_reenable_the_old_pool() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("cleanup.sqlite3");
    let link = directory.path().join("untrusted-link.sqlite3");
    let owner = NativeCleanupOwner::new(path.clone(), "agent-1".to_string(), 1);
    owner.get().await?;
    std::fs::hard_link(&path, &link)?;
    assert!(owner.get().await.is_err());
    std::fs::remove_file(link)?;
    assert!(owner.get().await.is_err());
    assert!(owner.maintain(Duration::from_secs(5)).await.is_err());
    let restarted = NativeCleanupOwner::new(path, "agent-1".to_string(), 1);
    assert!(restarted.get().await.is_ok());
    Ok(())
}
