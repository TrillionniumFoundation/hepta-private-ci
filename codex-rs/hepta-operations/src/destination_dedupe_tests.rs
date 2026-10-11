use super::*;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

fn stable_id(value: &str) -> StableId {
    StableId::new(value).expect("test identifier")
}

fn identity(payload: &[u8]) -> DestinationOperationIdentity {
    DestinationOperationIdentity {
        destination: stable_id("automation.taskflow"),
        scope_id: stable_id("scope:test"),
        operation_id: stable_id("operation:test:destination"),
        payload_digest: Digest32::of_bytes(payload),
    }
}

#[tokio::test]
async fn domain_write_and_dedupe_receipt_commit_atomically() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("destination.sqlite3");
    let store = DestinationDedupeStore::open_standalone(&path)
        .await
        .expect("open");
    sqlx::query(
        "CREATE TABLE domain_effects (operation_id TEXT PRIMARY KEY, payload BLOB NOT NULL)",
    )
    .execute(&store.pool)
    .await
    .expect("domain schema");
    let operation = identity(b"payload");
    let start = store.begin_apply(&operation).await.expect("begin");
    let DestinationApplyStart::Apply(mut apply) = start else {
        panic!("first application must not be deduped");
    };
    sqlx::query("INSERT INTO domain_effects (operation_id, payload) VALUES (?, ?)")
        .bind(operation.operation_id.as_str())
        .bind(b"payload".as_slice())
        .execute(&mut **apply.transaction().expect("transaction"))
        .await
        .expect("domain write");
    let receipt = apply
        .commit_applied(Digest32::of_bytes(b"domain-row-1"))
        .await
        .expect("commit");
    assert_eq!(receipt.identity, operation);

    let replay = store.begin_apply(&operation).await.expect("replay");
    assert!(matches!(replay, DestinationApplyStart::AlreadyApplied(_)));
    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM domain_effects")
        .fetch_one(&store.pool)
        .await
        .expect("count");
    assert_eq!(count, 1);
}

#[tokio::test]
async fn rollback_removes_domain_write_and_dedupe_together() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("destination.sqlite3");
    let store = DestinationDedupeStore::open_standalone(&path)
        .await
        .expect("open");
    sqlx::query(
        "CREATE TABLE domain_effects (operation_id TEXT PRIMARY KEY, payload BLOB NOT NULL)",
    )
    .execute(&store.pool)
    .await
    .expect("domain schema");
    let operation = identity(b"payload");
    let start = store.begin_apply(&operation).await.expect("begin");
    let DestinationApplyStart::Apply(mut apply) = start else {
        panic!("first application must not be deduped");
    };
    sqlx::query("INSERT INTO domain_effects (operation_id, payload) VALUES (?, ?)")
        .bind(operation.operation_id.as_str())
        .bind(b"payload".as_slice())
        .execute(&mut **apply.transaction().expect("transaction"))
        .await
        .expect("domain write");
    apply.rollback().await.expect("rollback");
    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM domain_effects")
        .fetch_one(&store.pool)
        .await
        .expect("count");
    assert_eq!(count, 0);
    assert!(matches!(
        store.begin_apply(&operation).await.expect("retry"),
        DestinationApplyStart::Apply(_)
    ));
}

#[tokio::test]
async fn semantic_identity_drift_conflicts() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("destination.sqlite3");
    let store = DestinationDedupeStore::open_standalone(&path)
        .await
        .expect("open");
    let first = identity(b"payload");
    let start = store.begin_apply(&first).await.expect("begin");
    let DestinationApplyStart::Apply(apply) = start else {
        panic!("first application must not be deduped");
    };
    apply
        .commit_applied(Digest32::of_bytes(b"effect"))
        .await
        .expect("commit");
    let changed = identity(b"changed");
    assert!(matches!(
        store.begin_apply(&changed).await,
        Err(DurableOperationError::Conflict(_))
    ));
}
