use std::future::Future;
use std::task::Context;
use std::task::Waker;

use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::CognitiveStore;
use super::CognitiveStoreError;
use super::CognitiveStoreOpenGuard;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::LocalAdmission;
use crate::LocalLeaseOutboxError;
use crate::LocalOutcomeState;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::source;
use crate::cognitive_test_support::workspace;

#[tokio::test]
async fn close_marks_clone_pool_immediately_and_retains_recovery_guard_until_drop() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(/*suffix*/ 71);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let clone = store.clone();
    let root = store.path().parent().expect("root").to_path_buf();

    let closing = store.close();
    // Deliberately inspect before polling: an async-fn wrapper would defer this.
    assert!(store.pool.is_closed());
    assert!(clone.pool.is_closed());
    assert!(matches!(
        clone.pool.acquire().await,
        Err(sqlx::Error::PoolClosed)
    ));
    closing.await;
    assert!(matches!(
        CognitiveStoreOpenGuard::acquire_exclusive(&root),
        Err(CognitiveStoreError::Unavailable(_))
    ));

    drop(store);
    assert!(matches!(
        CognitiveStoreOpenGuard::acquire_exclusive(&root),
        Err(CognitiveStoreError::Unavailable(_))
    ));
    drop(clone);
    let _exclusive = CognitiveStoreOpenGuard::acquire_exclusive(&root)
        .expect("last store handle dropped its recovery guard");
}

#[derive(Debug, PartialEq, sqlx::FromRow)]
struct StoredSource {
    source_id: String,
    source_revision: i64,
    owner_agent_id: String,
    scope_kind: String,
    workspace_sha256: Option<String>,
    source_kind: String,
    content: Vec<u8>,
    content_sha256: String,
    observed_at_unix_seconds: i64,
    recorded_at_unix_seconds: i64,
}

#[tokio::test]
async fn close_waits_for_checked_out_transaction_commit_and_preserves_all_source_fields() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(/*suffix*/ 72);
    let owner_layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&owner_layout).await.expect("store");
    let workspace_sha256 = workspace("close-persistence");
    let access = CognitiveAccess::workspace_private(owner, workspace_sha256.clone());
    let draft = source(
        CognitiveScope::WorkspacePrivate { workspace_sha256 },
        "close-checked-out-commit",
        "committed before the pool finishes closing",
    );
    let mut transaction = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("transaction");
    let appended = store
        .append_source_tx(&mut transaction, &access, &draft)
        .await
        .expect("append inside checked-out transaction");
    let expected: Vec<StoredSource> = sqlx::query_as(
        "SELECT source_id, source_revision, owner_agent_id, scope_kind, workspace_sha256,
                source_kind, content, content_sha256, observed_at_unix_seconds,
                recorded_at_unix_seconds FROM source_ledger",
    )
    .fetch_all(&mut *transaction)
    .await
    .expect("read every stored source field before closing");
    assert_eq!(expected.len(), 1);

    let mut closing = Box::pin(store.close());
    assert!(
        closing
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
            .is_pending()
    );
    transaction
        .commit()
        .await
        .expect("checked-out transaction can commit");
    closing.await;
    drop(store);

    let reopened = CognitiveStore::open(&owner_layout).await.expect("reopen");
    let persisted: Vec<StoredSource> = sqlx::query_as(
        "SELECT source_id, source_revision, owner_agent_id, scope_kind, workspace_sha256,
                source_kind, content, content_sha256, observed_at_unix_seconds,
                recorded_at_unix_seconds FROM source_ledger",
    )
    .fetch_all(&reopened.pool)
    .await
    .expect("read persisted source without replaying the write");
    // Compare all ten stored fields, including the recorded timestamp, before
    // replay can accidentally recreate a missing row and hide a persistence bug.
    assert_eq!(persisted, expected);
    assert_eq!(
        reopened
            .append_source(&access, &draft)
            .await
            .expect("idempotent replay"),
        appended
    );
    reopened.close().await;
}

#[tokio::test]
async fn close_cancelled_before_pool_drain_can_be_retried_and_is_idempotent() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(/*suffix*/ 73);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let clone = store.clone();
    let checked_out = store.pool.acquire().await.expect("hold a pool permit");
    let mut closing = Box::pin(store.close());

    // Sqlx 0.9.0 first acquires all five permits for this non-child pool.
    // Holding one makes this poll stop before idle-connection draining; this
    // does not exercise cancellation inside SQLite worker shutdown.
    assert!(
        closing
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
            .is_pending()
    );
    drop(closing);
    assert!(store.pool.is_closed());
    assert!(clone.pool.is_closed());
    assert!(matches!(
        clone.pool.acquire().await,
        Err(sqlx::Error::PoolClosed)
    ));

    drop(checked_out);
    store.close().await;
    clone.close().await;
    store.close().await;
}

#[tokio::test]
async fn close_does_not_close_independently_opened_pool_for_same_database() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(/*suffix*/ 74);
    let owner_layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&owner_layout)
        .await
        .expect("first pool");
    let clone = store.clone();
    let independent = CognitiveStore::open(&owner_layout)
        .await
        .expect("independent pool");

    store.close().await;
    assert!(clone.pool.is_closed());
    assert!(!independent.pool.is_closed());
    independent
        .append_source(
            &CognitiveAccess::agent_private(owner),
            &source(
                CognitiveScope::AgentPrivate,
                "independent-pool",
                "still writable",
            ),
        )
        .await
        .expect("closing the clone family leaves the independent pool writable");
    independent.close().await;
}

#[tokio::test]
async fn close_preserves_unresolved_queued_lease_and_release_still_fails_closed() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(/*suffix*/ 75);
    let owner_layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&owner_layout).await.expect("store");
    let lease = store
        .acquire_local_lease(
            "lease:close-queued",
            /*generation*/ 1,
            "fence:close-queued",
        )
        .await
        .expect("acquire lease")
        .into_handle();
    assert!(matches!(
        lease
            .admit("occurrence:close-queued", "topic", "payload")
            .await
            .expect("admit"),
        LocalAdmission::Queued(_)
    ));
    let head = lease.head_witness().await.expect("active lease head");
    let counts = lease.snapshot_counts().await.expect("queued counts");

    store.close().await;
    drop(lease);
    drop(store);
    let reopened = CognitiveStore::open(&owner_layout).await.expect("reopen");
    let lease = reopened
        .reopen_local_lease(
            "lease:close-queued",
            /*generation*/ 1,
            "fence:close-queued",
        )
        .await
        .expect("close did not terminalize the active lease");
    assert_eq!(lease.head_witness().await.expect("reopened head"), head);
    assert_eq!(
        lease.snapshot_counts().await.expect("reopened counts"),
        counts
    );
    assert_eq!(
        lease
            .status("occurrence:close-queued")
            .await
            .expect("queued status"),
        LocalOutcomeState::Queued
    );
    assert!(matches!(
        lease.release().await,
        Err(LocalLeaseOutboxError::IllegalTransition(message))
            if message.contains("unresolved local occurrences")
    ));
    assert_eq!(
        lease.head_witness().await.expect("unchanged active head"),
        head
    );
    assert_eq!(
        lease.snapshot_counts().await.expect("unchanged counts"),
        counts
    );
    reopened.close().await;
}
