use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use tempfile::TempDir;
use tokio::sync::Notify;
use tokio::time::timeout;

use super::super::*;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;

#[derive(Default)]
struct Gate {
    entered: Notify,
    release: Notify,
}

struct Observer {
    outcome: LocalReconcileOutcome,
    gate: Option<Arc<Gate>>,
}

impl ProductionOutboxTarget for Observer {
    fn dispatch<'a>(&'a self, _request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        Box::pin(async { panic!("terminal observation must never dispatch") })
    }
}

impl FinalUseProductionOutboxTarget for Observer {
    fn destination_id(&self) -> &str {
        "target:race"
    }

    fn observe_terminal<'a>(
        &'a self,
        _request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        Box::pin(async move {
            if let Some(gate) = &self.gate {
                gate.entered.notify_one();
                gate.release.notified().await;
            }
            match self.outcome {
                LocalReconcileOutcome::Committed => ProductionTerminalObservation::Applied {
                    receipt: "independent durable target observation".to_string(),
                },
                LocalReconcileOutcome::Rejected => ProductionTerminalObservation::NotApplied {
                    reason: "independent durable negative observation".to_string(),
                },
                LocalReconcileOutcome::StillIndeterminate => {
                    ProductionTerminalObservation::Indeterminate {
                        reason: "target observation has no terminal evidence".to_string(),
                    }
                }
            }
        })
    }
}

struct Fixture {
    _temp: TempDir,
    writer: ProductionDurableWriter,
    revoked: Arc<AtomicBool>,
}

async fn make_fixture() -> Fixture {
    let temp = TempDir::new().expect("tempdir");
    let owner = agent_id(/*suffix*/ 88);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner,
        Sha256Digest::for_bytes(b"reconciliation race grant"),
        /*authority_epoch*/ 1,
        /*owner_epoch*/ 1,
        now_unix_seconds().expect("clock") + 3_600,
        ProductionAuthorityToken::from_verified_bytes(b"reconciliation race token".to_vec())
            .expect("token"),
    )
    .expect("authority");
    let revoked = Arc::new(AtomicBool::new(/*v*/ false));
    let checked_revocation = Arc::clone(&revoked);
    let verifier = move |_authority: &ProductionAuthorityLease, _agent: &AgentId| {
        if checked_revocation.load(Ordering::SeqCst) {
            Err("independently revoked race fixture authority".to_string())
        } else {
            Ok(())
        }
    };
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store,
        authority,
        Arc::new(verifier),
        "reconciliation:race",
        /*generation*/ 1,
    )
    .await
    .expect("writer");
    Fixture {
        _temp: temp,
        writer,
        revoked,
    }
}

async fn prepare_dispatch(
    writer: &ProductionDurableWriter,
    operation_id: &str,
) -> (ProductionDispatchRequest, String) {
    let intent = OperationIntentV1::new(
        StableId::new(operation_id).expect("operation id"),
        StableId::new(writer.owner_agent_id().as_str()).expect("owner"),
        StableId::new("target:race").expect("destination"),
        Digest32::of_bytes(b"{}"),
        Digest32::of_bytes(b"reconciliation race scope"),
        Generation::new(/*value*/ 1).expect("generation"),
        /*expected_predecessor*/ None,
    )
    .expect("operation");
    writer
        .prepare_operation(intent, "reconciliation.race", "{}")
        .await
        .expect("prepare");
    let request = writer
        .reconciliation_request(operation_id, "target:race")
        .await
        .expect("bound request");
    let claim = writer
        .lease
        .claim_dispatch(
            operation_id,
            &writer.authority.grant_digest,
            &request.operation_digest,
        )
        .await
        .expect("physical dispatch claim");
    (request, claim.event_id)
}

fn terminal_cases() -> [ProductionTargetOutcome; 3] {
    [
        ProductionTargetOutcome::Committed {
            receipt: "actual target commit receipt".to_string(),
        },
        ProductionTargetOutcome::NotApplied {
            reason: "actual target CAS rejection".to_string(),
        },
        ProductionTargetOutcome::Rejected {
            reason: "actual target request rejection".to_string(),
        },
    ]
}

fn expected_dispatch(
    request: ProductionDispatchRequest,
    outcome: ProductionTargetOutcome,
    local_event_id: String,
) -> ProductionDispatchReceipt {
    let (state, target_disposition, target_receipt, target_reason, external_effect) = match outcome
    {
        ProductionTargetOutcome::Committed { receipt } => (
            LocalOutcomeState::Committed,
            ProductionTargetDisposition::Committed,
            Some(receipt),
            None,
            true,
        ),
        ProductionTargetOutcome::NotApplied { reason } => (
            LocalOutcomeState::Rejected,
            ProductionTargetDisposition::NotApplied,
            None,
            Some(reason),
            false,
        ),
        ProductionTargetOutcome::Rejected { reason } => (
            LocalOutcomeState::Rejected,
            ProductionTargetDisposition::Rejected,
            None,
            Some(reason),
            false,
        ),
        ProductionTargetOutcome::Indeterminate { .. } => {
            panic!("fixture expects a terminal target outcome")
        }
    };
    ProductionDispatchReceipt {
        request,
        state,
        target_disposition,
        target_receipt,
        target_reason,
        local_event_id,
        external_effect,
    }
}

#[tokio::test]
async fn ack_during_observation_settles_same_result_and_supersedes_unknown_without_another_event() {
    for outcome in terminal_cases() {
        for observation in [
            if matches!(outcome, ProductionTargetOutcome::Committed { .. }) {
                LocalReconcileOutcome::Committed
            } else {
                LocalReconcileOutcome::Rejected
            },
            LocalReconcileOutcome::StillIndeterminate,
        ] {
            let fixture = make_fixture().await;
            let writer = &fixture.writer;
            let (request, claim) = prepare_dispatch(writer, "ack-first").await;
            let gate = Arc::new(Gate::default());
            let observer = Observer {
                outcome: observation,
                gate: Some(Arc::clone(&gate)),
            };
            let ack = async {
                gate.entered.notified().await;
                let receipt = writer
                    .settle_dispatch_outcome(request.clone(), "ack-first", claim, outcome.clone())
                    .await
                    .expect("normal target ACK");
                let counts = writer.lease.snapshot_counts().await.expect("ACK counts");
                gate.release.notify_one();
                (receipt, counts)
            };
            let (observed, (receipt, counts)) = timeout(Duration::from_secs(/*secs*/ 10), async {
                tokio::join!(writer.reconcile_target_batch(&observer, /*limit*/ 1), ack)
            })
            .await
            .expect("controlled ACK/observer race must finish");
            assert_eq!(observed.expect("superseded observation"), 1);
            assert_eq!(
                receipt,
                expected_dispatch(request, outcome.clone(), receipt.local_event_id.clone())
            );
            assert_eq!(
                writer.lease.snapshot_counts().await.expect("counts"),
                counts
            );
        }
    }
}

#[tokio::test]
async fn observer_before_ack_preserves_actual_target_transport_and_immutable_terminal_event() {
    for outcome in terminal_cases() {
        let fixture = make_fixture().await;
        let writer = &fixture.writer;
        let (request, claim) = prepare_dispatch(writer, "observer-first").await;
        let state = if matches!(outcome, ProductionTargetOutcome::Committed { .. }) {
            LocalReconcileOutcome::Committed
        } else {
            LocalReconcileOutcome::Rejected
        };
        let observer = Observer {
            outcome: state,
            gate: None,
        };
        assert_eq!(
            writer
                .reconcile_target_batch(&observer, /*limit*/ 1)
                .await
                .expect("observer"),
            1
        );
        let terminal = writer
            .reconcile("observer-first", state)
            .await
            .expect("same terminal replay");
        assert!(terminal.event_id.starts_with("observed-event:"));
        let counts = writer
            .lease
            .snapshot_counts()
            .await
            .expect("observer counts");
        let receipt = writer
            .settle_dispatch_outcome(request.clone(), "observer-first", claim, outcome.clone())
            .await
            .expect("same-result physical ACK");
        assert_eq!(
            receipt,
            expected_dispatch(request, outcome, terminal.event_id)
        );
        assert_eq!(
            writer.lease.snapshot_counts().await.expect("counts"),
            counts
        );
    }
}

#[tokio::test]
async fn opposite_terminal_observations_and_acks_remain_errors_in_both_orders() {
    for outcome in terminal_cases() {
        let opposite = if matches!(outcome, ProductionTargetOutcome::Committed { .. }) {
            LocalReconcileOutcome::Rejected
        } else {
            LocalReconcileOutcome::Committed
        };
        let fixture = make_fixture().await;
        let writer = &fixture.writer;
        let (request, claim) = prepare_dispatch(writer, "opposite-ack-first").await;
        writer
            .settle_dispatch_outcome(request, "opposite-ack-first", claim, outcome.clone())
            .await
            .expect("normal ACK");
        let counts = writer.lease.snapshot_counts().await.expect("counts");
        assert!(matches!(
            writer.reconcile("opposite-ack-first", opposite).await,
            Err(ProductionWriterError::Local(
                LocalLeaseOutboxError::IllegalTransition(_)
            ))
        ));
        assert_eq!(
            writer.lease.snapshot_counts().await.expect("counts"),
            counts
        );

        let (request, claim) = prepare_dispatch(writer, "opposite-observer-first").await;
        writer
            .reconcile("opposite-observer-first", opposite)
            .await
            .expect("observer terminal");
        let counts = writer.lease.snapshot_counts().await.expect("counts");
        assert!(matches!(
            writer
                .settle_dispatch_outcome(request, "opposite-observer-first", claim, outcome)
                .await,
            Err(ProductionWriterError::Local(
                LocalLeaseOutboxError::IllegalTransition(_)
            ))
        ));
        assert_eq!(
            writer.lease.snapshot_counts().await.expect("counts"),
            counts
        );
    }
}

#[tokio::test]
async fn same_terminal_races_do_not_relax_authority_fences_or_generic_receipt_replay() {
    let fixture = make_fixture().await;
    let writer = &fixture.writer;
    let (request, claim) = prepare_dispatch(writer, "terminal-guards").await;
    writer
        .reconcile("terminal-guards", LocalReconcileOutcome::Committed)
        .await
        .expect("observer terminal");
    let counts = writer.lease.snapshot_counts().await.expect("counts");
    assert!(matches!(
        writer
            .apply("terminal-guards", "unrelated semantic receipt")
            .await,
        Err(ProductionWriterError::Local(
            LocalLeaseOutboxError::IllegalTransition(_)
        ))
    ));
    fixture.revoked.store(/*val*/ true, Ordering::SeqCst);
    assert!(matches!(
        writer
            .settle_dispatch_outcome(
                request.clone(),
                "terminal-guards",
                claim.clone(),
                terminal_cases()[0].clone()
            )
            .await,
        Err(ProductionWriterError::AuthorityRejected(_))
    ));
    assert!(matches!(
        writer
            .reconcile("terminal-guards", LocalReconcileOutcome::Committed)
            .await,
        Err(ProductionWriterError::AuthorityRejected(_))
    ));
    fixture.revoked.store(/*val*/ false, Ordering::SeqCst);
    writer.release().await.expect("close settled lease");
    let closed_counts = writer.lease.snapshot_counts().await.expect("closed counts");
    assert!(matches!(
        writer
            .settle_dispatch_outcome(
                request,
                "terminal-guards",
                claim,
                terminal_cases()[0].clone()
            )
            .await,
        Err(ProductionWriterError::Local(
            LocalLeaseOutboxError::StaleFence(_)
        ))
    ));
    assert!(matches!(
        writer
            .reconcile("terminal-guards", LocalReconcileOutcome::Committed)
            .await,
        Err(ProductionWriterError::Local(
            LocalLeaseOutboxError::StaleFence(_)
        ))
    ));
    assert_eq!(
        writer.lease.snapshot_counts().await.expect("closed counts"),
        closed_counts
    );
    assert_eq!(closed_counts.event_rows, counts.event_rows);

    let fixture = make_fixture().await;
    let writer = &fixture.writer;
    let (request, claim) = prepare_dispatch(writer, "actual-ack-replay").await;
    let outcome = terminal_cases()[0].clone();
    writer
        .settle_dispatch_outcome(request.clone(), "actual-ack-replay", claim.clone(), outcome)
        .await
        .expect("ACK");
    let counts = writer.lease.snapshot_counts().await.expect("counts");
    assert!(matches!(
        writer
            .settle_dispatch_outcome(
                request,
                "actual-ack-replay",
                claim,
                ProductionTargetOutcome::Committed {
                    receipt: "different physical target receipt".to_string()
                }
            )
            .await,
        Err(ProductionWriterError::Local(
            LocalLeaseOutboxError::IllegalTransition(_)
        ))
    ));
    assert_eq!(
        writer.lease.snapshot_counts().await.expect("counts"),
        counts
    );
}

#[tokio::test]
async fn generic_literal_receipts_cannot_impersonate_observers_for_different_actual_acks() {
    for outcome in terminal_cases() {
        let fixture = make_fixture().await;
        let writer = &fixture.writer;
        let (request, claim) = prepare_dispatch(writer, "literal-receipt-origin").await;
        let generic = match &outcome {
            ProductionTargetOutcome::Committed { .. } => writer
                .apply("literal-receipt-origin", "committed")
                .await
                .expect("allowed generic receipt literal"),
            ProductionTargetOutcome::NotApplied { .. }
            | ProductionTargetOutcome::Rejected { .. } => writer
                .reject("literal-receipt-origin", "rejected")
                .await
                .expect("allowed generic reason literal"),
            ProductionTargetOutcome::Indeterminate { .. } => panic!("terminal fixture"),
        };
        assert!(generic.event_id.starts_with("event:"));
        let replay = match &outcome {
            ProductionTargetOutcome::Committed { .. } => writer
                .apply("literal-receipt-origin", "committed")
                .await
                .expect("exact generic receipt replay"),
            ProductionTargetOutcome::NotApplied { .. }
            | ProductionTargetOutcome::Rejected { .. } => writer
                .reject("literal-receipt-origin", "rejected")
                .await
                .expect("exact generic reason replay"),
            ProductionTargetOutcome::Indeterminate { .. } => panic!("terminal fixture"),
        };
        assert_eq!(replay, generic);
        let counts = writer.lease.snapshot_counts().await.expect("counts");
        assert!(matches!(
            writer
                .settle_dispatch_outcome(request, "literal-receipt-origin", claim, outcome)
                .await,
            Err(ProductionWriterError::Local(
                LocalLeaseOutboxError::IllegalTransition(_)
            ))
        ));
        assert_eq!(
            writer.lease.snapshot_counts().await.expect("counts"),
            counts
        );
    }
}

#[tokio::test]
async fn legacy_terminal_history_and_new_observer_origin_survive_store_and_writer_reopen() {
    let Fixture {
        _temp: temp,
        writer,
        revoked: _revoked,
    } = make_fixture().await;
    let owner = writer.owner_agent_id().clone();
    let authority = writer.authority.clone();
    let verifier = Arc::clone(writer.live_verifier.as_ref().expect("retained verifier"));
    let (legacy_request, legacy_claim) = prepare_dispatch(&writer, "legacy-terminal").await;
    // This is exactly the legacy observer encoding: canonical terminal text
    // in an ordinary event ID. Origin cannot be inferred from those bytes.
    let legacy = writer
        .apply("legacy-terminal", "committed")
        .await
        .expect("legacy terminal encoding");
    let (observed_request, observed_claim) = prepare_dispatch(&writer, "observed-terminal").await;
    let observed = writer
        .reconcile("observed-terminal", LocalReconcileOutcome::Committed)
        .await
        .expect("new observer terminal");
    assert!(legacy.event_id.starts_with("event:"));
    assert!(observed.event_id.starts_with("observed-event:"));
    let counts = writer.lease.snapshot_counts().await.expect("counts");
    drop(writer);

    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("full owner verification accepts legacy and observer event origins");
    let reopened = ProductionDurableWriter::open_with_live_verifier(
        store,
        authority,
        verifier,
        "reconciliation:race",
        /*generation*/ 1,
    )
    .await
    .expect("writer reopen");
    assert_eq!(
        reopened
            .status("legacy-terminal")
            .await
            .expect("legacy status"),
        LocalOutcomeState::Committed
    );
    assert_eq!(
        reopened
            .status("observed-terminal")
            .await
            .expect("observer status"),
        LocalOutcomeState::Committed
    );
    let exact_legacy_ack = reopened
        .settle_dispatch_outcome(
            legacy_request.clone(),
            "legacy-terminal",
            legacy_claim.clone(),
            ProductionTargetOutcome::Committed {
                receipt: "committed".to_string(),
            },
        )
        .await
        .expect("legacy exact-payload ACK remains valid");
    assert_eq!(exact_legacy_ack.local_event_id, legacy.event_id);
    assert!(matches!(
        reopened
            .settle_dispatch_outcome(
                legacy_request,
                "legacy-terminal",
                legacy_claim,
                terminal_cases()[0].clone()
            )
            .await,
        Err(ProductionWriterError::Local(
            LocalLeaseOutboxError::IllegalTransition(_)
        ))
    ));
    let outcome = terminal_cases()[0].clone();
    let receipt = reopened
        .settle_dispatch_outcome(
            observed_request.clone(),
            "observed-terminal",
            observed_claim,
            outcome.clone(),
        )
        .await
        .expect("new observer provenance remains usable after reopen");
    assert_eq!(
        receipt,
        expected_dispatch(observed_request, outcome, observed.event_id)
    );
    assert_eq!(
        reopened.lease.snapshot_counts().await.expect("counts"),
        counts
    );
}
