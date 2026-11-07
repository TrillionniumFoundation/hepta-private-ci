use pretty_assertions::assert_eq;

use crate::circuit_history::CircuitFenceIdentityV2;
use crate::circuit_history::CircuitLedgerEventV2;
use crate::circuit_runtime_tests::completion;
use crate::circuit_runtime_tests::definition;
use crate::circuit_runtime_tests::digest;
use crate::circuit_runtime_tests::fence;
use crate::circuit_runtime_tests::start;
use crate::*;

async fn pending(
    event_limit: u32,
) -> (tempfile::TempDir, AutomationStore, CircuitCommandReceiptV2) {
    pending_until(event_limit, /*elapsed_limit*/ 1_000).await
}

async fn pending_until(
    event_limit: u32,
    elapsed_limit: u64,
) -> (tempfile::TempDir, AutomationStore, CircuitCommandReceiptV2) {
    let directory = tempfile::tempdir().expect("private durable owner");
    let store = AutomationStore::open_root(
        directory.path().join("automation"),
        fence(/*generation*/ 1).owner_agent_id,
    )
    .await
    .expect("normal AutomationStore migrations");
    let mut bounded = definition();
    bounded.limits.max_events = event_limit;
    bounded.limits.max_elapsed_ms = elapsed_limit;
    bounded.limits.max_activations = 2;
    bounded.limits.max_frontier = 2;
    let initial = CircuitStartV2 {
        lease_duration_ms: 1_000,
        ..start()
    };
    let created = store
        .create_bounded_circuit_run(&bounded, &initial, &fence(/*generation*/ 1))
        .await
        .expect("create");
    let dispatched = store
        .apply_bounded_circuit_command(&command(
            &created.run,
            "dispatch",
            CircuitEventV2::Advance { quantum: 1 },
        ))
        .await
        .expect("commit original invocation");
    (directory, store, dispatched)
}

fn command(run: &CircuitRunV2, id: &str, event: CircuitEventV2) -> CircuitCommandV2 {
    CircuitCommandV2 {
        run_id: run.run_id().to_string(),
        command_id: id.to_string(),
        fence: fence(/*generation*/ 1),
        expected_revision: run.revision(),
        now_ms: 12,
        event,
    }
}

fn lease(run: &CircuitRunV2, id: &str) -> CircuitLeaseClaimV2 {
    CircuitLeaseClaimV2 {
        run_id: run.run_id().to_string(),
        command_id: id.to_string(),
        fence: fence(/*generation*/ 1),
        expected_revision: run.revision(),
        now_ms: 12,
        lease_duration_ms: 1_000,
    }
}

#[tokio::test]
async fn stopped_polling_cannot_spend_the_original_unknown_settlement_slot() {
    let (_directory, store, dispatched) = pending(/*event_limit*/ 2).await;
    let original = &dispatched.dispatches[0];
    let unknown = store
        .apply_bounded_circuit_command(&command(
            &dispatched.run,
            "unknown",
            CircuitEventV2::MarkIndeterminate {
                activation_id: original.activation_id,
                observation_digest: digest("lost-original-result"),
            },
        ))
        .await
        .expect("preserve original unknown invocation");
    let cancellation = command(&unknown.run, "cancel-once", CircuitEventV2::Cancel);
    let stopped = store
        .apply_bounded_circuit_command(&cancellation)
        .await
        .expect("stop admissions");
    assert_eq!(
        (
            stopped.run.outcome(),
            stopped.run.unresolved(),
            stopped.run.budget().reserved()
        ),
        (None, 1, 5)
    );
    for index in 0..80 {
        for event in [
            CircuitEventV2::Cancel,
            CircuitEventV2::Advance { quantum: 1 },
        ] {
            assert!(matches!(
                store
                    .apply_bounded_circuit_command(&command(
                        &stopped.run,
                        &format!("poll-{index}"),
                        event,
                    ))
                    .await,
                Err(TaskFlowError::Invalid(_))
            ));
        }
    }
    let duplicate = store
        .apply_bounded_circuit_command(&cancellation)
        .await
        .expect("exact stop retry");
    assert_eq!(
        duplicate,
        CircuitCommandReceiptV2 {
            status: CircuitCommandStatusV2::AlreadyApplied,
            run: stopped.run.clone(),
            dispatches: Vec::new(),
        }
    );
    let root = store.path().parent().expect("root").to_path_buf();
    let owner = store.owner_agent_id().clone();
    store.close().await;
    let reopened = AutomationStore::open_root(root, owner)
        .await
        .expect("new owner connection");
    assert_eq!(
        reopened.bounded_circuit_run("run-1").await.expect("replay"),
        Some(stopped.run.clone())
    );
    let observed = completion(original, &["done"], "original-result");
    let settled = reopened
        .apply_bounded_circuit_command(&command(
            &stopped.run,
            "settle-original",
            CircuitEventV2::Reconcile {
                completion: observed.clone(),
            },
        ))
        .await
        .expect("settlement capacity survived polling and restart");
    assert_eq!(
        (
            settled.run.outcome(),
            settled.run.stop_reason(),
            settled.run.unresolved(),
            settled.run.budget().spent(),
            settled.run.budget().reserved()
        ),
        (
            Some(CircuitExitV2::Failed),
            Some(CircuitStopReasonV2::Cancelled),
            0,
            3,
            0
        ),
    );
    let activation = &settled.run.activations()[&original.activation_id];
    assert_eq!(
        (&activation.output_digest, &activation.receipt_digest),
        (
            &Some(observed.output_digest),
            &Some(observed.receipt_digest)
        )
    );
    assert!(settled.dispatches.is_empty());
    reopened.close().await;
}

#[tokio::test]
async fn the_event_limit_stop_is_persisted_once_without_refunding_inflight_work() {
    let (_directory, store, dispatched) = pending(/*event_limit*/ 1).await;
    let stopped = store
        .apply_bounded_circuit_command(&command(
            &dispatched.run,
            "event-limit",
            CircuitEventV2::Advance { quantum: 1 },
        ))
        .await
        .expect("one durable limit stop");
    assert_eq!(
        (
            stopped.run.stop_reason(),
            stopped.run.revision(),
            stopped.run.unresolved(),
            stopped.run.budget().reserved()
        ),
        (Some(CircuitStopReasonV2::EventLimit), 2, 1, 5)
    );
    assert!(matches!(
        store
            .apply_bounded_circuit_command(&command(
                &stopped.run,
                "not-a-read",
                CircuitEventV2::Advance { quantum: 1 },
            ))
            .await,
        Err(TaskFlowError::Invalid(_))
    ));
    let settled = store
        .apply_bounded_circuit_command(&command(
            &stopped.run,
            "actual-completion",
            CircuitEventV2::Complete {
                completion: completion(&dispatched.dispatches[0], &["done"], "original-result"),
            },
        ))
        .await
        .expect("original work remains chargeable after event limit");
    assert_eq!(
        (
            settled.run.outcome(),
            settled.run.budget().spent(),
            settled.run.budget().reserved()
        ),
        (Some(CircuitExitV2::Failed), 3, 0)
    );
    store.close().await;
}

#[tokio::test]
async fn exhausted_ordinary_leases_reserve_an_expired_owner_handoff_and_original_reconciliation() {
    let (_directory, store, dispatched) = pending(/*event_limit*/ 4).await;
    let mut run = dispatched.run;
    let mut last_claim = lease(&run, "initial");
    for index in 0..62 {
        last_claim = lease(&run, &format!("renew-{index}"));
        run = store
            .claim_bounded_circuit_run(&last_claim)
            .await
            .expect("bounded lease renewal")
            .run;
    }
    let root = store.path().parent().expect("root").to_path_buf();
    let owner = store.owner_agent_id().clone();
    store.close().await;
    let reopened = AutomationStore::open_root(root, owner)
        .await
        .expect("recover derived allowance");
    let exact_retry = reopened
        .claim_bounded_circuit_run(&last_claim)
        .await
        .expect("lost renewal acknowledgement");
    assert_eq!(
        exact_retry,
        CircuitCommandReceiptV2 {
            status: CircuitCommandStatusV2::AlreadyApplied,
            run: run.clone(),
            dispatches: Vec::new(),
        }
    );
    assert!(matches!(
        reopened
            .claim_bounded_circuit_run(&lease(&run, "renewal-overflow"))
            .await,
        Err(TaskFlowError::Invalid(_))
    ));
    assert_eq!(
        reopened
            .bounded_circuit_run("run-1")
            .await
            .expect("unchanged readback"),
        Some(run.clone())
    );
    let unknown = reopened
        .apply_bounded_circuit_command(&command(
            &run,
            "unknown",
            CircuitEventV2::MarkIndeterminate {
                activation_id: dispatched.dispatches[0].activation_id,
                observation_digest: digest("unknown-original"),
            },
        ))
        .await
        .expect("unknown observation remains reserved");
    let expired_at = 1_012;
    assert!(matches!(
        reopened
            .apply_bounded_circuit_command(&CircuitCommandV2 {
                now_ms: expired_at,
                ..command(&unknown.run, "expired-old-owner", CircuitEventV2::Cancel)
            })
            .await,
        Err(TaskFlowError::StaleFence)
    ));
    let takeover = CircuitLeaseClaimV2 {
        fence: fence(/*generation*/ 2),
        now_ms: expired_at,
        ..lease(&unknown.run, "reserved-recovery-handoff")
    };
    let recovered = reopened
        .claim_bounded_circuit_run(&takeover)
        .await
        .expect("63rd transition belongs to expired-owner recovery");
    assert_eq!(
        (
            recovered.run.stop_reason(),
            recovered.run.unresolved(),
            recovered.run.budget().reserved()
        ),
        (Some(CircuitStopReasonV2::Deadline), 1, 5)
    );
    assert!(recovered.dispatches.is_empty());
    assert!(matches!(
        reopened
            .claim_bounded_circuit_run(&CircuitLeaseClaimV2 {
                command_id: "no-unlimited-recovery-renewal".to_string(),
                expected_revision: recovered.run.revision(),
                ..takeover.clone()
            })
            .await,
        Err(TaskFlowError::Invalid(_))
    ));
    let settled = reopened
        .apply_bounded_circuit_command(&CircuitCommandV2 {
            fence: fence(/*generation*/ 2),
            now_ms: expired_at + 1,
            ..command(
                &recovered.run,
                "original-reconciliation",
                CircuitEventV2::Reconcile {
                    completion: completion(&dispatched.dispatches[0], &["done"], "original-result"),
                },
            )
        })
        .await
        .expect("original unknown result can still settle after old lease expires");
    assert_eq!(
        (
            settled.run.outcome(),
            settled.run.unresolved(),
            settled.run.budget().spent(),
            settled.run.budget().reserved()
        ),
        (Some(CircuitExitV2::Failed), 0, 3, 0)
    );
    reopened.close().await;
}

#[tokio::test]
async fn final_recovery_handoff_cannot_dispatch_fresh_work_before_the_deadline() {
    let (_directory, store, dispatched) =
        pending_until(/*event_limit*/ 128, /*elapsed_limit*/ 10_000).await;
    let mut run = dispatched.run;
    for index in 0..62 {
        run = store
            .claim_bounded_circuit_run(&lease(&run, &format!("renew-{index}")))
            .await
            .unwrap()
            .run;
    }
    let recovered = store
        .claim_bounded_circuit_run(&CircuitLeaseClaimV2 {
            fence: fence(/*generation*/ 2),
            now_ms: 1_012,
            ..lease(&run, "final-recovery")
        })
        .await
        .expect("one original-identity recovery handoff");
    assert_eq!(
        (
            recovered.run.stop_reason(),
            recovered.run.unresolved(),
            recovered.run.budget().reserved()
        ),
        (None, 1, 5)
    );
    assert_eq!(
        recovered.run.activations()[&dispatched.dispatches[0].activation_id].status,
        CircuitActivationStatusV2::Indeterminate
    );
    let reconciled = store
        .apply_bounded_circuit_command(&CircuitCommandV2 {
            fence: fence(/*generation*/ 2),
            now_ms: 1_013,
            ..command(
                &recovered.run,
                "original-result",
                CircuitEventV2::Reconcile {
                    completion: completion(
                        &dispatched.dispatches[0],
                        &["again"],
                        "original-result",
                    ),
                },
            )
        })
        .await
        .expect("settle original invocation without granting new execution");
    let poll = CircuitCommandV2 {
        fence: fence(/*generation*/ 2),
        now_ms: 1_024,
        ..command(
            &reconciled.run,
            "do-not-redrive-feedback",
            CircuitEventV2::Advance { quantum: 1 },
        )
    };
    assert!(matches!(
        store.apply_bounded_circuit_command(&poll).await,
        Err(TaskFlowError::Invalid(_))
    ));
    assert_eq!(
        store.bounded_circuit_run("run-1").await.unwrap(),
        Some(reconciled.run.clone())
    );
    let stopped = store
        .apply_bounded_circuit_command(&CircuitCommandV2 {
            fence: fence(/*generation*/ 2),
            now_ms: 1_024,
            ..command(&reconciled.run, "final-stop", CircuitEventV2::Cancel)
        })
        .await
        .expect("the separate final stop slot remains available");
    assert_eq!(
        (
            stopped.run.outcome(),
            stopped.run.unresolved(),
            stopped.run.budget().spent(),
            stopped.run.budget().reserved()
        ),
        (Some(CircuitExitV2::Failed), 0, 3, 0)
    );
    assert!(stopped.dispatches.is_empty());
    store.close().await;
}

// Produce the canonical bytes accepted by the prior writer, without applying the
// new admission-only guard. The same reducer, event hashes and SQLite projection
// are used so this exercises compatibility with an existing V2 journal.
async fn legacy_append(
    store: &AutomationStore,
    command_id: &str,
    event: CircuitLedgerEventV2,
) -> CircuitRunV2 {
    let mut tx = store
        .taskflow_pool()
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("legacy writer");
    let history = super::load(&mut tx, store.owner_agent_id(), "run-1")
        .await
        .expect("legacy prefix")
        .expect("run");
    let (run, dispatches) = event
        .replay(
            Some(&history.run),
            &history.definition,
            store.owner_agent_id(),
        )
        .expect("original V2 reducer");
    assert!(dispatches.is_empty());
    let tail = super::append(&mut tx, &run, command_id, &event, &history.last_digest)
        .await
        .expect("original event encoding");
    sqlx::query("UPDATE circuit_v2_runs SET revision = ?, state_json = ?, state_digest = ?, last_event_digest = ? WHERE run_id = ?")
        .bind(i64::try_from(run.revision()).expect("bounded revision"))
        .bind(super::encode(&run).expect("state bytes")).bind(run.state_digest().expect("state digest").as_str())
        .bind(tail.as_str()).bind(run.run_id()).execute(&mut *tx).await.expect("legacy projection");
    tx.commit().await.expect("legacy durable history");
    run
}

#[tokio::test]
async fn existing_v2_history_with_extra_renewals_and_stopped_polls_still_replays() {
    let (_directory, store, dispatched) = pending(/*event_limit*/ 8).await;
    let mut run = dispatched.run;
    for index in 0..64 {
        run = legacy_append(
            &store,
            &format!("legacy-renew-{index}"),
            CircuitLedgerEventV2::Claimed {
                fence: CircuitFenceIdentityV2::from_fence(&fence(/*generation*/ 1))
                    .expect("identity"),
                expected_revision: run.revision(),
                now_ms: 12,
                lease_duration_ms: 1_000,
            },
        )
        .await;
    }
    run = store
        .apply_bounded_circuit_command(&command(&run, "stop", CircuitEventV2::Cancel))
        .await
        .expect("stop")
        .run;
    run = legacy_append(
        &store,
        "legacy-stopped-poll",
        CircuitLedgerEventV2::Applied {
            fence: CircuitFenceIdentityV2::from_fence(&fence(/*generation*/ 1)).expect("identity"),
            expected_revision: run.revision(),
            now_ms: 12,
            event: CircuitEventV2::Advance { quantum: 1 },
        },
    )
    .await;
    assert_eq!(
        store
            .bounded_circuit_run("run-1")
            .await
            .expect("original hashes remain valid"),
        Some(run.clone())
    );
    assert!(matches!(
        store
            .claim_bounded_circuit_run(&lease(&run, "new-overflow"))
            .await,
        Err(TaskFlowError::Invalid(_))
    ));
    let settled = store
        .apply_bounded_circuit_command(&command(
            &run,
            "original-result",
            CircuitEventV2::Complete {
                completion: completion(&dispatched.dispatches[0], &["done"], "original-result"),
            },
        ))
        .await
        .expect("compatible old history may still settle its original work");
    assert_eq!(
        (
            settled.run.outcome(),
            settled.run.budget().spent(),
            settled.run.budget().reserved()
        ),
        (Some(CircuitExitV2::Failed), 3, 0)
    );
    store.close().await;
}
