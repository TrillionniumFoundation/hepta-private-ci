//! Canonical histories written before stopped polling had a live admission gate.

use pretty_assertions::assert_eq;

use super::*;
use crate::circuit_journal;

enum RecoveryCase {
    LiveRenewal,
    ExpiredTakeover,
}

#[tokio::test]
async fn legacy_stopped_history_reserves_actual_pending_settlement_slots() {
    for case in [RecoveryCase::LiveRenewal, RecoveryCase::ExpiredTakeover] {
        let (_directory, store, run, dispatch) = pending_run().await;
        let stopped = store
            .apply_bounded_circuit_command(&command(
                &run,
                "legacy-stop",
                CircuitEventV2::Cancel,
                /*now_ms*/ 13,
            ))
            .await
            .expect("stop leaves the original computation pending");

        // Reproduce an old owner's real canonical rows, including each digest
        // and the final projection. The reducer intentionally still accepts
        // these historical events; the new live polling gate must not rewrite
        // them or make an otherwise verifiable database unreadable.
        let mut tx = store.taskflow_pool().begin_with("BEGIN IMMEDIATE")
            .await.expect("legacy transaction");
        let history = circuit_journal::load(&mut tx, store.owner_agent_id(), "run-1")
            .await.expect("verified initial history").expect("run");
        let mut run = history.run;
        let mut previous = history.last_digest;
        for index in 0..63 {
            let event = CircuitLedgerEventV2::Applied {
                fence: CircuitFenceIdentityV2::from_fence(&fence(/*generation*/ 1))
                    .expect("original writer"),
                expected_revision: run.revision(),
                now_ms: 14,
                event: CircuitEventV2::Advance { quantum: 1 },
            };
            let (next, dispatches) = event
                .replay(Some(&run), &history.definition, store.owner_agent_id())
                .expect("old stopped poll remains replayable");
            assert!(dispatches.is_empty());
            previous = circuit_journal::append(
                &mut tx,
                &next,
                &format!("legacy-poll-{index}"),
                &event,
                &previous,
            ).await.expect("canonical historical event");
            run = next;
        }
        let updated = sqlx::query(
            "UPDATE circuit_v2_runs
             SET revision = ?, state_json = ?, state_digest = ?, last_event_digest = ?
             WHERE owner_agent_id = ? AND run_id = ? AND revision = ? AND state_digest = ?",
        )
        .bind(i64::try_from(run.revision()).expect("bounded revision"))
        .bind(circuit_journal::encode(&run).expect("canonical state"))
        .bind(run.state_digest().expect("state digest").as_str())
        .bind(previous.as_str())
        .bind(store.owner_agent_id().as_str())
        .bind(run.run_id())
        .bind(i64::try_from(stopped.run.revision()).expect("previous revision"))
        .bind(stopped.run.state_digest().expect("previous digest").as_str())
        .execute(&mut *tx)
        .await.expect("historical projection");
        assert_eq!(updated.rows_affected(), 1);
        tx.commit().await.expect("durable historical fixture");
        let store = reopen(store).await;
        assert_eq!(
            store.bounded_circuit_run("run-1").await.expect("legacy canonical replay"),
            Some(run.clone())
        );
        assert_eq!((run.revision(), run.unresolved()), (66, 1));

        let (generation, claim_time) = match case {
            RecoveryCase::LiveRenewal => (1, 15),
            RecoveryCase::ExpiredTakeover => (2, 110),
        };
        let claim = CircuitLeaseClaimV2 {
            run_id: "run-1".to_string(),
            command_id: "post-upgrade-lease".to_string(),
            fence: fence(generation),
            expected_revision: run.revision(),
            now_ms: claim_time,
            lease_duration_ms: 100,
        };
        let (unknown, receipt_time) = match case {
            RecoveryCase::LiveRenewal => {
                assert!(matches!(
                    store.claim_bounded_circuit_run(&claim).await,
                    Err(TaskFlowError::Invalid(message))
                        if message == "circuit maintenance would consume reconciliation slots"
                ));
                assert_eq!(
                    store.bounded_circuit_run("run-1").await.expect("atomic rejection"),
                    Some(run.clone())
                );
                let unknown = store
                    .apply_bounded_circuit_command(&command(
                        &run,
                        "original-unknown-after-upgrade",
                        CircuitEventV2::MarkIndeterminate {
                            activation_id: dispatch.activation_id,
                            observation_digest: digest("original-late-observation"),
                        },
                        /*now_ms*/ 16,
                    ))
                    .await.expect("the original unknown marker retains its slot");
                (unknown.run, 17)
            }
            RecoveryCase::ExpiredTakeover => {
                let takeover = store.claim_bounded_circuit_run(&claim)
                    .await.expect("expired claim itself makes the original work unknown");
                assert!(takeover.dispatches.is_empty());
                (takeover.run, 111)
            }
        };
        assert_eq!(
            (
                unknown.revision(),
                unknown.activations()[&dispatch.activation_id].status,
                unknown.budget().reserved(),
            ),
            (67, CircuitActivationStatusV2::Indeterminate, 5)
        );
        let mut actual = completion(&dispatch, &["done"], "original-legacy-result");
        actual.actual_work = 7;
        let mut terminal = command(
            &unknown,
            "original-terminal-after-upgrade",
            CircuitEventV2::Reconcile { completion: actual },
            receipt_time,
        );
        terminal.fence = claim.fence;
        let finished = store.apply_bounded_circuit_command(&terminal)
            .await.expect("the original receipt fits exactly at the history bound");
        assert_eq!(
            (
                finished.run.revision(),
                finished.run.outcome(),
                finished.run.budget().spent(),
                finished.run.budget().reserved(),
            ),
            (68, Some(CircuitExitV2::Failed), 7, 0)
        );
        let store = reopen(store).await;
        assert_eq!(
            store.bounded_circuit_run("run-1").await.expect("terminal historical replay"),
            Some(finished.run.clone())
        );
        assert_eq!(
            store.apply_bounded_circuit_command(&terminal).await.expect("terminal ACK retry"),
            CircuitCommandReceiptV2 {
                status: CircuitCommandStatusV2::AlreadyApplied,
                run: finished.run,
                dispatches: Vec::new(),
            }
        );
        store.close().await;
    }
}
