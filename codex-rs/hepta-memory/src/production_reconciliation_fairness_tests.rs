//! Real dispatcher regressions. Synthetic targets do not certify provider behavior.

use super::*;

async fn prepare_operations(
    writer: &ProductionDurableWriter,
    dispatcher: &ProductionFinalUseOutboxDispatcher,
    issuer: &SigningKey,
    owner: &AgentId,
    operation_ids: &[&str],
) {
    for &operation_id in operation_ids {
        let (draft, payload) = source_payload(operation_id, operation_id.as_bytes());
        let queued = writer
            .prepare_operation(
                OperationIntentV1::new(
                    StableId::new(operation_id).expect("operation id"),
                    StableId::new(owner.as_str()).expect("subject"),
                    StableId::new(dispatcher.destination_id()).expect("destination"),
                    Digest32::of_bytes(payload.as_bytes()),
                    scope_digest(&draft),
                    Generation::new(1).expect("policy generation"),
                    None,
                )
                .expect("operation intent"),
                COGNITIVE_SOURCE_TOPIC_V1,
                &payload,
            )
            .await
            .expect("prepare");
        let binding = writer
            .final_use_binding(&queued, dispatcher.destination_id())
            .await
            .expect("binding");
        let signed = signed_final_use(issuer, binding.clone(), operation_id);
        let result = dispatcher
            .dispatch(writer, &signed, &binding, queued)
            .await
            .expect("dispatch");
        assert_eq!(result.state, LocalOutcomeState::Indeterminate);
    }
}

#[derive(Debug, Default)]
enum PersistentObservation {
    #[default]
    Unavailable,
    Indeterminate,
}

#[derive(Debug, Default)]
struct PausedObserverTarget {
    destination: Option<&'static str>,
    pause_first: bool,
    observation: PersistentObservation,
    observed: std::sync::Mutex<Vec<String>>,
    entered: tokio::sync::Notify,
    dispatches: std::sync::atomic::AtomicUsize,
}

impl ProductionOutboxTarget for PausedObserverTarget {
    fn dispatch<'a>(&'a self, _request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        self.dispatches
            .fetch_add(/*val*/ 1, std::sync::atomic::Ordering::SeqCst);
        Box::pin(async {
            ProductionTargetOutcome::Indeterminate {
                reason: "synthetic dispatch with unknown outcome".to_string(),
            }
        })
    }
}

impl crate::FinalUseProductionOutboxTarget for PausedObserverTarget {
    fn destination_id(&self) -> &str {
        self.destination.unwrap_or(COGNITIVE_SOURCE_DESTINATION_V1)
    }

    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        Box::pin(async move {
            let first = {
                let mut observed = self.observed.lock().expect("observer log");
                observed.push(request.occurrence_key.clone());
                observed.len() == 1
            };
            if first && self.pause_first {
                self.entered.notify_one();
                std::future::pending::<()>().await;
            }
            match self.observation {
                PersistentObservation::Unavailable => ProductionTerminalObservation::Unavailable {
                    reason: "synthetic observer unavailable".to_string(),
                },
                PersistentObservation::Indeterminate => {
                    ProductionTerminalObservation::Indeterminate {
                        reason: "synthetic observer still indeterminate".to_string(),
                    }
                }
            }
        })
    }
}

#[tokio::test]
async fn cloned_dispatcher_reserves_beyond_paused_observer_and_cancelled_page_wraps() {
    let temp = TempDir::new().expect("temp");
    let store = store(&temp).await;
    let owner = store.owner_agent_id().clone();
    let writer = Arc::new(
        ProductionDurableWriter::open(
            store,
            production_authority(owner.clone()),
            &AllowVerifier,
            "production:h4:fairness-cancel",
            /*generation*/ 1,
        )
        .await
        .expect("writer"),
    );
    let target = Arc::new(PausedObserverTarget {
        pause_first: true,
        ..Default::default()
    });
    let issuer = SigningKey::from_bytes(&[91; 32]);
    let dispatcher =
        ProductionFinalUseOutboxDispatcher::attach(final_use(&temp, &issuer), target.clone());
    prepare_operations(
        &writer,
        &dispatcher,
        &issuer,
        &owner,
        &[
            "operation:fairness-a",
            "operation:fairness-b",
            "operation:fairness-c",
        ],
    )
    .await;
    let first_dispatcher = dispatcher.clone();
    let first_writer = Arc::clone(&writer);
    let first = tokio::spawn(async move {
        first_dispatcher.reconcile(&first_writer, /*limit*/ 2).await
    });
    tokio::time::timeout(
        std::time::Duration::from_secs(/*secs*/ 5),
        target.entered.notified(),
    )
    .await
    .expect("observer entered after reservation");
    let second = tokio::time::timeout(
        std::time::Duration::from_secs(/*secs*/ 5),
        dispatcher.reconcile(&writer, /*limit*/ 2),
    )
    .await
    .expect("observer does not hold discovery lock")
    .expect("second page");
    assert_eq!(second, 0);
    let seen = target.observed.lock().expect("observer log").clone();
    assert_eq!(seen.len(), 3);
    assert_eq!(
        seen.iter().collect::<BTreeSet<_>>().len(),
        3,
        "concurrent reservations must reach all three identities"
    );
    assert_ne!(
        seen[0], seen[1],
        "concurrent reservations advance within the cycle"
    );
    first.abort();
    assert!(first.await.expect_err("cancelled waiter").is_cancelled());
    assert_eq!(
        dispatcher
            .reconcile(&writer, /*limit*/ 1)
            .await
            .expect("wrap"),
        0
    );
    let final_seen = target.observed.lock().expect("observer log").clone();
    assert_eq!(
        final_seen,
        vec![
            seen[0].clone(),
            seen[1].clone(),
            seen[2].clone(),
            seen[0].clone()
        ]
    );
    assert_eq!(
        target.dispatches.load(std::sync::atomic::Ordering::SeqCst),
        3
    );
    for operation_id in seen {
        assert_eq!(
            writer.status(&operation_id).await.expect("status"),
            LocalOutcomeState::Indeterminate
        );
    }
}

#[tokio::test]
async fn cursor_does_not_retain_writer_lock_and_resets_on_reopened_owner() {
    let temp = TempDir::new().expect("temp");
    let store = store(&temp).await;
    let owner = store.owner_agent_id().clone();
    let authority = production_authority(owner.clone());
    let lease_id = "production:h4:fairness-reopen";
    let writer = ProductionDurableWriter::open(
        store.clone(),
        authority.clone(),
        &AllowVerifier,
        lease_id,
        /*generation*/ 1,
    )
    .await
    .expect("writer");
    let target = Arc::new(UnavailablePrefixTarget::default());
    let issuer = SigningKey::from_bytes(&[91; 32]);
    let dispatcher =
        ProductionFinalUseOutboxDispatcher::attach(final_use(&temp, &issuer), target.clone());
    prepare_operations(
        &writer,
        &dispatcher,
        &issuer,
        &owner,
        &["operation:fairness-a", "operation:fairness-b"],
    )
    .await;
    assert_eq!(
        dispatcher
            .reconcile(&writer, /*limit*/ 1)
            .await
            .expect("first page"),
        0
    );
    drop(writer);
    // The dispatcher and its reserved cursor survive. Reopening must not be
    // blocked by an accidental strong reference to the old writer fence.
    let reopened = ProductionDurableWriter::open(
        store,
        authority,
        &AllowVerifier,
        lease_id,
        /*generation*/ 1,
    )
    .await
    .expect("writer lock released despite retained dispatcher");
    assert_eq!(
        dispatcher
            .reconcile(&reopened, /*limit*/ 1)
            .await
            .expect("fresh owner page"),
        0
    );
    let seen = target.observed.lock().expect("observer log").clone();
    assert_eq!(seen.len(), 2);
    assert_eq!(
        seen[0], seen[1],
        "new owner incarnation starts a new scan cycle"
    );
}

#[tokio::test]
async fn limit_two_binding_error_propagates_without_permanently_hiding_later_items() {
    let temp = TempDir::new().expect("temp");
    let store = store(&temp).await;
    let owner = store.owner_agent_id().clone();
    let writer = ProductionDurableWriter::open(
        store.clone(),
        production_authority(owner.clone()),
        &AllowVerifier,
        "production:h4:fairness-error",
        /*generation*/ 1,
    )
    .await
    .expect("writer");
    let target = Arc::new(PausedObserverTarget::default());
    let issuer = SigningKey::from_bytes(&[91; 32]);
    let dispatcher =
        ProductionFinalUseOutboxDispatcher::attach(final_use(&temp, &issuer), target.clone());
    prepare_operations(
        &writer,
        &dispatcher,
        &issuer,
        &owner,
        &[
            "operation:fairness-a",
            "operation:fairness-b",
            "operation:fairness-c",
        ],
    )
    .await;
    let ordered = sqlx::query_scalar::<_, String>(
        "SELECT operation_id FROM cognitive_operation_ledger WHERE lease_id = ?
         ORDER BY prepared_at_unix_seconds, operation_id",
    )
    .bind(writer.lease_id())
    .fetch_all(&store.pool)
    .await
    .expect("actual stable ordering");
    assert_eq!(ordered.len(), 3);
    // Controlled corruption of one fixture row. Keep the production binding
    // check and its error intact; the scheduler must never legitimize this row.
    sqlx::query("DROP TRIGGER cognitive_local_outbox_no_update")
        .execute(&store.pool)
        .await
        .expect("fixture tamper seam");
    sqlx::query("UPDATE cognitive_local_outbox SET payload_json = 'tampered' WHERE lease_id = ? AND occurrence_key = ?")
        .bind(writer.lease_id()).bind(&ordered[0]).execute(&store.pool).await.expect("tamper only first row");
    dispatcher
        .reconcile(&writer, /*limit*/ 2)
        .await
        .expect_err("binding corruption must propagate");
    assert!(target.observed.lock().expect("log").is_empty());
    assert_eq!(
        dispatcher
            .reconcile(&writer, /*limit*/ 2)
            .await
            .expect("later valid rows remain observable"),
        0
    );
    assert_eq!(*target.observed.lock().expect("log"), ordered[1..].to_vec());
    dispatcher
        .reconcile(&writer, /*limit*/ 2)
        .await
        .expect_err("wrap must still reject corrupt first row");
    assert_eq!(
        target.dispatches.load(std::sync::atomic::Ordering::SeqCst),
        3
    );
}

#[tokio::test]
async fn still_indeterminate_cycle_is_fair_and_short_cycle_never_repeats_within_one_call() {
    let temp = TempDir::new().expect("temp");
    let store = store(&temp).await;
    let owner = store.owner_agent_id().clone();
    let writer = ProductionDurableWriter::open(
        store,
        production_authority(owner.clone()),
        &AllowVerifier,
        "production:h4:fairness-indeterminate",
        /*generation*/ 1,
    )
    .await
    .expect("writer");
    let target = Arc::new(PausedObserverTarget {
        observation: PersistentObservation::Indeterminate,
        ..Default::default()
    });
    let issuer = SigningKey::from_bytes(&[91; 32]);
    let dispatcher =
        ProductionFinalUseOutboxDispatcher::attach(final_use(&temp, &issuer), target.clone());
    prepare_operations(
        &writer,
        &dispatcher,
        &issuer,
        &owner,
        &["operation:fairness-a", "operation:fairness-b"],
    )
    .await;
    for _ in 0..2 {
        assert_eq!(
            dispatcher
                .reconcile(&writer, /*limit*/ 1)
                .await
                .expect("one-item pass"),
            1
        );
    }
    {
        let mut seen = target.observed.lock().expect("log");
        assert_eq!(seen.len(), 2);
        assert_ne!(seen[0], seen[1], "still-indeterminate prefix must rotate");
        seen.clear();
    }
    assert_eq!(
        dispatcher
            .reconcile(&writer, /*limit*/ 256)
            .await
            .expect("bounded cycle"),
        2
    );
    let seen = target.observed.lock().expect("log").clone();
    assert_eq!(seen.len(), 2);
    assert_ne!(seen[0], seen[1]);
    assert_eq!(
        dispatcher
            .reconcile(&writer, /*limit*/ 1)
            .await
            .expect("later pass"),
        1
    );
    assert_eq!(
        target.dispatches.load(std::sync::atomic::Ordering::SeqCst),
        2
    );
    for id in seen {
        assert_eq!(
            writer.status(&id).await.expect("still pending"),
            LocalOutcomeState::Indeterminate
        );
    }
}

#[path = "production_reconciliation_edge_tests.rs"]
mod edge_tests;
