//! Actual SQLite/kernel recovery; modeled terminal observations are not learning
//! efficacy, independent evaluation, or production authority evidence.
use super::*;
use crate::CircuitCommandV2;
use crate::CircuitEventV2;
use crate::circuit_runtime_tests::completion;
use crate::circuit_runtime_tests::definition;
use crate::circuit_runtime_tests::digest;
use crate::circuit_runtime_tests::fence;
use crate::circuit_runtime_tests::start;
use pretty_assertions::assert_eq;

async fn store() -> (tempfile::TempDir, AutomationStore) {
    let root = tempfile::tempdir().unwrap();
    let store = AutomationStore::open_root(
        root.path().canonicalize().unwrap().join("automation"),
        fence(/*generation*/ 1).owner_agent_id,
    )
    .await
    .unwrap();
    (root, store)
}

async fn terminal(store: &AutomationStore, id: &str) -> CircuitCommittedTraceV2 {
    let mut input = start();
    input.run_id = id.into();
    let mut receipt = store
        .create_bounded_circuit_run(&definition(), &input, &fence(/*generation*/ 1))
        .await
        .unwrap();
    let mut event = CircuitEventV2::Advance { quantum: 1 };
    for index in 0..3 {
        receipt = store
            .apply_bounded_circuit_command(&CircuitCommandV2 {
                run_id: id.into(),
                command_id: format!("step-{index}"),
                fence: fence(/*generation*/ 1),
                expected_revision: receipt.run.revision(),
                now_ms: 11 + index,
                event,
            })
            .await
            .unwrap();
        event = if index == 0 {
            CircuitEventV2::Complete {
                completion: completion(&receipt.dispatches[0], &["done"], "observed-result"),
            }
        } else {
            CircuitEventV2::Advance { quantum: 1 }
        };
    }
    store
        .bounded_circuit_committed_trace(id)
        .await
        .unwrap()
        .unwrap()
}

#[tokio::test]
async fn completion_claim_and_ack_survive_reopen_without_releasing_delivery() {
    let (_root, store) = store().await;
    let trace = terminal(&store, "outbox-run").await;
    let intent = store
        .enqueue_circuit_learning(&trace, digest("objective"))
        .await
        .unwrap();
    assert_eq!(
        store
            .enqueue_circuit_learning(&trace, digest("objective"))
            .await
            .unwrap(),
        intent
    );
    assert!(
        store
            .enqueue_circuit_learning(&trace, digest("other-objective"))
            .await
            .is_err()
    );
    let request = digest("exact-request-and-owners");
    assert!(
        store
            .acknowledge_circuit_learning(&intent, &request, &digest("head"))
            .await
            .is_err()
    );
    assert!(
        store
            .claim_circuit_learning(&intent, &request)
            .await
            .unwrap()
    );
    let path = store.path().parent().unwrap().to_path_buf();
    let owner = store.owner_agent_id().clone();
    store.close().await;
    drop(store);
    let reopened = AutomationStore::open_root(path, owner).await.unwrap();
    assert!(
        !reopened
            .claim_circuit_learning(&intent, &request)
            .await
            .unwrap(),
        "claimed-before-submit crash must only read back"
    );
    assert!(
        reopened
            .claim_circuit_learning(&intent, &digest("changed-request"))
            .await
            .is_err()
    );
    assert_eq!(
        reopened
            .pending_circuit_learning(/*limit*/ 1)
            .await
            .unwrap()
            .len(),
        1
    );
    reopened
        .acknowledge_circuit_learning(&intent, &request, &digest("head"))
        .await
        .unwrap();
    reopened
        .acknowledge_circuit_learning(&intent, &request, &digest("head"))
        .await
        .unwrap();
    assert!(
        reopened
            .acknowledge_circuit_learning(&intent, &request, &digest("other-head"))
            .await
            .is_err()
    );
    assert!(
        !reopened
            .claim_circuit_learning(&intent, &request)
            .await
            .unwrap()
    );
    assert!(
        reopened
            .pending_circuit_learning(/*limit*/ 1)
            .await
            .unwrap()
            .is_empty()
    );
    reopened.close().await;
}

#[tokio::test]
async fn learning_drain_distinguishes_unclaimed_intents_from_unsettled_claims_after_restart() {
    let (_root, store) = store().await;
    let trace = terminal(&store, "learning-drain").await;
    let intent = store
        .enqueue_circuit_learning(&trace, digest("objective"))
        .await
        .unwrap();
    assert_eq!(store.circuit_learning_drain_blockers().await.unwrap(), 0);
    let request = digest("original-request-and-owners");
    assert!(store.claim_circuit_learning(&intent, &request).await.unwrap());
    assert_eq!(store.circuit_drain_blockers().await.unwrap(), 0);
    assert_eq!(store.circuit_learning_drain_blockers().await.unwrap(), 1);
    let path = store.path().parent().unwrap().to_path_buf();
    let owner = store.owner_agent_id().clone();
    store.close().await;
    let reopened = AutomationStore::open_root(path, owner).await.unwrap();
    assert_eq!(reopened.circuit_learning_drain_blockers().await.unwrap(), 1);
    reopened
        .acknowledge_circuit_learning(&intent, &request, &digest("original-next-use-head"))
        .await
        .unwrap();
    assert_eq!(reopened.circuit_learning_drain_blockers().await.unwrap(), 0);
    // Even an ACK cannot conceal a corrupt original completion history.
    sqlx::query("UPDATE circuit_v2_runs SET state_digest = ? WHERE run_id = ?")
        .bind(digest("corrupt-projection").as_str())
        .bind("learning-drain")
        .execute(reopened.taskflow_pool())
        .await
        .unwrap();
    assert!(reopened.circuit_learning_drain_blockers().await.is_err());
    reopened.close().await;
}

#[tokio::test]
async fn learning_drain_visits_late_claims_and_rejects_corrupt_delivery_metadata() {
    let (_root, store) = store().await;
    let mut last = None;
    for index in 0..65 {
        let trace = terminal(&store, &format!("drain-{index:03}")).await;
        last = Some(store.enqueue_circuit_learning(&trace, digest("objective")).await.unwrap());
    }
    let intent = last.unwrap();
    store.claim_circuit_learning(&intent, &digest("request")).await.unwrap();
    assert_eq!(store.circuit_learning_drain_blockers().await.unwrap(), 1);
    sqlx::query("UPDATE circuit_learning_outbox_v1 SET request_digest = ? WHERE run_id = ?")
        .bind("z".repeat(64))
        .bind(&intent.source_run_id)
        .execute(store.taskflow_pool())
        .await
        .unwrap();
    assert!(matches!(store.circuit_learning_drain_blockers().await, Err(Error::Conflict)));
    store.close().await;
}

#[tokio::test]
async fn full_queue_preserves_existing_operation_and_corrupt_history_is_rejected() {
    let (_root, store) = store().await;
    for index in 0..MAX_RECORDS {
        let trace = terminal(&store, &format!("bounded-{index}")).await;
        store
            .enqueue_circuit_learning(&trace, digest("objective"))
            .await
            .unwrap();
    }
    let overflow = terminal(&store, "overflow").await;
    assert!(matches!(
        store
            .enqueue_circuit_learning(&overflow, digest("objective"))
            .await,
        Err(Error::Capacity)
    ));
    let original = store
        .bounded_circuit_committed_trace("bounded-0")
        .await
        .unwrap()
        .unwrap();
    store
        .enqueue_circuit_learning(&original, digest("objective"))
        .await
        .unwrap();
    assert_eq!(
        store
            .pending_circuit_learning(/*limit*/ 64)
            .await
            .unwrap()
            .len(),
        64
    );
    assert!(matches!(
        store.pending_circuit_learning(/*limit*/ 65).await,
        Err(Error::Capacity)
    ));
    sqlx::query("UPDATE circuit_v2_runs SET last_event_digest = 'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff' WHERE run_id = 'bounded-0'").execute(store.taskflow_pool()).await.unwrap();
    assert!(store.circuit_learning_delivery("bounded-0").await.is_err());
    store.close().await;
}

#[tokio::test]
async fn unfinished_computation_cannot_enter_learning_queue() {
    let (_root, store) = store().await;
    store
        .create_bounded_circuit_run(&definition(), &start(), &fence(/*generation*/ 1))
        .await
        .unwrap();
    let trace = store
        .bounded_circuit_committed_trace("run-1")
        .await
        .unwrap()
        .unwrap();
    assert!(
        store
            .enqueue_circuit_learning(&trace, digest("objective"))
            .await
            .is_err()
    );
    assert!(
        store
            .pending_circuit_learning(/*limit*/ 1)
            .await
            .unwrap()
            .is_empty()
    );
    store.close().await;
}
