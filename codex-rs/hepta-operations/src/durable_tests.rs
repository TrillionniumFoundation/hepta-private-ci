use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use tempfile::TempDir;

use super::DurableOperationError;
use super::DurableOperationStore;
use super::DurableOutboxState;
use super::OperationContextV1;
use crate::OperationError;
use crate::OperationKey;
use crate::OperationState;
use crate::OutboxIntent;
use crate::ReconciliationOutcome;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn key(operation: &str, payload: &[u8]) -> OperationKey {
    OperationKey {
        id: id(operation),
        payload_digest: Digest32::of_bytes(payload),
    }
}

fn outbox(intent: &str, operation: &str) -> OutboxIntent {
    OutboxIntent {
        intent_id: id(intent),
        operation_id: id(operation),
        destination: id("runtime.agentd"),
        payload_digest: Digest32::of_bytes(b"dispatch-payload"),
    }
}

async fn opened() -> (TempDir, DurableOperationStore) {
    let temp = tempfile::tempdir().expect("tempdir");
    let store = DurableOperationStore::open(temp.path())
        .await
        .expect("open durable store");
    (temp, store)
}

#[tokio::test]
async fn crash_reopen_preserves_indeterminate_and_terminal_reconciliation() {
    let (temp, store) = opened().await;
    let operation = id("operation.crash-reopen");
    store
        .begin(key(operation.as_str(), b"payload"), generation(7))
        .await
        .expect("begin");
    store
        .record_authorized(
            &operation,
            Digest32::of_bytes(b"authorization"),
            generation(19),
        )
        .await
        .expect("authorized");
    store
        .record_dispatch(&operation, Digest32::of_bytes(b"dispatch"))
        .await
        .expect("dispatch");
    store
        .mark_indeterminate(&operation, Digest32::of_bytes(b"response-lost"))
        .await
        .expect("indeterminate");
    store.close().await;

    let reopened = DurableOperationStore::open(temp.path())
        .await
        .expect("reopen after simulated crash");
    let before = reopened
        .get(&operation)
        .await
        .expect("read indeterminate")
        .expect("operation exists");
    assert!(matches!(before.state, OperationState::Indeterminate { .. }));

    reopened
        .observe_terminal(
            &operation,
            ReconciliationOutcome::Applied,
            Digest32::of_bytes(b"owner-terminal-observation"),
            generation(7),
        )
        .await
        .expect("terminal observation");
    reopened.close().await;

    let terminal = DurableOperationStore::open(temp.path())
        .await
        .expect("reopen terminal");
    let after = terminal
        .get(&operation)
        .await
        .expect("read terminal")
        .expect("operation exists");
    assert!(matches!(after.state, OperationState::Applied { .. }));
}

#[tokio::test]
async fn operation_identity_reuse_with_changed_payload_fails_closed_across_handles() {
    let (temp, first) = opened().await;
    let second = DurableOperationStore::open(temp.path())
        .await
        .expect("second handle");
    let operation = id("operation.identity");

    first
        .begin(key(operation.as_str(), b"one"), generation(3))
        .await
        .expect("first begin");
    let same = second
        .begin(key(operation.as_str(), b"one"), generation(3))
        .await
        .expect("idempotent begin");
    assert_eq!(same.key.payload_digest, Digest32::of_bytes(b"one"));

    let error = second
        .begin(key(operation.as_str(), b"two"), generation(3))
        .await
        .expect_err("changed payload must conflict");
    assert!(matches!(
        error,
        DurableOperationError::Operation(OperationError::Conflict(ref value))
            if value == &operation
    ));
}

#[tokio::test]
async fn immutable_operation_context_survives_reopen_and_rejects_semantic_drift() {
    let (temp, store) = opened().await;
    let operation = id("operation.context");
    let semantic = Digest32::of_bytes(b"semantic-context");
    store
        .begin(
            OperationKey {
                id: operation.clone(),
                payload_digest: semantic,
            },
            generation(6),
        )
        .await
        .expect("begin");
    let context = OperationContextV1 {
        operation_id: operation.clone(),
        action_id: id("request_retry"),
        resource_id: id("runtime.agentd"),
        expected_revision: codex_hepta_types::Revision::new(9).expect("revision"),
        semantic_digest: semantic,
    };
    store.bind_context(&context).await.expect("bind context");
    store.close().await;

    let reopened = DurableOperationStore::open(temp.path())
        .await
        .expect("reopen");
    assert_eq!(
        reopened
            .get_context(&operation)
            .await
            .expect("context read")
            .expect("context exists"),
        context
    );

    let changed = OperationContextV1 {
        action_id: id("runtime_stop"),
        ..context
    };
    let error = reopened
        .bind_context(&changed)
        .await
        .expect_err("context is immutable");
    assert!(matches!(
        error,
        DurableOperationError::Operation(OperationError::Conflict(ref value))
            if value == &operation
    ));
}

#[tokio::test]
async fn successor_owner_generation_can_reconcile_but_predecessor_cannot() {
    let (_temp, store) = opened().await;
    let operation = id("operation.successor-reconcile");
    store
        .begin(key(operation.as_str(), b"payload"), generation(8))
        .await
        .expect("begin");
    store
        .record_authorized(
            &operation,
            Digest32::of_bytes(b"authorization"),
            generation(21),
        )
        .await
        .expect("authorize");
    store
        .record_dispatch(&operation, Digest32::of_bytes(b"dispatch"))
        .await
        .expect("dispatch");

    let stale = store
        .observe_terminal(
            &operation,
            ReconciliationOutcome::NotApplied,
            Digest32::of_bytes(b"stale-observation"),
            generation(7),
        )
        .await
        .expect_err("predecessor owner must be fenced");
    assert!(matches!(
        stale,
        DurableOperationError::Operation(OperationError::StaleGeneration)
    ));

    let terminal = store
        .observe_terminal(
            &operation,
            ReconciliationOutcome::NotApplied,
            Digest32::of_bytes(b"successor-observation"),
            generation(9),
        )
        .await
        .expect("successor generation may reconcile");
    assert!(matches!(terminal.state, OperationState::NotApplied { .. }));
}

#[tokio::test]
async fn durable_outbox_lease_fences_live_owner_and_allows_expired_takeover() {
    let (_temp, store) = opened().await;
    let operation = id("operation.outbox-lease");
    let intent = outbox("intent.outbox-lease", operation.as_str());
    store
        .begin(key(operation.as_str(), b"payload"), generation(11))
        .await
        .expect("begin");
    store.enqueue_outbox(&intent).await.expect("enqueue");

    let first_owner = id("worker.one");
    let second_owner = id("worker.two");
    store
        .claim_outbox(
            &intent.intent_id,
            first_owner.clone(),
            generation(1),
            1_000,
            100,
        )
        .await
        .expect("first claim");

    let live_error = store
        .claim_outbox(
            &intent.intent_id,
            second_owner.clone(),
            generation(2),
            1_050,
            100,
        )
        .await
        .expect_err("live foreign claim must be fenced");
    assert!(matches!(
        live_error,
        DurableOperationError::Operation(OperationError::StaleGeneration)
    ));

    store
        .claim_outbox(
            &intent.intent_id,
            second_owner.clone(),
            generation(2),
            1_101,
            100,
        )
        .await
        .expect("expired takeover");

    let stale_ack = store
        .acknowledge_outbox(
            &intent.intent_id,
            &first_owner,
            generation(1),
            Digest32::of_bytes(b"old-ack"),
            1_102,
        )
        .await
        .expect_err("old owner must not acknowledge after takeover");
    assert!(matches!(
        stale_ack,
        DurableOperationError::Operation(OperationError::StaleGeneration)
    ));

    let acknowledgement = Digest32::of_bytes(b"new-ack");
    store
        .acknowledge_outbox(
            &intent.intent_id,
            &second_owner,
            generation(2),
            acknowledgement,
            1_102,
        )
        .await
        .expect("current owner ack");
    assert_eq!(
        store
            .outbox_state(&intent.intent_id)
            .await
            .expect("state")
            .expect("outbox"),
        DurableOutboxState::Acknowledged {
            owner_id: second_owner,
            owner_generation: generation(2),
            acknowledgement_digest: acknowledgement,
        }
    );
}

#[tokio::test]
async fn outbox_acknowledgement_never_promotes_operation_to_terminal() {
    let (_temp, store) = opened().await;
    let operation = id("operation.ack-not-terminal");
    store
        .begin(key(operation.as_str(), b"payload"), generation(4))
        .await
        .expect("begin");
    store
        .record_authorized(
            &operation,
            Digest32::of_bytes(b"authorization"),
            generation(9),
        )
        .await
        .expect("authorize");
    store
        .record_dispatch(&operation, Digest32::of_bytes(b"dispatch"))
        .await
        .expect("dispatch");

    let intent = outbox("intent.ack-not-terminal", operation.as_str());
    store.enqueue_outbox(&intent).await.expect("enqueue");
    let owner = id("worker.delivery");
    store
        .claim_outbox(
            &intent.intent_id,
            owner.clone(),
            generation(4),
            10,
            1_000,
        )
        .await
        .expect("claim");
    store
        .acknowledge_outbox(
            &intent.intent_id,
            &owner,
            generation(4),
            Digest32::of_bytes(b"queue-ack"),
            11,
        )
        .await
        .expect("acknowledge");

    let record = store
        .get(&operation)
        .await
        .expect("read operation")
        .expect("operation exists");
    assert!(matches!(record.state, OperationState::Dispatched { .. }));
    assert!(!record.state.is_terminal());
}

#[tokio::test]
async fn reopen_rejects_current_projection_without_matching_immutable_event() {
    let (temp, store) = opened().await;
    let operation = id("operation.tamper");
    store
        .begin(key(operation.as_str(), b"payload"), generation(5))
        .await
        .expect("begin");

    sqlx::query(
        "UPDATE operation_records
         SET state='applied', outcome_digest=?
         WHERE operation_id=?",
    )
    .bind(Digest32::of_bytes(b"forged").to_string())
    .bind(operation.as_str())
    .execute(&store.pool)
    .await
    .expect("sabotage current projection");
    store.close().await;

    let error = DurableOperationStore::open(temp.path())
        .await
        .expect_err("tampered projection must fail reopen");
    assert!(matches!(error, DurableOperationError::Corrupt(_)));
}
