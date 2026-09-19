use std::time::Duration;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::DurableOperationError;
use crate::DurableOperationStore;
use crate::OperationIntentV1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn intent(operation_id: &str) -> OperationIntentV1 {
    OperationIntentV1 {
        scope_id: id("scope:interactive"),
        operation_id: id(operation_id),
        expected_predecessor: None,
        destination: id("automation.taskflow"),
        payload_digest: Digest32::of_bytes(operation_id.as_bytes()),
        owner_generation: generation(1),
    }
}

#[tokio::test]
async fn exact_claim_never_consumes_an_older_queued_operation() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let store = DurableOperationStore::open(&path).await.expect("open");
    let older = intent("operation:0001");
    let requested = intent("operation:9999");
    store.prepare_intent(&older).await.expect("prepare older");
    store
        .prepare_intent(&requested)
        .await
        .expect("prepare requested");

    let claim = store
        .claim_operation(
            &requested.scope_id,
            &requested.operation_id,
            &id("worker:interactive"),
            generation(1),
            Duration::from_secs(5),
        )
        .await
        .expect("claim")
        .expect("claim row");
    assert_eq!(claim.intent.operation_id, requested.operation_id);

    let older_status = store
        .outbox_status(&older.destination, &older.scope_id, &older.operation_id)
        .await
        .expect("status")
        .expect("older row");
    assert_eq!(older_status.state.as_str(), "queued");
}

#[tokio::test]
async fn exact_claim_fences_lower_generation_and_allows_current_takeover() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let store = DurableOperationStore::open(&path).await.expect("open");
    let operation = intent("operation:takeover");
    store.prepare_intent(&operation).await.expect("prepare");
    let first = store
        .claim_operation(
            &operation.scope_id,
            &operation.operation_id,
            &id("worker:first"),
            generation(2),
            Duration::from_millis(1),
        )
        .await
        .expect("claim")
        .expect("row");
    tokio::time::sleep(Duration::from_millis(5)).await;
    store.recover_expired_leases().await.expect("recover");

    assert!(matches!(
        store
            .claim_operation(
                &operation.scope_id,
                &operation.operation_id,
                &id("worker:stale"),
                generation(1),
                Duration::from_secs(1),
            )
            .await,
        Err(DurableOperationError::StaleGeneration)
    ));
    let current = store
        .claim_operation(
            &operation.scope_id,
            &operation.operation_id,
            &id("worker:current"),
            generation(3),
            Duration::from_secs(1),
        )
        .await
        .expect("takeover")
        .expect("row");
    assert!(current.fence > first.fence);
    assert_eq!(current.owner_generation, generation(3));
}
