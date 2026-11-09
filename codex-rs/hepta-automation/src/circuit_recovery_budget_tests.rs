use pretty_assertions::assert_eq;

use crate::circuit_history::CircuitFenceIdentityV2;
use crate::circuit_history::CircuitLedgerEventV2;
use crate::circuit_runtime_tests::completion;
use crate::circuit_runtime_tests::definition;
use crate::circuit_runtime_tests::digest;
use crate::circuit_runtime_tests::fence;
use crate::circuit_runtime_tests::start;
use crate::*;

#[path = "circuit_legacy_recovery_tests.rs"]
mod legacy;

#[path = "circuit_expired_recovery_tests.rs"]
mod expired;

fn command(run: &CircuitRunV2, id: &str, event: CircuitEventV2, now_ms: u64) -> CircuitCommandV2 {
    CircuitCommandV2 {
        run_id: run.run_id().to_string(),
        command_id: id.to_string(),
        fence: fence(/*generation*/ 1),
        expected_revision: run.revision(),
        now_ms,
        event,
    }
}

async fn pending_run() -> (
    tempfile::TempDir,
    AutomationStore,
    CircuitRunV2,
    CircuitDispatchV2,
) {
    let mut definition = definition();
    definition.limits.max_events = 1;
    definition.limits.max_activations = 1;
    definition.limits.max_frontier = 1;
    definition.limits.work_budget = 5;
    let directory = tempfile::tempdir().expect("private owner directory");
    let store = AutomationStore::open_root(
        directory
            .path()
            .canonicalize()
            .expect("canonical temporary owner")
            .join("automation"),
        fence(/*generation*/ 1).owner_agent_id,
    )
    .await
    .expect("durable owner");
    let created = store
        .create_bounded_circuit_run(&definition, &start(), &fence(/*generation*/ 1))
        .await
        .expect("create");
    let dispatched = store
        .apply_bounded_circuit_command(&command(
            &created.run,
            "dispatch",
            CircuitEventV2::Advance { quantum: 1 },
            /*now_ms*/ 11,
        ))
        .await
        .expect("dispatch inside the normal event horizon");
    let dispatch = dispatched.dispatches[0].clone();
    let admission = store
        .claim_circuit_computation(&CircuitComputationClaimV2 {
            run_id: dispatched.run.run_id().to_string(),
            activation_id: dispatch.activation_id,
            command_id: "original-computation".to_string(),
            fence: fence(/*generation*/ 1),
            expected_revision: dispatched.run.revision(),
            now_ms: 12,
            execution_request_digest: digest("original-cell-request"),
        })
        .await
        .expect("persist the original execution claim");
    assert!(!admission.reconciliation_only());
    let run = store
        .bounded_circuit_run("run-1")
        .await
        .expect("verified claim readback")
        .expect("run");
    (directory, store, run, dispatch)
}

async fn reopen(store: AutomationStore) -> AutomationStore {
    let root = store.path().parent().expect("owner root").to_path_buf();
    let owner = store.owner_agent_id().clone();
    store.close().await;
    drop(store);
    AutomationStore::open_root(root, owner)
        .await
        .expect("fresh owner connection")
}

#[tokio::test]
async fn stopped_polling_preserves_original_reconciliation_and_idempotent_retry() {
    let (_directory, store, run, dispatch) = pending_run().await;
    let stop = command(
        &run,
        "event-horizon",
        CircuitEventV2::Advance { quantum: 1 },
        /*now_ms*/ 13,
    );
    let stopped = store
        .apply_bounded_circuit_command(&stop)
        .await
        .expect("the first excess advance records the resource stop");
    assert_eq!(
        (
            stopped.run.stop_reason(),
            stopped.run.outcome(),
            stopped.run.unresolved(),
            stopped.run.budget().reserved(),
        ),
        (Some(CircuitStopReasonV2::EventLimit), None, 1, 5)
    );
    for (index, event) in [
        CircuitEventV2::Advance { quantum: 1 },
        CircuitEventV2::Cancel,
    ]
    .into_iter()
    .enumerate()
    {
        assert!(matches!(
            store
                .apply_bounded_circuit_command(&command(
                    &stopped.run,
                    &format!("new-poll-{index}"),
                    event,
                    /*now_ms*/ 14,
                ))
                .await,
            Err(TaskFlowError::Invalid(_))
        ));
    }
    assert_eq!(
        store.bounded_circuit_run("run-1").await.expect("readback"),
        Some(stopped.run.clone())
    );
    assert_eq!(
        store
            .apply_bounded_circuit_command(&stop)
            .await
            .expect("lost ACK retry"),
        CircuitCommandReceiptV2 {
            status: CircuitCommandStatusV2::AlreadyApplied,
            run: stopped.run.clone(),
            dispatches: Vec::new(),
        }
    );
    let unknown = store
        .apply_bounded_circuit_command(&command(
            &stopped.run,
            "original-unknown",
            CircuitEventV2::MarkIndeterminate {
                activation_id: dispatch.activation_id,
                observation_digest: digest("original-observation"),
            },
            /*now_ms*/ 14,
        ))
        .await
        .expect("unknown keeps its reserved work");
    let mut actual = completion(&dispatch, &["done"], "late-result");
    actual.actual_work = 7;
    let finished = store
        .apply_bounded_circuit_command(&command(
            &unknown.run,
            "original-terminal",
            CircuitEventV2::Reconcile { completion: actual },
            /*now_ms*/ 15,
        ))
        .await
        .expect("late original work remains settleable");
    assert_eq!(
        (
            finished.run.outcome(),
            finished.run.budget().spent(),
            finished.run.budget().reserved()
        ),
        (Some(CircuitExitV2::Failed), 7, 0)
    );
    let reopened = reopen(store).await;
    assert_eq!(
        reopened
            .bounded_circuit_run("run-1")
            .await
            .expect("canonical replay"),
        Some(finished.run)
    );
    reopened.close().await;
}

#[tokio::test]
async fn lease_churn_cannot_spend_pending_receipt_slots_across_reopen() {
    let (_directory, store, run, dispatch) = pending_run().await;
    let unknown = store
        .apply_bounded_circuit_command(&command(
            &run,
            "original-unknown",
            CircuitEventV2::MarkIndeterminate {
                activation_id: dispatch.activation_id,
                observation_digest: digest("original-observation"),
            },
            /*now_ms*/ 13,
        ))
        .await
        .expect("retain original unknown");
    let mut run = store
        .apply_bounded_circuit_command(&command(
            &unknown.run,
            "first-stop",
            CircuitEventV2::Cancel,
            /*now_ms*/ 14,
        ))
        .await
        .expect("stop without refunding unknown work")
        .run;
    for index in 0..63 {
        run = store
            .claim_bounded_circuit_run(&CircuitLeaseClaimV2 {
                run_id: "run-1".to_string(),
                command_id: format!("renewal-{index}"),
                fence: fence(/*generation*/ 1),
                expected_revision: run.revision(),
                now_ms: 15 + index,
                lease_duration_ms: 1_000,
            })
            .await
            .expect("bounded recovery lease renewal")
            .run;
    }
    let store = reopen(store).await;
    assert_eq!(
        store
            .bounded_circuit_run("run-1")
            .await
            .expect("history after reopen"),
        Some(run.clone())
    );
    assert!(matches!(
        store
            .claim_bounded_circuit_run(&CircuitLeaseClaimV2 {
                run_id: "run-1".to_string(),
                command_id: "excess-renewal".to_string(),
                fence: fence(/*generation*/ 1),
                expected_revision: run.revision(),
                now_ms: 78,
                lease_duration_ms: 1_000,
            })
            .await,
        Err(TaskFlowError::Invalid(_))
    ));
    assert_eq!(
        store
            .bounded_circuit_run("run-1")
            .await
            .expect("failed renewal is atomic"),
        Some(run.clone())
    );
    let mut actual = completion(&dispatch, &["done"], "original-overrun");
    actual.actual_work = 7;
    let terminal = command(
        &run,
        "terminal-at-history-bound",
        CircuitEventV2::Reconcile { completion: actual },
        /*now_ms*/ 78,
    );
    let finished = store
        .apply_bounded_circuit_command(&terminal)
        .await
        .expect("the final reserved slot records full original cost");
    assert_eq!(
        (
            finished.run.revision(),
            finished.run.outcome(),
            finished.run.budget().spent(),
            finished.run.budget().reserved(),
            finished.run.budget().available(),
        ),
        (68, Some(CircuitExitV2::Failed), 7, 0, 0)
    );
    let reopened = reopen(store).await;
    assert_eq!(
        reopened
            .bounded_circuit_run("run-1")
            .await
            .expect("terminal replay"),
        Some(finished.run.clone())
    );
    assert_eq!(
        reopened
            .apply_bounded_circuit_command(&terminal)
            .await
            .expect("terminal ACK retry"),
        CircuitCommandReceiptV2 {
            status: CircuitCommandStatusV2::AlreadyApplied,
            run: finished.run,
            dispatches: Vec::new(),
        }
    );
    reopened.close().await;
}

#[test]
fn historical_stopped_scheduling_events_retain_their_canonical_replay_semantics() {
    let definition = definition();
    let run = CircuitRunV2::prepare(&definition, &start(), &fence(/*generation*/ 1))
        .expect("initial state");
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Advance { quantum: 1 },
            /*now_ms*/ 10,
        )
        .expect("original dispatch");
    let (mut run, _) = run
        .reduce(&definition, &CircuitEventV2::Cancel, /*now_ms*/ 11)
        .expect("stopped with an unresolved original computation");
    for event in [
        CircuitEventV2::Advance { quantum: 1 },
        CircuitEventV2::Cancel,
    ] {
        let recorded = CircuitLedgerEventV2::Applied {
            fence: CircuitFenceIdentityV2::from_fence(&fence(/*generation*/ 1)).expect("identity"),
            expected_revision: run.revision(),
            now_ms: 12,
            event,
        };
        let (next, dispatches) = recorded
            .replay(
                Some(&run),
                &definition,
                &fence(/*generation*/ 1).owner_agent_id,
            )
            .expect("previously persisted events are not rejected by the new admission gate");
        assert!(dispatches.is_empty());
        assert_eq!(
            (
                next.activations(),
                next.budget(),
                next.stop_reason(),
                next.outcome()
            ),
            (
                run.activations(),
                run.budget(),
                run.stop_reason(),
                run.outcome()
            )
        );
        assert_eq!(next.revision(), run.revision() + 1);
        run = next;
    }
}
