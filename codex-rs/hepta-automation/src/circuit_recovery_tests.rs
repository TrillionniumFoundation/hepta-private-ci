use pretty_assertions::assert_eq;

use crate::circuit_history::CircuitFenceIdentityV2;
use crate::circuit_history::CircuitLedgerEventV2;
use crate::circuit_journal;
use crate::circuit_runtime_tests::completion;
use crate::circuit_runtime_tests::definition;
use crate::circuit_runtime_tests::digest;
use crate::circuit_runtime_tests::fence;
use crate::circuit_runtime_tests::start;
use crate::*;

async fn store() -> (tempfile::TempDir, AutomationStore) {
    let directory = tempfile::tempdir().expect("private temporary owner");
    let store = AutomationStore::open_root(
        directory.path().join("automation"),
        fence(/*generation*/ 1).owner_agent_id,
    )
    .await
    .expect("normal AutomationStore open/migrations");
    (directory, store)
}

fn command(run: &CircuitRunV2, id: &str, event: CircuitEventV2) -> CircuitCommandV2 {
    CircuitCommandV2 {
        run_id: run.run_id().to_string(),
        command_id: id.to_string(),
        fence: fence(/*generation*/ 1),
        expected_revision: run.revision(),
        now_ms: 11 + run.revision(),
        event,
    }
}

#[tokio::test]
async fn stopped_run_preserves_recovery_slots_across_reopen_and_owner_takeover() {
    let (_directory, store) = store().await;
    let mut definition = definition();
    definition.limits.max_events = 1;
    definition.limits.max_activations = 1;
    definition.limits.max_frontier = 1;
    let created = store
        .create_bounded_circuit_run(&definition, &start(), &fence(/*generation*/ 1))
        .await
        .expect("create");
    let active = store
        .apply_bounded_circuit_command(&command(
            &created.run,
            "dispatch",
            CircuitEventV2::Advance { quantum: 1 },
        ))
        .await
        .expect("dispatch before stopping");
    let cancel = command(&active.run, "cancel", CircuitEventV2::Cancel);
    let stopped = store
        .apply_bounded_circuit_command(&cancel)
        .await
        .expect("cancel unknown worker");
    assert_eq!(
        (
            stopped.run.stop_reason(),
            stopped.run.outcome(),
            stopped.run.unresolved(),
            stopped.run.budget().reserved(),
        ),
        (Some(CircuitStopReasonV2::Cancelled), None, 1, 5)
    );
    for index in 0..70 {
        let event = if index % 2 == 0 {
            CircuitEventV2::Advance { quantum: 1 }
        } else {
            CircuitEventV2::Cancel
        };
        assert_eq!(
            store
                .apply_bounded_circuit_command(&command(
                    &stopped.run,
                    &format!("stopped-poll-{index}"),
                    event,
                ))
                .await,
            Err(TaskFlowError::Invalid(
                "stopped circuit cannot schedule or cancel again".to_string()
            )),
            "new scheduling/cancellation must not consume reconciliation slots"
        );
    }
    assert_eq!(
        store.bounded_circuit_run("run-1").await.expect("unchanged"),
        Some(stopped.run.clone())
    );
    assert_eq!(
        store
            .apply_bounded_circuit_command(&cancel)
            .await
            .expect("retry"),
        CircuitCommandReceiptV2 {
            status: CircuitCommandStatusV2::AlreadyApplied,
            run: stopped.run.clone(),
            dispatches: vec![],
        }
    );
    let unknown = store
        .apply_bounded_circuit_command(&command(
            &stopped.run,
            "lost-worker-ack",
            CircuitEventV2::MarkIndeterminate {
                activation_id: active.dispatches[0].activation_id,
                observation_digest: digest("ack-lost-after-cancel"),
            },
        ))
        .await
        .expect("unknown work remains observable after stopping");
    let path = store.path().parent().expect("root").to_path_buf();
    let owner = store.owner_agent_id().clone();
    store.close().await;
    drop(store);
    let reopened = AutomationStore::open_root(path, owner)
        .await
        .expect("cold reopen");
    assert_eq!(
        reopened.bounded_circuit_run("run-1").await.expect("replay"),
        Some(unknown.run.clone())
    );
    let mut successor_fence = fence(/*generation*/ 2);
    successor_fence.owner_id = "successor-process".to_string();
    successor_fence.owner_epoch = 2;
    let successor = reopened
        .claim_bounded_circuit_run(&CircuitLeaseClaimV2 {
            run_id: "run-1".to_string(),
            command_id: "successor".to_string(),
            fence: successor_fence.clone(),
            expected_revision: unknown.run.revision(),
            now_ms: 110,
            lease_duration_ms: 100,
        })
        .await
        .expect("different writer acquires expired lease");
    let mut reconcile = CircuitCommandV2 {
        run_id: "run-1".to_string(),
        command_id: "actual-result".to_string(),
        fence: fence(/*generation*/ 1),
        expected_revision: successor.run.revision(),
        now_ms: 111,
        event: CircuitEventV2::Reconcile {
            completion: completion(&active.dispatches[0], &["done"], "actual-result"),
        },
    };
    assert!(matches!(
        reopened.apply_bounded_circuit_command(&reconcile).await,
        Err(TaskFlowError::StaleFence)
    ));
    reconcile.fence = successor_fence;
    let finished = reopened
        .apply_bounded_circuit_command(&reconcile)
        .await
        .expect("successor settles original invocation and actual cost");
    assert_eq!(
        (
            finished.run.outcome(),
            finished.run.stop_reason(),
            finished.run.budget().spent(),
            finished.run.budget().reserved(),
            finished.run.unresolved(),
            finished.dispatches,
        ),
        (
            Some(CircuitExitV2::Failed),
            Some(CircuitStopReasonV2::Cancelled),
            3,
            0,
            0,
            vec![]
        )
    );
    assert_eq!(
        reopened
            .apply_bounded_circuit_command(&cancel)
            .await
            .expect("original retry"),
        CircuitCommandReceiptV2 {
            status: CircuitCommandStatusV2::AlreadyApplied,
            run: finished.run,
            dispatches: vec![],
        }
    );
    reopened.close().await;
}

#[tokio::test]
async fn preexisting_stopped_noop_history_remains_readable_and_settleable() {
    let (_directory, store) = store().await;
    let created = store
        .create_bounded_circuit_run(&definition(), &start(), &fence(/*generation*/ 1))
        .await
        .expect("create");
    let active = store
        .apply_bounded_circuit_command(&command(
            &created.run,
            "dispatch",
            CircuitEventV2::Advance { quantum: 1 },
        ))
        .await
        .expect("dispatch");
    let stopped = store
        .apply_bounded_circuit_command(&command(&active.run, "cancel", CircuitEventV2::Cancel))
        .await
        .expect("stop");
    // Seed the exact canonical event an older writer could persist. The live
    // admission guard must not retroactively reject it during journal replay.
    let legacy_command = command(&stopped.run, "legacy-cancel", CircuitEventV2::Cancel);
    let event = CircuitLedgerEventV2::Applied {
        fence: CircuitFenceIdentityV2::from_fence(&legacy_command.fence).expect("fence"),
        expected_revision: legacy_command.expected_revision,
        now_ms: legacy_command.now_ms,
        event: legacy_command.event.clone(),
    };
    let mut tx = store
        .taskflow_pool()
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("lock");
    let history = circuit_journal::load(&mut tx, store.owner_agent_id(), "run-1")
        .await
        .expect("load")
        .expect("run");
    let (legacy, dispatches) = event
        .replay(
            Some(&history.run),
            &history.definition,
            store.owner_agent_id(),
        )
        .expect("historical reducer semantics");
    assert!(dispatches.is_empty());
    let last_digest = circuit_journal::append(
        &mut tx,
        &legacy,
        &legacy_command.command_id,
        &event,
        &history.last_digest,
    )
    .await
    .expect("canonical legacy event");
    sqlx::query("UPDATE circuit_v2_runs SET revision = ?, state_json = ?, state_digest = ?, last_event_digest = ?
        WHERE owner_agent_id = ? AND run_id = ?")
        .bind(i64::try_from(legacy.revision()).expect("revision"))
        .bind(circuit_journal::encode(&legacy).expect("state"))
        .bind(legacy.state_digest().expect("state digest").as_str())
        .bind(last_digest.as_str())
        .bind(store.owner_agent_id().as_str())
        .bind("run-1")
        .execute(&mut *tx).await.expect("legacy projection");
    tx.commit().await.expect("legacy commit");
    let path = store.path().parent().expect("root").to_path_buf();
    let owner = store.owner_agent_id().clone();
    store.close().await;
    drop(store);
    let reopened = AutomationStore::open_root(path, owner)
        .await
        .expect("cold reopen");
    assert_eq!(
        reopened
            .bounded_circuit_run("run-1")
            .await
            .expect("legacy replay"),
        Some(legacy.clone())
    );
    assert_eq!(
        reopened
            .apply_bounded_circuit_command(&legacy_command)
            .await
            .expect("legacy retry"),
        CircuitCommandReceiptV2 {
            status: CircuitCommandStatusV2::AlreadyApplied,
            run: legacy.clone(),
            dispatches: vec![],
        }
    );
    let finished = reopened
        .apply_bounded_circuit_command(&command(
            &legacy,
            "original-result",
            CircuitEventV2::Complete {
                completion: completion(&active.dispatches[0], &["done"], "original-result"),
            },
        ))
        .await
        .expect("settlement of preexisting stopped run");
    assert_eq!(
        (
            finished.run.outcome(),
            finished.run.budget().spent(),
            finished.run.budget().reserved()
        ),
        (Some(CircuitExitV2::Failed), 3, 0)
    );
    reopened.close().await;
}
