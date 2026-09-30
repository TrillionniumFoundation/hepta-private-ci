use super::*;
use sqlx::Connection;
use sqlx::SqliteConnection;

async fn connection(path: &Path) -> SqliteConnection {
    SqliteConnection::connect_with(&sqlx::sqlite::SqliteConnectOptions::new().filename(path))
        .await
        .unwrap()
}

#[tokio::test]
async fn repeated_requests_reuse_the_owner_and_fresh_identity_changes_fail_closed() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("cleanup.sqlite3");
    let owner = NativeCleanupOwner::new(path.clone(), "agent-1".to_string(), 1);
    let first = owner.get().await.unwrap();
    first
        .enqueue(
            "operation-1".to_string(),
            "thread-1".to_string(),
            "session-1".to_string(),
        )
        .await
        .unwrap();
    let checked = owner.cached.lock().await.as_ref().unwrap().integrity_at;
    for _ in 0..32 {
        let store = owner.get().await.unwrap();
        assert!(store.obligation("operation-1").await.unwrap().is_some());
        assert_eq!(
            owner.cached.lock().await.as_ref().unwrap().integrity_at,
            checked
        );
    }
    let mut connection = connection(&path).await;
    sqlx::query("UPDATE runtime_codex_cleanup_meta SET owner_id = 'other-agent'")
        .execute(&mut connection)
        .await
        .unwrap();
    assert!(owner.get().await.is_err());
    sqlx::query("UPDATE runtime_codex_cleanup_meta SET owner_id = 'agent-1'")
        .execute(&mut connection)
        .await
        .unwrap();
    assert!(owner.get().await.is_err());
    owner.maintain(Duration::from_secs(5)).await.unwrap();
    assert!(
        owner
            .get()
            .await
            .unwrap()
            .obligation("operation-1")
            .await
            .unwrap()
            .is_some()
    );
}

#[tokio::test]
async fn full_integrity_quarantines_schema_changes_and_recovers_only_after_repair() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("cleanup.sqlite3");
    let owner = NativeCleanupOwner::new(path.clone(), "agent-1".to_string(), 1);
    owner.get().await.unwrap();
    let mut connection = connection(&path).await;
    sqlx::query("DROP INDEX runtime_codex_cleanup_lease_idx")
        .execute(&mut connection)
        .await
        .unwrap();
    assert!(owner.get().await.is_err());
    assert!(owner.maintain(Duration::from_secs(5)).await.is_err());
    sqlx::query("CREATE INDEX runtime_codex_cleanup_lease_idx ON runtime_codex_cleanup_obligations(state, lease_until_ms)")
        .execute(&mut connection).await.unwrap();
    assert!(owner.get().await.is_err());
    owner.maintain(Duration::from_secs(5)).await.unwrap();
    assert!(owner.get().await.is_ok());
}

#[cfg(unix)]
#[tokio::test]
async fn valid_atomic_file_replacement_requires_a_new_generation_owner() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("cleanup.sqlite3");
    let replacement = directory.path().join("replacement.sqlite3");
    let owner = NativeCleanupOwner::new(path.clone(), "agent-1".to_string(), 1);
    owner.get().await.unwrap();
    let mut connection = connection(&path).await;
    sqlx::query("VACUUM INTO ?")
        .bind(replacement.to_string_lossy().as_ref())
        .execute(&mut connection)
        .await
        .unwrap();
    connection.close().await.unwrap();
    std::fs::rename(replacement, &path).unwrap();
    assert!(owner.get().await.is_err());
    assert!(owner.maintain(Duration::from_secs(5)).await.is_err());
    let restarted = NativeCleanupOwner::new(path, "agent-1".to_string(), 1);
    assert!(restarted.get().await.is_ok());
}

#[tokio::test]
async fn overdue_integrity_and_waiting_admission_obey_maintenance_budget() {
    let directory = tempfile::tempdir().unwrap();
    let owner = NativeCleanupOwner::new(
        directory.path().join("cleanup.sqlite3"),
        "agent-1".to_string(),
        1,
    );
    owner.get().await.unwrap();
    owner.cached.lock().await.as_mut().unwrap().integrity_at = Instant::now() - MAX_INTEGRITY_AGE;
    assert!(owner.get().await.is_err());
    let held = owner.cached.lock().await;
    let started = Instant::now();
    assert!(owner.maintain(Duration::from_millis(30)).await.is_err());
    assert!(started.elapsed() < Duration::from_secs(1));
    drop(held);
    owner.maintain(Duration::from_secs(5)).await.unwrap();
    assert!(owner.get().await.is_ok());
}

#[cfg(unix)]
#[tokio::test]
async fn transient_invalid_file_identity_cannot_reenable_the_old_pool() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("cleanup.sqlite3");
    let link = directory.path().join("untrusted-link.sqlite3");
    let owner = NativeCleanupOwner::new(path.clone(), "agent-1".to_string(), 1);
    owner.get().await.unwrap();
    std::fs::hard_link(&path, &link).unwrap();
    assert!(owner.get().await.is_err());
    std::fs::remove_file(link).unwrap();
    assert!(owner.get().await.is_err());
    assert!(owner.maintain(Duration::from_secs(5)).await.is_err());
    let restarted = NativeCleanupOwner::new(path, "agent-1".to_string(), 1);
    assert!(restarted.get().await.is_ok());
}
