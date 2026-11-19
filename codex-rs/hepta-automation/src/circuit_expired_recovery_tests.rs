use std::collections::BTreeMap;

use pretty_assertions::assert_eq;

use super::command;
use super::pending_run;
use super::reopen;
use crate::circuit_history::CircuitRecoverySettlementV2;
use crate::circuit_runtime_tests::completion;
use crate::circuit_runtime_tests::definition;
use crate::circuit_runtime_tests::digest;
use crate::circuit_runtime_tests::fence;
use crate::circuit_runtime_tests::start;
use crate::*;

#[tokio::test]
async fn expired_recovery_settles_after_the_lease_allowance_is_exhausted() {
    let (_directory, store, run, dispatch) = pending_run().await;
    let unknown = store
        .apply_bounded_circuit_command(&command(
            &run,
            "unknown",
            CircuitEventV2::MarkIndeterminate {
                activation_id: dispatch.activation_id,
                observation_digest: digest("unknown"),
            },
            /*now_ms*/ 13,
        ))
        .await
        .expect("retain original work");
    let mut run = store
        .apply_bounded_circuit_command(&command(
            &unknown.run,
            "stop",
            CircuitEventV2::Cancel,
            /*now_ms*/ 14,
        ))
        .await
        .expect("stop")
        .run;
    for index in 0..63 {
        run = store
            .claim_bounded_circuit_run(&CircuitLeaseClaimV2 {
                run_id: run.run_id().to_string(),
                command_id: format!("renewal-{index}"),
                fence: fence(/*generation*/ 1),
                expected_revision: run.revision(),
                now_ms: 15 + index,
                lease_duration_ms: 1_000,
            })
            .await
            .expect("bounded renewal")
            .run;
    }
    let store = reopen(store).await;
    let mut actual = completion(&dispatch, &["done"], "late-original");
    actual.actual_work = 7;
    assert!(matches!(
        store
            .apply_bounded_circuit_command(&command(
                &run,
                "expired-old-writer",
                CircuitEventV2::Reconcile {
                    completion: actual.clone()
                },
                /*now_ms*/ 1_077,
            ))
            .await,
        Err(TaskFlowError::StaleFence)
    ));
    assert!(matches!(
        store
            .claim_bounded_circuit_run(&CircuitLeaseClaimV2 {
                run_id: run.run_id().to_string(),
                command_id: "no-lease-slot".to_string(),
                fence: fence(/*generation*/ 2),
                expected_revision: run.revision(),
                now_ms: 1_077,
                lease_duration_ms: 100,
            })
            .await,
        Err(TaskFlowError::Invalid(_))
    ));
    let request = CircuitRecoverySettlementV2 {
        run_id: run.run_id().to_string(),
        command_id: "late-original-settlement".to_string(),
        fence: fence(/*generation*/ 2),
        expected_revision: run.revision(),
        now_ms: 1_077,
        execution_request_digest: digest("original-cell-request"),
        completion: actual.clone(),
    };
    let finished = store
        .reconcile_expired_circuit_computation(&request)
        .await
        .expect("last reserved slot settles after the final lease expires");
    assert_eq!(
        (
            finished.run.revision(),
            finished.run.outcome(),
            finished.run.stop_reason(),
            finished.run.budget().spent(),
            finished.run.budget().reserved(),
            finished.run.budget().available(),
            finished.run.unresolved(),
            finished.dispatches
        ),
        (
            68,
            Some(CircuitExitV2::Failed),
            Some(CircuitStopReasonV2::Cancelled),
            7,
            0,
            0,
            0,
            Vec::new()
        )
    );
    let store = reopen(store).await;
    assert_eq!(
        store
            .reconcile_expired_circuit_computation(&request)
            .await
            .expect("lost ACK retry"),
        CircuitCommandReceiptV2 {
            status: CircuitCommandStatusV2::AlreadyApplied,
            run: finished.run.clone(),
            dispatches: Vec::new(),
        }
    );
    let mut conflict = request.clone();
    conflict.completion.actual_work = 6;
    assert!(matches!(
        store.reconcile_expired_circuit_computation(&conflict).await,
        Err(TaskFlowError::Conflict(_))
    ));
    let trace = store
        .bounded_circuit_committed_trace(run.run_id())
        .await
        .expect("verified trace")
        .expect("run");
    assert_eq!(trace.run(), &finished.run);
    assert_eq!(
        trace.completions(),
        &BTreeMap::from([(dispatch.activation_id, actual)])
    );
    store.close().await;
}

#[tokio::test]
async fn expired_recovery_rejects_live_stale_and_changed_original_requests() {
    let (_directory, store, run, dispatch) = pending_run().await;
    let request = CircuitRecoverySettlementV2 {
        run_id: run.run_id().to_string(),
        command_id: "recover".to_string(),
        fence: fence(/*generation*/ 2),
        expected_revision: run.revision(),
        now_ms: 110,
        execution_request_digest: digest("original-cell-request"),
        completion: completion(&dispatch, &["done"], "original"),
    };
    let mut live = request.clone();
    live.now_ms = 109;
    let mut stale = request.clone();
    stale.fence = fence(/*generation*/ 1);
    let mut revision = request.clone();
    revision.expected_revision += 1;
    let mut changed_request = request.clone();
    changed_request.execution_request_digest = digest("another-cell-request");
    let mut changed_invocation = request.clone();
    changed_invocation.completion.invocation_digest = digest("another-invocation");
    for invalid in [live, stale, revision, changed_request, changed_invocation] {
        assert!(
            store
                .reconcile_expired_circuit_computation(&invalid)
                .await
                .is_err()
        );
        assert_eq!(
            store
                .bounded_circuit_run(run.run_id())
                .await
                .expect("unchanged"),
            Some(run.clone())
        );
    }
    let finished = store
        .reconcile_expired_circuit_computation(&request)
        .await
        .expect("expired in-flight original may settle atomically");
    assert_eq!(
        (
            finished.run.outcome(),
            finished.run.stop_reason(),
            finished.run.budget().spent(),
            finished.run.budget().reserved(),
            finished.run.unresolved(),
            finished.dispatches
        ),
        (
            Some(CircuitExitV2::Failed),
            Some(CircuitStopReasonV2::Cancelled),
            3,
            0,
            0,
            Vec::new()
        )
    );
    store.close().await;
}

#[tokio::test]
async fn recovery_owner_settles_multiple_receipts_without_a_new_lease() {
    let mut definition = definition();
    let program = &mut definition.programs[0];
    program.nodes[0].kind = CircuitNodeKindV2::Compute { max_work: 5 };
    let mut sibling = program.nodes[0].clone();
    sibling.node_id = "sibling".to_string();
    program.nodes.push(sibling);
    program.edges[1].to = "sibling".to_string();
    program.edges.push(CircuitEdgeV2 {
        edge_id: "finish".to_string(),
        from: "sibling".to_string(),
        to: "success".to_string(),
        feedback_delay_ms: None,
    });
    let mut original_fence = fence(/*generation*/ 1);
    original_fence.owner_epoch = 2;
    let directory = tempfile::tempdir().expect("private owner");
    let store = AutomationStore::open_root(
        directory
            .path()
            .canonicalize()
            .expect("canonical private owner")
            .join("automation"),
        original_fence.owner_agent_id.clone(),
    )
    .await
    .expect("store");
    let created = store
        .create_bounded_circuit_run(&definition, &start(), &original_fence)
        .await
        .expect("create");
    let command = |run: &CircuitRunV2, id: &str, event, now_ms| CircuitCommandV2 {
        fence: original_fence.clone(),
        ..command(run, id, event, now_ms)
    };
    let active = store
        .apply_bounded_circuit_command(&command(
            &created.run,
            "first-dispatch",
            CircuitEventV2::Advance { quantum: 1 },
            /*now_ms*/ 11,
        ))
        .await
        .expect("first computation");
    let first = completion(&active.dispatches[0], &["again", "done"], "fanout");
    let completed = store
        .apply_bounded_circuit_command(&command(
            &active.run,
            "fanout",
            CircuitEventV2::Complete {
                completion: first.clone(),
            },
            /*now_ms*/ 12,
        ))
        .await
        .expect("fanout");
    let active = store
        .apply_bounded_circuit_command(&command(
            &completed.run,
            "two-dispatches",
            CircuitEventV2::Advance { quantum: 2 },
            /*now_ms*/ 22,
        ))
        .await
        .expect("two pending computations");
    assert_eq!(active.dispatches.len(), 2);
    for (index, dispatch) in active.dispatches.iter().enumerate() {
        store
            .claim_circuit_computation(&CircuitComputationClaimV2 {
                run_id: active.run.run_id().to_string(),
                activation_id: dispatch.activation_id,
                command_id: format!("original-claim-{index}"),
                fence: original_fence.clone(),
                expected_revision: active.run.revision() + index as u64,
                now_ms: 23,
                execution_request_digest: digest(&format!("request-{index}")),
            })
            .await
            .expect("durable original claim");
    }
    let mut run = store
        .bounded_circuit_run(active.run.run_id())
        .await
        .expect("read")
        .expect("run");
    let mut recovery_fence = fence(/*generation*/ 2);
    recovery_fence.owner_epoch = 2;
    let mut expected = BTreeMap::from([(first.activation_id, first)]);
    let mut store = store;
    for (index, dispatch) in active.dispatches.iter().enumerate() {
        let actual = CircuitCompletionV2 {
            selected_edges: dispatch.candidate_edges.clone(),
            ..completion(dispatch, &[], &format!("late-{index}"))
        };
        let request = CircuitRecoverySettlementV2 {
            run_id: run.run_id().to_string(),
            command_id: format!("settle-{index}"),
            fence: recovery_fence.clone(),
            expected_revision: run.revision(),
            now_ms: 110 + index as u64,
            execution_request_digest: digest(&format!("request-{index}")),
            completion: actual.clone(),
        };
        let mut stale = request.clone();
        stale.fence = if index == 0 {
            fence(/*generation*/ 2)
        } else {
            original_fence.clone()
        };
        assert!(matches!(
            store.reconcile_expired_circuit_computation(&stale).await,
            Err(TaskFlowError::StaleFence)
        ));
        let receipt = store
            .reconcile_expired_circuit_computation(&request)
            .await
            .expect("same real recovery owner settles each original");
        assert!(receipt.dispatches.is_empty());
        run = receipt.run;
        assert_eq!(
            (run.unresolved(), run.budget().reserved()),
            (1 - index, 5 * (1 - index) as u64)
        );
        expected.insert(actual.activation_id, actual);
        store = reopen(store).await;
        if index == 0 {
            let mut next_fence = recovery_fence.clone();
            next_fence.generation += 1;
            assert!(matches!(
                store
                    .claim_bounded_circuit_run(&CircuitLeaseClaimV2 {
                        run_id: run.run_id().to_string(),
                        command_id: "must-not-reopen-execution".to_string(),
                        fence: next_fence,
                        expected_revision: run.revision(),
                        now_ms: 111,
                        lease_duration_ms: 100,
                    })
                    .await,
                Err(TaskFlowError::Conflict(_))
            ));
        }
    }
    let trace = store
        .bounded_circuit_committed_trace(run.run_id())
        .await
        .expect("trace")
        .expect("run");
    assert_eq!(trace.run(), &run);
    assert_eq!(trace.completions(), &expected);
    assert_eq!(
        (run.outcome(), run.budget().spent(), run.writer.generation),
        (Some(CircuitExitV2::Failed), 9, 2)
    );
    store.close().await;
}
