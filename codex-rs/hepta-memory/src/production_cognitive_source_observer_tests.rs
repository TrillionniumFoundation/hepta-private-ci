use super::*;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::sync::Notify;

/// Pause the real destination before its transaction; its observer is unchanged.
struct PausedRealTarget {
    inner: CognitiveSourceOutboxTarget,
    entered: Notify,
    release: Notify,
    calls: AtomicUsize,
}

impl ProductionOutboxTarget for PausedRealTarget {
    fn dispatch<'a>(&'a self, request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        Box::pin(async move {
            self.calls.fetch_add(/*val*/ 1, Ordering::SeqCst);
            self.entered.notify_one();
            self.release.notified().await;
            self.inner.dispatch(request).await
        })
    }
}

impl crate::FinalUseProductionOutboxTarget for PausedRealTarget {
    fn destination_id(&self) -> &str {
        self.inner.destination_id()
    }

    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        crate::FinalUseProductionOutboxTarget::observe_terminal(&self.inner, request)
    }
}

struct Fixture {
    _temp: TempDir,
    store: CognitiveStore,
    writer: ProductionDurableWriter,
    dispatcher: ProductionFinalUseOutboxDispatcher,
    target: Arc<PausedRealTarget>,
    binding: FinalUseBinding,
    signed: SignedFinalUseGrant,
    queued: crate::ProductionQueuedReceipt,
    request: ProductionDispatchRequest,
}

impl Fixture {
    async fn new() -> Self {
        let temp = TempDir::new().expect("temp");
        let store = store(&temp).await;
        let owner = store.owner_agent_id().clone();
        let writer = ProductionDurableWriter::open(
            store.clone(),
            production_authority(owner.clone()),
            &AllowVerifier,
            "production:h4:live-observer",
            /*generation*/ 1,
        )
        .await
        .expect("writer");
        let target = Arc::new(PausedRealTarget {
            inner: CognitiveSourceOutboxTarget::new(
                store.clone(),
                CognitiveAccess::agent_private(owner.clone()),
            )
            .expect("real target"),
            entered: Notify::new(),
            release: Notify::new(),
            calls: AtomicUsize::new(/*v*/ 0),
        });
        let issuer = SigningKey::from_bytes(&[92; 32]);
        let dispatcher =
            ProductionFinalUseOutboxDispatcher::attach(final_use(&temp, &issuer), target.clone());
        let operation_id = "operation:cognitive-live-observer";
        let (draft, payload) = source_payload(operation_id, b"real-delayed-commit");
        let intent = operation(
            &owner,
            operation_id,
            &payload,
            &draft,
            /*predecessor*/ None,
        );
        let request = direct_request(&intent, payload.clone());
        let queued = writer
            .prepare_operation(intent, COGNITIVE_SOURCE_TOPIC_V1, &payload)
            .await
            .expect("queued");
        let binding = writer
            .final_use_binding(&queued, COGNITIVE_SOURCE_DESTINATION_V1)
            .await
            .expect("binding");
        let signed = signed_final_use(&issuer, binding.clone(), "live-observer-grant");
        Self {
            _temp: temp,
            store,
            writer,
            dispatcher,
            target,
            binding,
            signed,
            queued,
            request,
        }
    }

    async fn start(
        &self,
    ) -> tokio::task::JoinHandle<
        Result<crate::ProductionDispatchReceipt, crate::ProductionWriterError>,
    > {
        let dispatcher = self.dispatcher.clone();
        let writer = self.writer.clone();
        let signed = self.signed.clone();
        let binding = self.binding.clone();
        let queued = self.queued.clone();
        let dispatch = tokio::spawn(async move {
            dispatcher
                .dispatch(&writer, &signed, &binding, queued)
                .await
        });
        tokio::time::timeout(
            Duration::from_secs(/*secs*/ 30),
            self.target.entered.notified(),
        )
        .await
        .expect("real target future entered");
        dispatch
    }

    async fn local_event_count(&self) -> i64 {
        sqlx::query_scalar(
            "SELECT COUNT(*) FROM cognitive_local_events WHERE lease_id = ? AND occurrence_key = ?",
        )
        .bind(self.writer.lease_id())
        .bind(&self.queued.occurrence_key)
        .fetch_one(&self.store.pool)
        .await
        .expect("local event count")
    }
}

#[tokio::test]
async fn live_destination_absence_cannot_reconcile_before_real_commit() {
    let fixture = Fixture::new().await;
    let dispatch = fixture.start().await;
    let reconciled = fixture
        .dispatcher
        .reconcile(&fixture.writer, /*limit*/ 8)
        .await
        .expect("observer-only reconcile");
    let live_status = fixture
        .writer
        .status(&fixture.queued.occurrence_key)
        .await
        .expect("live source status");
    fixture.target.release.notify_one();
    let dispatch_result = tokio::time::timeout(Duration::from_secs(/*secs*/ 30), dispatch)
        .await
        .expect("bounded dispatch completion")
        .expect("dispatch task");
    assert!(matches!(
        fixture
            .target
            .inner
            .observe_terminal(&fixture.request)
            .await,
        CognitiveSourceTerminalObservation::Applied { .. }
    ));
    assert_eq!(
        (reconciled, live_status),
        (0, LocalOutcomeState::Indeterminate),
        "a missing row during a live effect is not a terminal negative receipt"
    );
    assert_eq!(
        dispatch_result.expect("real commit is settled").state,
        LocalOutcomeState::Committed
    );
}

#[tokio::test]
async fn cancelled_destination_absence_stays_open_without_events_or_resend() {
    let fixture = Fixture::new().await;
    let dispatch = fixture.start().await;
    let initial_events = fixture.local_event_count().await;
    dispatch.abort();
    assert!(
        dispatch
            .await
            .expect_err("dispatch cancelled")
            .is_cancelled()
    );
    for _ in 0..2 {
        assert_eq!(
            fixture
                .dispatcher
                .reconcile(&fixture.writer, /*limit*/ 8)
                .await
                .expect("observer-only reconcile"),
            0
        );
    }
    assert_eq!(fixture.local_event_count().await, initial_events);
    assert_eq!(
        fixture
            .writer
            .status(&fixture.queued.occurrence_key)
            .await
            .expect("cancelled source status"),
        LocalOutcomeState::Indeterminate
    );
    assert!(matches!(
        fixture
            .dispatcher
            .dispatch(
                &fixture.writer,
                &fixture.signed,
                &fixture.binding,
                fixture.queued.clone(),
            )
            .await,
        Err(crate::ProductionWriterError::StaleReceipt)
    ));
    assert_eq!(fixture.target.calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn destination_observer_distinguishes_unknown_exact_conflict_and_read_failure() {
    let fixture = Fixture::new().await;
    assert_eq!(
        fixture
            .target
            .inner
            .observe_terminal(&fixture.request)
            .await,
        CognitiveSourceTerminalObservation::Unavailable {
            reason: "destination outcome is unknown: source absence is not terminal proof"
                .to_string(),
        }
    );
    let receipt = match fixture.target.inner.dispatch(fixture.request.clone()).await {
        ProductionTargetOutcome::Committed { receipt } => receipt,
        other => panic!("real target did not commit: {other:?}"),
    };
    assert_eq!(
        fixture
            .target
            .inner
            .observe_terminal(&fixture.request)
            .await,
        CognitiveSourceTerminalObservation::Applied { receipt }
    );

    let (draft, payload) = source_payload(&fixture.queued.occurrence_key, b"conflicting-content");
    let intent = operation(
        fixture.store.owner_agent_id(),
        &fixture.queued.occurrence_key,
        &payload,
        &draft,
        /*predecessor*/ None,
    );
    assert_eq!(
        fixture
            .target
            .inner
            .observe_terminal(&direct_request(&intent, payload))
            .await,
        CognitiveSourceTerminalObservation::Quarantined {
            reason: "destination source identity exists with different semantics".to_string(),
        }
    );

    fixture.store.pool.close().await;
    assert!(matches!(
        fixture.target.inner.observe_terminal(&fixture.request).await,
        CognitiveSourceTerminalObservation::Unavailable { reason } if reason.contains("closed")
    ));
}
