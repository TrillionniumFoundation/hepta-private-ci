//! Actual SQLite locking for the same managed owner; no protected-host fixture
//! claim is used as evidence that SQLite excluded a competing transaction.

use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn protected_checkpoint_barrier_excludes_writers_without_dirtying_current() {
    let fixture = ManagedFixture::new().await;
    fixture.sender().acknowledge_owner_cut().await.unwrap();
    let before = fixture.peer.receipt.lock().unwrap().clone();
    let mut barrier = fixture.store.begin_checkpoint_barrier().await.unwrap();
    assert_eq!(
        crate::cognitive_store::capture_recovery_anchor(
            &mut barrier,
            fixture.writer.owner_agent_id()
        )
        .await
        .unwrap(),
        before.head.last_current
    );
    for statement in [
        "CREATE TABLE checkpoint_forbidden_write(v INTEGER)",
        "DELETE FROM cognitive_meta",
    ] {
        let error = sqlx::query(statement)
            .execute(&mut *barrier)
            .await
            .unwrap_err();
        assert_eq!(
            error.as_database_error().unwrap().code().as_deref(),
            Some("8"),
            "lock-only observations must reject write statements"
        );
    }
    assert_eq!(*fixture.peer.receipt.lock().unwrap(), before);

    // A normal original-owner checkout may now mark Dirty. With zero SQLite
    // busy timeout this proves real exclusion, not merely slow task scheduling.
    let mut competitor = fixture.store.pool.acquire().await.unwrap();
    competitor.close_on_drop();
    sqlx::query("PRAGMA busy_timeout=0")
        .execute(&mut *competitor)
        .await
        .unwrap();
    let error = sqlx::query("BEGIN IMMEDIATE")
        .execute(&mut *competitor)
        .await
        .unwrap_err();
    assert_eq!(
        error.as_database_error().unwrap().code().as_deref(),
        Some("5"),
        "the actual writer lock must return SQLITE_BUSY before barrier release"
    );
    barrier.rollback().await.unwrap();
    sqlx::query("BEGIN IMMEDIATE")
        .execute(&mut *competitor)
        .await
        .unwrap();
    sqlx::query("ROLLBACK")
        .execute(&mut *competitor)
        .await
        .unwrap();
    assert_eq!(
        fixture.store.recovery_anchor().await.unwrap(),
        before.head.last_current
    );
}

#[tokio::test]
async fn protected_checkpoint_barrier_cancelled_acquisition_cannot_return_write_mode() {
    let fixture = ManagedFixture::new().await;
    let blocking = fixture
        .store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .unwrap();
    let store = fixture.store.clone();
    let mut acquiring = tokio::spawn(async move { store.begin_checkpoint_barrier().await });
    assert!(
        tokio::time::timeout(Duration::from_millis(20), &mut acquiring)
            .await
            .is_err()
    );
    acquiring.abort();
    assert!(acquiring.await.unwrap_err().is_cancelled());
    blocking.rollback().await.unwrap();
    let mut barrier = tokio::time::timeout(
        Duration::from_secs(5),
        fixture.store.begin_checkpoint_barrier(),
    )
    .await
    .unwrap()
    .unwrap();
    let query_only: i64 = sqlx::query_scalar("PRAGMA query_only")
        .fetch_one(&mut *barrier)
        .await
        .unwrap();
    assert_eq!(query_only, 1);
    let error = sqlx::query("CREATE TABLE checkpoint_cancelled_write(v INTEGER)")
        .execute(&mut *barrier)
        .await
        .unwrap_err();
    assert_eq!(
        error.as_database_error().unwrap().code().as_deref(),
        Some("8")
    );
    barrier.rollback().await.unwrap();
    assert!(!fixture.store.commit_gate.is_fenced());
}

#[tokio::test]
async fn protected_checkpoint_barrier_never_commits_even_if_query_only_is_disabled() {
    let fixture = ManagedFixture::new().await;
    let before = fixture.store.recovery_anchor().await.unwrap();
    let mut barrier = fixture.store.begin_checkpoint_barrier().await.unwrap();
    sqlx::query("PRAGMA query_only=OFF")
        .execute(&mut *barrier)
        .await
        .unwrap();
    sqlx::query("CREATE TABLE checkpoint_forbidden_commit(v INTEGER)")
        .execute(&mut *barrier)
        .await
        .unwrap();
    let error = barrier.commit().await.unwrap_err();
    assert_eq!(
        error.as_database_error().unwrap().code().as_deref(),
        Some("531"),
        "per-connection commit rejection must be independent of owner Dirty permission"
    );
    let count: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM sqlite_schema WHERE name='checkpoint_forbidden_commit'",
    )
    .fetch_one(fixture.store.observation_pool())
    .await
    .unwrap();
    assert_eq!(count, 0);
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), before);
}
