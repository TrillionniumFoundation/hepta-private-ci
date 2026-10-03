//! Effective connection-policy regressions at the real owner constructors.
use sqlx::SqlitePool;

pub(crate) async fn assert_operation_policy(pool: &SqlitePool) {
    assert_eq!(pool.options().get_max_connections(), 4);
    let mut connections = Vec::new();
    for _ in 0..4 {
        let mut connection = pool.acquire().await.expect("owner connection");
        let journal: String = sqlx::query_scalar("PRAGMA journal_mode")
            .fetch_one(&mut *connection)
            .await
            .expect("journal policy");
        let sync: i64 = sqlx::query_scalar("PRAGMA synchronous")
            .fetch_one(&mut *connection)
            .await
            .expect("sync policy");
        let foreign: i64 = sqlx::query_scalar("PRAGMA foreign_keys")
            .fetch_one(&mut *connection)
            .await
            .expect("foreign-key policy");
        let busy: i64 = sqlx::query_scalar("PRAGMA busy_timeout")
            .fetch_one(&mut *connection)
            .await
            .expect("busy policy");
        assert_eq!((journal.as_str(), sync, foreign, busy), ("wal", 2, 1, 5000));
        connections.push(connection);
    }
    assert!(
        pool.try_acquire().is_none(),
        "fifth connection must not escape owner bound"
    );
}

#[tokio::test]
async fn durable_operation_constructor_preserves_all_connection_policies() {
    let directory = tempfile::tempdir().expect("tempdir");
    let store = crate::DurableOperationStore::open(&directory.path().join("operations.sqlite3"))
        .await
        .expect("owner");
    assert_operation_policy(&store.pool).await;
    store.close().await;
}

#[tokio::test]
async fn fixture_inspection_never_creates_missing_history() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("missing.sqlite3");
    assert!(
        codex_state_test_support::open_existing_operation_fixture(&path)
            .await
            .is_err()
    );
    assert!(!path.exists());
}

#[tokio::test]
async fn page_fault_helper_rejects_a_different_pool_profile() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let store = crate::DurableOperationStore::open(&path)
        .await
        .expect("owner");
    store.close().await;
    let fixture = codex_state_test_support::open_existing_operation_fixture(&path)
        .await
        .expect("existing fixture");
    let result = codex_state_test_support::open_operation_page_limited_pool(
        &fixture,
        std::num::NonZeroU32::new(1).expect("positive page limit"),
    )
    .await;
    assert!(matches!(result, Err(sqlx::Error::Protocol(_))));
    fixture.close().await;
}
