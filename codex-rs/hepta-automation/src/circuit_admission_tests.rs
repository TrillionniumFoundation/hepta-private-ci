use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

use crate::*;
use crate::circuit_runtime_tests::completion;
use crate::circuit_runtime_tests::definition;
use crate::circuit_runtime_tests::digest;
use crate::circuit_runtime_tests::fence;
use crate::circuit_runtime_tests::start;

async fn pending() -> (tempfile::TempDir, AutomationStore, CircuitCommandReceiptV2) {
    let directory = tempfile::tempdir().expect("private durable owner");
    let store = AutomationStore::open_root(
        directory.path().join("automation"), fence(/*generation*/ 1).owner_agent_id,
    ).await.expect("normal AutomationStore migrations");
    let created = store.create_bounded_circuit_run(&definition(), &start(), &fence(/*generation*/ 1))
        .await.expect("create");
    let dispatched = store.apply_bounded_circuit_command(&CircuitCommandV2 {
        run_id: "run-1".to_string(), command_id: "advance".to_string(),
        fence: fence(/*generation*/ 1), expected_revision: created.run.revision(),
        now_ms: 11, event: CircuitEventV2::Advance { quantum: 1 },
    }).await.expect("commit computation reservation");
    (directory, store, dispatched)
}

fn claim(dispatched: &CircuitCommandReceiptV2, command_id: &str) -> CircuitComputationClaimV2 {
    CircuitComputationClaimV2 {
        run_id: "run-1".to_string(), activation_id: dispatched.dispatches[0].activation_id,
        command_id: command_id.to_string(), fence: fence(/*generation*/ 1),
        expected_revision: dispatched.run.revision(), now_ms: 12,
        execution_request_digest: digest("exact-cell-input-with-original-clock"),
    }
}

#[tokio::test]
async fn only_first_persisted_claim_returns_a_single_use_execution_admission() {
    let (_directory, store, dispatched) = pending().await;
    let request = claim(&dispatched, "claim");
    let token = store.claim_circuit_computation(&request).await.expect("first durable claim");
    assert!(!token.reconciliation_only());
    assert_eq!(token.dispatch(), &dispatched.dispatches[0]);
    assert_eq!(token.owner_agent_id(), store.owner_agent_id());
    assert_eq!(token.definition_digest(), &definition().definition_digest().expect("definition"));
    assert_eq!(token.execution_request_digest(), Some(&request.execution_request_digest));
    assert_eq!((token.observed_revision(), token.observed_at_ms(), token.lease_expires_at_ms(), token.run_deadline_ms()),
        (2, 12, 110, 1_010));
    let repeated = store.claim_circuit_computation(&request).await.expect("same claim bytes");
    assert!(repeated.reconciliation_only());
    assert_eq!(repeated.dispatch(), token.dispatch());
    assert_eq!(repeated.observed_revision(), token.observed_revision());
    let recovered = store.recover_circuit_computation("run-1", request.activation_id, &request.fence, /*now_ms*/ 13)
        .await.expect("read verified pending work");
    assert!(recovered.reconciliation_only());
    assert_eq!((recovered.observed_revision(), recovered.observed_at_ms()), (2, 13));
    assert_eq!(recovered.execution_request_digest(), token.execution_request_digest());
    let run = store.bounded_circuit_run("run-1").await.expect("full event replay").expect("run");
    assert_eq!((run.revision(), run.budget().spent(), run.budget().reserved(), run.unresolved()), (2, 0, 5, 1));
    store.close().await;
}

#[tokio::test]
async fn lost_claim_response_before_any_cell_contact_never_reopens_execution() {
    let (directory, store, dispatched) = pending().await;
    let request = claim(&dispatched, "claim-before-process-loss");
    let lost_response = store.claim_circuit_computation(&request).await.expect("claim committed");
    assert!(!lost_response.reconciliation_only());
    drop(lost_response); // No Cell has received this request.
    let root = store.path().parent().expect("root").to_path_buf();
    let owner = store.owner_agent_id().clone();
    store.close().await;
    drop(store);
    let reopened = AutomationStore::open_root(root, owner).await.expect("new process/pool");
    let recovered = reopened.recover_circuit_computation("run-1", request.activation_id, &request.fence, /*now_ms*/ 13)
        .await.expect("recover committed claim");
    assert!(recovered.reconciliation_only());
    assert_eq!(recovered.dispatch(), &dispatched.dispatches[0]);
    assert_eq!(recovered.execution_request_digest(), Some(&request.execution_request_digest));
    let retry = CircuitComputationClaimV2 {
        command_id: "different-retry-id".to_string(), expected_revision: recovered.observed_revision(),
        now_ms: 14, ..request
    };
    let retried = reopened.claim_circuit_computation(&retry).await.expect("readback after lost response");
    assert!(retried.reconciliation_only(), "downstream absence is not proof of no contact");
    assert_eq!(retried.observed_revision(), 2);
    assert_eq!(reopened.bounded_circuit_run("run-1").await.expect("replay").expect("run").budget().reserved(), 5);
    reopened.close().await;
    drop(directory);
}

#[tokio::test]
async fn independent_owner_connections_cannot_both_claim_the_same_computation() {
    let (_directory, store, dispatched) = pending().await;
    let other = AutomationStore::open_root(
        store.path().parent().expect("root").to_path_buf(), store.owner_agent_id().clone(),
    ).await.expect("independent pool");
    let left = claim(&dispatched, "claim-left");
    let right = claim(&dispatched, "claim-right");
    let (left, right) = tokio::join!(
        store.claim_circuit_computation(&left), other.claim_circuit_computation(&right),
    );
    let left = left.expect("left result");
    let right = right.expect("right result");
    assert_eq!(usize::from(!left.reconciliation_only()) + usize::from(!right.reconciliation_only()), 1);
    assert_eq!(left.dispatch(), right.dispatch());
    assert_eq!(left.execution_request_digest(), right.execution_request_digest());
    let run = store.bounded_circuit_run("run-1").await.expect("replay").expect("run");
    assert_eq!((run.revision(), run.budget().reserved()), (2, 5));
    store.close().await;
    other.close().await;
}

#[tokio::test]
async fn downstream_request_changes_and_command_id_reuse_cannot_rebind_the_claim() {
    let (_directory, store, dispatched) = pending().await;
    let original = claim(&dispatched, "immutable-claim");
    let token = store.claim_circuit_computation(&original).await.expect("claim");
    let changed_request = CircuitComputationClaimV2 {
        command_id: "new-id".to_string(), expected_revision: token.observed_revision(),
        execution_request_digest: digest("different-clock-mask-or-frontier"), ..original.clone()
    };
    assert!(matches!(store.claim_circuit_computation(&changed_request).await, Err(TaskFlowError::Conflict(_))));
    let changed_bytes = CircuitComputationClaimV2 { now_ms: 13, ..original.clone() };
    assert!(matches!(store.claim_circuit_computation(&changed_bytes).await, Err(TaskFlowError::Conflict(_))));
    let recovered = store.recover_circuit_computation("run-1", original.activation_id, &original.fence, /*now_ms*/ 13)
        .await.expect("original request survives");
    assert_eq!(recovered.execution_request_digest(), Some(&original.execution_request_digest));
    assert_eq!(recovered.observed_revision(), token.observed_revision());
    store.close().await;
}

#[tokio::test]
async fn wrong_owner_generation_expiry_and_clock_regression_never_create_a_token() {
    let (_directory, store, dispatched) = pending().await;
    let original = claim(&dispatched, "claim");
    let stale_revision = CircuitComputationClaimV2 { expected_revision: 0, ..original.clone() };
    assert!(matches!(store.claim_circuit_computation(&stale_revision).await, Err(TaskFlowError::Conflict(_))));
    store.claim_circuit_computation(&original).await.expect("correct claim");
    for mutation in ["owner", "generation", "expiry", "clock"] {
        let mut changed = original.clone();
        changed.command_id = format!("rejected-{mutation}");
        match mutation {
            "owner" => changed.fence.owner_agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13").expect("other agent"),
            "generation" => changed.fence = fence(/*generation*/ 2),
            "expiry" => changed.now_ms = 110,
            "clock" => changed.now_ms = 11,
            _ => unreachable!(),
        }
        assert!(matches!(store.claim_circuit_computation(&changed).await, Err(TaskFlowError::StaleFence)));
        assert!(matches!(store.recover_circuit_computation("run-1", original.activation_id, &changed.fence, changed.now_ms).await,
            Err(TaskFlowError::StaleFence)));
    }
    assert_eq!(store.bounded_circuit_run("run-1").await.expect("replay").expect("run").revision(), 2);
    store.close().await;
}

#[tokio::test]
async fn lease_takeover_keeps_the_original_invocation_and_only_allows_reconciliation() {
    let (_directory, store, dispatched) = pending().await;
    let original = claim(&dispatched, "claim");
    let token = store.claim_circuit_computation(&original).await.expect("claim");
    let successor = store.claim_bounded_circuit_run(&CircuitLeaseClaimV2 {
        run_id: "run-1".to_string(), command_id: "takeover".to_string(), fence: fence(/*generation*/ 2),
        expected_revision: token.observed_revision(), now_ms: 110, lease_duration_ms: 100,
    }).await.expect("fenced successor");
    assert_eq!(successor.run.activations()[&original.activation_id].status, CircuitActivationStatusV2::Indeterminate);
    assert!(matches!(store.recover_circuit_computation("run-1", original.activation_id, &original.fence, /*now_ms*/ 111).await,
        Err(TaskFlowError::StaleFence)));
    let recovered = store.recover_circuit_computation("run-1", original.activation_id, &fence(/*generation*/ 2), /*now_ms*/ 111)
        .await.expect("successor readback");
    assert!(recovered.reconciliation_only());
    assert_eq!(recovered.dispatch(), token.dispatch());
    assert_eq!(recovered.execution_request_digest(), token.execution_request_digest());
    assert_eq!(recovered.lease_expires_at_ms(), 210);
    let retry = CircuitComputationClaimV2 {
        command_id: "successor-may-not-reexecute".to_string(), fence: fence(/*generation*/ 2),
        expected_revision: successor.run.revision(), now_ms: 111, ..original
    };
    assert!(store.claim_circuit_computation(&retry).await.expect("readback only").reconciliation_only());
    assert_eq!(store.bounded_circuit_run("run-1").await.expect("replay").expect("run").budget().reserved(), 5);
    store.close().await;
}

#[tokio::test]
async fn cancellation_before_a_computation_claim_never_manufactures_execution_authority() {
    let (_directory, store, dispatched) = pending().await;
    let request = claim(&dispatched, "after-cancel");
    let cancelled = store.apply_bounded_circuit_command(&CircuitCommandV2 {
        run_id: "run-1".to_string(), command_id: "cancel".to_string(), fence: fence(/*generation*/ 1),
        expected_revision: dispatched.run.revision(), now_ms: 12, event: CircuitEventV2::Cancel,
    }).await.expect("stop admission");
    let readback = store.claim_circuit_computation(&CircuitComputationClaimV2 {
        expected_revision: cancelled.run.revision(), now_ms: 13, ..request
    }).await.expect("pending original dispatch is still observable");
    assert!(readback.reconciliation_only());
    assert_eq!(readback.execution_request_digest(), None);
    assert_eq!((readback.observed_revision(), cancelled.run.budget().reserved(), cancelled.run.outcome()), (2, 5, None));
    store.close().await;
}

#[tokio::test]
async fn ready_completed_and_corrupt_activations_cannot_be_admitted_as_pending_work() {
    let (_directory, store, dispatched) = pending().await;
    let mut separate = start();
    separate.run_id = "ready-run".to_string();
    let ready = store.create_bounded_circuit_run(&definition(), &separate, &fence(/*generation*/ 1)).await.expect("ready");
    let ready_id = *ready.run.activations().keys().next().expect("entry");
    assert!(store.recover_circuit_computation("ready-run", ready_id, &fence(/*generation*/ 1), /*now_ms*/ 12).await.is_err());
    let completed = store.apply_bounded_circuit_command(&CircuitCommandV2 {
        run_id: "run-1".to_string(), command_id: "complete".to_string(), fence: fence(/*generation*/ 1),
        expected_revision: dispatched.run.revision(), now_ms: 12,
        event: CircuitEventV2::Complete { completion: completion(&dispatched.dispatches[0], &["done"], "result") },
    }).await.expect("actual completion");
    assert!(store.recover_circuit_computation("run-1", dispatched.dispatches[0].activation_id, &fence(/*generation*/ 1), /*now_ms*/ 13)
        .await.is_err());
    assert_eq!(completed.run.budget().spent(), 3);
    sqlx::query("UPDATE circuit_v2_runs SET state_json = '{}' WHERE run_id = 'run-1'")
        .execute(store.taskflow_pool()).await.expect("inject projection corruption");
    assert!(matches!(store.claim_circuit_computation(&claim(&dispatched, "forged-projection")).await, Err(TaskFlowError::Corrupt(_))));
    store.close().await;
}

#[tokio::test]
async fn run_deadline_rejects_new_claims_but_preserves_readback_of_existing_reservations() {
    let directory = tempfile::tempdir().expect("private owner");
    let store = AutomationStore::open_root(
        directory.path().join("automation"), fence(/*generation*/ 1).owner_agent_id,
    ).await.expect("store");
    let mut bounded = definition();
    bounded.limits.max_elapsed_ms = 10;
    let created = store.create_bounded_circuit_run(&bounded, &start(), &fence(/*generation*/ 1)).await.expect("create");
    let dispatched = store.apply_bounded_circuit_command(&CircuitCommandV2 {
        run_id: "run-1".to_string(), command_id: "advance".to_string(), fence: fence(/*generation*/ 1),
        expected_revision: created.run.revision(), now_ms: 11, event: CircuitEventV2::Advance { quantum: 1 },
    }).await.expect("reserve before deadline");
    let request = CircuitComputationClaimV2 { now_ms: 20, ..claim(&dispatched, "too-late") };
    assert!(store.claim_circuit_computation(&request).await.is_err());
    let recovered = store.recover_circuit_computation("run-1", request.activation_id, &request.fence, /*now_ms*/ 20)
        .await.expect("readback is still allowed");
    assert!(recovered.reconciliation_only());
    assert_eq!(recovered.run_deadline_ms(), 20);
    assert_eq!(recovered.execution_request_digest(), None);
    assert_eq!(store.bounded_circuit_run("run-1").await.expect("replay").expect("run"), dispatched.run);
    store.close().await;
}
