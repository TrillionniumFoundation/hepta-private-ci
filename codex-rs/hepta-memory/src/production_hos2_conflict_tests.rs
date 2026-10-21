//! Original SQLite conflict quarantine and the final source authority check.

use super::*;
use std::sync::Mutex;
use std::sync::mpsc;
use tokio::sync::Notify;
use tokio::sync::oneshot;

struct HeldConflictTarget {
    inner: Arc<ProductionHos2Target>,
    returned: Notify,
    release: Notify,
}

impl ProductionOutboxTarget for HeldConflictTarget {
    fn dispatch<'a>(&'a self, request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        // The device call still happens synchronously in the real consumer
        // closure. Only handing its completed observation to SQLite is held.
        let completed = self.inner.dispatch(request);
        self.returned.notify_one();
        Box::pin(async move {
            self.release.notified().await;
            completed.await
        })
    }
}

impl FinalUseProductionOutboxTarget for HeldConflictTarget {
    fn destination_id(&self) -> &str { HOS2_DESTINATION_V1 }

    fn observe_terminal<'a>(&'a self, request: &'a ProductionDispatchRequest) -> ProductionTerminalObservationFuture<'a> {
        self.inner.observe_terminal(request)
    }
}

#[tokio::test]
async fn observed_conflict_uses_original_rollback_after_still_indeterminate_and_blocks_later_query() -> TestResult {
    let directory = tempfile::tempdir()?;
    let fixture = Fixture::open(directory.path()).await?;
    let queued = fixture.prepare(OPERATION, /*sequence*/ 1).await?;
    let request = fixture.request(/*sequence*/ 1)?;
    let mut older = request.clone();
    older.cap_ns = 999;
    let old_observation = Hos2DeliveryObservation::Applied {
        stable_object_id: [9; 16], previous_revision: 1, revision: 2,
        effective_ns: HOS2_CPU_PERIOD_NS + 1_001, consumed_ns: 999,
    };
    // Deliberately violate the exclusive-namespace precondition to reproduce
    // a real Conflict followed by the older D's still-visible Applied result.
    let record = DeviceRecord { request: older, observation: old_observation };
    let mut file = OpenOptions::new().write(true).create_new(true).open(fixture.device.effect_path(1))?;
    file.write_all(&serde_json::to_vec(&record)?)?;
    file.sync_all()?;
    drop(file);
    let target = Arc::new(HeldConflictTarget {
        inner: fixture.target.clone(), returned: Notify::new(), release: Notify::new(),
    });
    let dispatcher = ProductionFinalUseOutboxDispatcher::attach(fixture.authority.clone(), target.clone());
    let (binding, signed) = fixture.signed(&queued, /*nonce*/ 40).await?;
    let writer = fixture.writer.clone();
    let task = tokio::spawn(async move { dispatcher.dispatch(&writer, &signed, &binding, queued).await });
    tokio::time::timeout(Duration::from_secs(5), target.returned.notified()).await?;
    // Exercise the actual public observer while dispatch already holds a
    // contradictory native result but has not appended its source event.
    // Without the original owner's use gate this call commits the older D.
    assert_eq!(fixture.dispatcher.reconcile(&fixture.writer, /*limit*/ 8).await?, 0);
    assert_eq!(fixture.device.queries.load(Ordering::SeqCst), 0);
    assert_eq!(fixture.writer.status(OPERATION).await?, LocalOutcomeState::Indeterminate);
    let dispatch_request = fixture.writer.reconciliation_request(OPERATION, HOS2_DESTINATION_V1).await?;
    let stale = match fixture.target.observe_terminal(&dispatch_request).await {
        ProductionTerminalObservation::Applied { receipt } => receipt,
        other => return Err(format!("expected the older native receipt: {other:?}").into()),
    };
    fixture.writer.reconcile(OPERATION, LocalReconcileOutcome::StillIndeterminate).await?;
    target.release.notify_one();
    let outcome = tokio::time::timeout(Duration::from_secs(5), task).await???;
    assert_eq!((outcome.state, outcome.target_disposition, outcome.target_receipt, outcome.external_effect),
        (LocalOutcomeState::RolledBack, ProductionTargetDisposition::Indeterminate, None, false));
    let events: Vec<(String, String)> = sqlx::query_as(
        "SELECT event_kind, payload_json FROM cognitive_local_events WHERE lease_id = ? AND occurrence_key = ? ORDER BY event_sequence",
    ).bind(LEASE).bind(OPERATION).fetch_all(&fixture.writer.store.pool).await?;
    assert_eq!(events.iter().map(|event| event.0.as_str()).collect::<Vec<_>>(),
        vec!["admitted", "indeterminate", "reconcile_still_indeterminate", "rolled_back"]);
    let conflict_json: serde_json::Value = serde_json::from_str(&events.last().ok_or("missing conflict event")?.1)?;
    assert_eq!(conflict_json, serde_json::json!({
        "schema_version": 1, "operation_id": OPERATION, "request": request,
        "contradiction": { "kind": "conflict_status" },
    }));
    assert_eq!(outcome.target_reason, Some(events.last().ok_or("missing conflict event")?.1.clone()));
    assert!(fixture.writer.settle_hos2_terminal(&dispatch_request, &stale, LocalReconcileOutcome::Committed).await.is_err());
    assert_eq!(fixture.dispatcher.reconcile(&fixture.writer, /*limit*/ 8).await?, 0);
    assert_eq!((fixture.device.calls.load(Ordering::SeqCst), fixture.device.queries.load(Ordering::SeqCst)), (1, 1));
    assert!(fixture.writer.awaiting_authorization(HOS2_DESTINATION_V1, /*limit*/ 8).await?.is_empty());
    assert!(fixture.prepare("hos2:after-conflict", /*sequence*/ 2).await.is_err());
    assert!(fixture.writer.retire_hos2_through(&fixture.target, &request.delivery).await.is_err());
    let cut = fixture.writer.recovery_anchor().await?;
    drop(fixture);
    let reopened = Fixture::open(directory.path()).await?;
    assert_eq!(reopened.writer.recovery_anchor().await?, cut);
    assert_eq!(reopened.writer.status(OPERATION).await?, LocalOutcomeState::RolledBack);
    assert_eq!(reopened.dispatcher.reconcile(&reopened.writer, /*limit*/ 8).await?, 0);
    assert_eq!((reopened.device.calls.load(Ordering::SeqCst), reopened.device.queries.load(Ordering::SeqCst)), (0, 0));
    assert!(reopened.prepare("hos2:after-reopen-conflict", /*sequence*/ 2).await.is_err());
    assert!(reopened.writer.retire_hos2_through(&reopened.target, &request.delivery).await.is_err());
    Ok(())
}

type HeldDispatch = tokio::task::JoinHandle<Result<ProductionDispatchReceipt, ProductionWriterError>>;

async fn hold_native_conflict(fixture: &Fixture, nonce: u8) -> TestResult<(Arc<HeldConflictTarget>, HeldDispatch)> {
    let queued = fixture.prepare(OPERATION, /*sequence*/ 1).await?;
    let mut older = fixture.request(/*sequence*/ 1)?;
    older.cap_ns = 999;
    let record = DeviceRecord {
        request: older,
        observation: Hos2DeliveryObservation::Applied {
            stable_object_id: [9; 16], previous_revision: 1, revision: 2,
            effective_ns: HOS2_CPU_PERIOD_NS + 1_001, consumed_ns: 999,
        },
    };
    let mut file = OpenOptions::new().write(true).create_new(true).open(fixture.device.effect_path(1))?;
    file.write_all(&serde_json::to_vec(&record)?)?;
    file.sync_all()?;
    drop(file);
    let target = Arc::new(HeldConflictTarget {
        inner: fixture.target.clone(), returned: Notify::new(), release: Notify::new(),
    });
    let dispatcher = ProductionFinalUseOutboxDispatcher::attach(fixture.authority.clone(), target.clone());
    let (binding, signed) = fixture.signed(&queued, nonce).await?;
    // Clone the writer value, not just the outer Arc: the existing retained
    // OS owner lock must also share its live native-use gate across clones.
    let writer = fixture.writer.as_ref().clone();
    let task = tokio::spawn(async move { dispatcher.dispatch(&writer, &signed, &binding, queued).await });
    tokio::time::timeout(Duration::from_secs(5), target.returned.notified()).await?;
    Ok((target, task))
}

#[tokio::test]
async fn aborted_native_use_stops_the_live_original_owner_before_observation() -> TestResult {
    let directory = tempfile::tempdir()?;
    let fixture = Fixture::open(directory.path()).await?;
    let (_target, task) = hold_native_conflict(&fixture, /*nonce*/ 43).await?;
    task.abort();
    let joined = tokio::time::timeout(Duration::from_secs(5), task).await?;
    assert!(matches!(joined, Err(error) if error.is_cancelled()));
    let observer = fixture.writer.as_ref().clone();
    let error = fixture.dispatcher.reconcile(&observer, /*limit*/ 8).await
        .err().ok_or("interrupted owner unexpectedly allowed native observation")?;
    assert!(error.to_string().contains("interrupted use"));
    assert_eq!(fixture.writer.status(OPERATION).await?, LocalOutcomeState::Indeterminate);
    assert_eq!((fixture.device.calls.load(Ordering::SeqCst), fixture.device.queries.load(Ordering::SeqCst)), (1, 0));
    let kinds: Vec<String> = sqlx::query_scalar(
        "SELECT event_kind FROM cognitive_local_events WHERE lease_id = ? AND occurrence_key = ? ORDER BY event_sequence",
    ).bind(LEASE).bind(OPERATION).fetch_all(&fixture.writer.store.pool).await?;
    assert_eq!(kinds, vec!["admitted", "indeterminate"]);
    assert!(fixture.prepare("hos2:after-aborted-use", /*sequence*/ 2).await.is_err());
    Ok(())
}

#[tokio::test]
async fn failed_conflict_append_keeps_the_live_original_owner_stopped() -> TestResult {
    let directory = tempfile::tempdir()?;
    let fixture = Fixture::open(directory.path()).await?;
    let (target, task) = hold_native_conflict(&fixture, /*nonce*/ 44).await?;
    // Fail the real original SQLite append. This is a fixture-only trigger,
    // removed below before checking that a recovered database connection
    // does not clear the still-live owner's interruption latch.
    sqlx::query(
        "CREATE TRIGGER hos2_fixture_abort_conflict BEFORE INSERT ON cognitive_local_events
         WHEN NEW.event_kind = 'rolled_back'
         BEGIN SELECT RAISE(ABORT, 'hos2 fixture conflict append failed'); END",
    ).execute(&fixture.writer.store.pool).await?;
    target.release.notify_one();
    let result = tokio::time::timeout(Duration::from_secs(5), task).await??;
    let error = result.err().ok_or("fixture unexpectedly persisted the native contradiction")?;
    assert!(error.to_string().contains("hos2 fixture conflict append failed"));
    sqlx::query("DROP TRIGGER hos2_fixture_abort_conflict").execute(&fixture.writer.store.pool).await?;
    let observer = fixture.writer.as_ref().clone();
    let error = fixture.dispatcher.reconcile(&observer, /*limit*/ 8).await
        .err().ok_or("failed contradiction append unexpectedly allowed native observation")?;
    assert!(error.to_string().contains("interrupted use"));
    assert_eq!(fixture.writer.status(OPERATION).await?, LocalOutcomeState::Indeterminate);
    assert_eq!((fixture.device.calls.load(Ordering::SeqCst), fixture.device.queries.load(Ordering::SeqCst)), (1, 0));
    let kinds: Vec<String> = sqlx::query_scalar(
        "SELECT event_kind FROM cognitive_local_events WHERE lease_id = ? AND occurrence_key = ? ORDER BY event_sequence",
    ).bind(LEASE).bind(OPERATION).fetch_all(&fixture.writer.store.pool).await?;
    assert_eq!(kinds, vec!["admitted", "indeterminate"]);
    assert!(fixture.prepare("hos2:after-failed-conflict-append", /*sequence*/ 2).await.is_err());
    Ok(())
}

struct RetirementVerifier {
    revoked: AtomicBool,
    checks: AtomicUsize,
    checked: Mutex<Option<oneshot::Sender<()>>>,
    resume: Mutex<mpsc::Receiver<()>>,
}

#[tokio::test]
async fn known_request_rejection_disables_original_intent_at_dispatch_and_recovery() -> TestResult {
    enum Entry { Dispatch, Recovery }
    for entry in [Entry::Dispatch, Entry::Recovery] {
        let directory = tempfile::tempdir()?;
        let fixture = Fixture::open(directory.path()).await?;
        let mut request = fixture.request(/*sequence*/ 1)?;
        request.cap_ns = 75_000_000;
        let queued = fixture.writer.prepare_operation(
            fixture.operation(OPERATION, &request)?, HOS2_INSTALL_TOPIC_V1, request.to_json()?,
        ).await?;
        let mut older = request.clone();
        older.cap_ns = 20_000_000;
        let record = DeviceRecord {
            request: older,
            observation: Hos2DeliveryObservation::Applied {
                stable_object_id: [9; 16], previous_revision: 1, revision: 2,
                effective_ns: HOS2_CPU_PERIOD_NS + 1_001, consumed_ns: 999,
            },
        };
        let before = serde_json::to_vec(&record)?;
        let effect_path = fixture.device.effect_path(1);
        let mut file = OpenOptions::new().write(true).create_new(true).open(&effect_path)?;
        file.write_all(&before)?;
        file.sync_all()?;
        drop(file);
        match entry {
            Entry::Dispatch => {
                let (binding, signed) = fixture.signed(&queued, /*nonce*/ 42).await?;
                let outcome = fixture.dispatcher.dispatch(&fixture.writer, &signed, &binding, queued).await?;
                assert_eq!((outcome.state, outcome.target_disposition),
                    (LocalOutcomeState::RolledBack, ProductionTargetDisposition::Indeterminate));
            }
            Entry::Recovery => {
                fixture.writer.mark_indeterminate(OPERATION, "lost response before source recovery").await?;
                assert_eq!(fixture.dispatcher.reconcile(&fixture.writer, /*limit*/ 8).await?, 1);
            }
        }
        assert_eq!(fixture.writer.status(OPERATION).await?, LocalOutcomeState::RolledBack);
        assert_eq!(fixture.device.queries.load(Ordering::SeqCst), 0);
        assert_eq!(fs::read(&effect_path)?, before);
        assert_eq!(fixture.dispatcher.reconcile(&fixture.writer, /*limit*/ 8).await?, 0);
        assert!(fixture.prepare("hos2:after-local-refusal", /*sequence*/ 2).await.is_err());
        assert!(fixture.writer.retire_hos2_through(&fixture.target, &request.delivery).await.is_err());
        drop(fixture);
        let reopened = Fixture::open(directory.path()).await?;
        assert_eq!(reopened.writer.status(OPERATION).await?, LocalOutcomeState::RolledBack);
        assert_eq!(reopened.dispatcher.reconcile(&reopened.writer, /*limit*/ 8).await?, 0);
        assert_eq!((reopened.device.calls.load(Ordering::SeqCst), reopened.device.queries.load(Ordering::SeqCst)), (0, 0));
    }
    Ok(())
}

impl ProductionAuthorityVerifier for RetirementVerifier {
    fn verify(&self, _authority: &ProductionAuthorityLease, _owner: &AgentId) -> Result<(), String> {
        if self.revoked.load(Ordering::SeqCst) {
            return Err("original issuer revoked the source lease".to_string());
        }
        if self.checks.fetch_add(1, Ordering::SeqCst) == 1 {
            self.checked.lock().map_err(|error| error.to_string())?.take()
                .ok_or_else(|| "missing authority-check notification".to_string())?
                .send(()).map_err(|_| "authority-check observer closed".to_string())?;
            self.resume.lock().map_err(|error| error.to_string())?
                .recv_timeout(Duration::from_secs(5)).map_err(|error| error.to_string())?;
        }
        Ok(())
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn retirement_rechecks_original_live_authority_after_sqlite_awaits() -> TestResult {
    let directory = tempfile::tempdir()?;
    let mut fixture = Fixture::open(directory.path()).await?;
    let queued = fixture.prepare(OPERATION, /*sequence*/ 1).await?;
    let (binding, signed) = fixture.signed(&queued, /*nonce*/ 41).await?;
    fixture.dispatcher.dispatch(&fixture.writer, &signed, &binding, queued).await?;
    let (checked_tx, checked_rx) = oneshot::channel();
    let (resume_tx, resume_rx) = mpsc::sync_channel(1);
    let verifier = Arc::new(RetirementVerifier {
        revoked: AtomicBool::new(false), checks: AtomicUsize::new(0),
        checked: Mutex::new(Some(checked_tx)), resume: Mutex::new(resume_rx),
    });
    Arc::get_mut(&mut fixture.writer).ok_or("fixture writer unexpectedly shared")?.live_verifier = Some(verifier.clone());
    let through = fixture.request(/*sequence*/ 1)?.delivery;
    let writer = fixture.writer.clone();
    let target = fixture.target.clone();
    let mut retirement = tokio::spawn(async move { writer.retire_hos2_through(&target, &through).await });
    tokio::time::timeout(Duration::from_secs(5), checked_rx).await??;
    // Prefix verification has committed. Exhaust the actual owning pool while
    // the second live check is paused, so its following SQLite await cannot
    // finish before this test revokes the original authority.
    let mut held = Vec::new();
    for _ in 0..fixture.writer.store.pool.options().get_max_connections() {
        held.push(tokio::time::timeout(Duration::from_secs(5), fixture.writer.store.pool.acquire()).await??);
    }
    resume_tx.send(())?;
    assert!(tokio::time::timeout(Duration::from_millis(20), &mut retirement).await.is_err());
    verifier.revoked.store(true, Ordering::SeqCst);
    drop(held);
    let result = tokio::time::timeout(Duration::from_secs(5), retirement).await??;
    assert!(matches!(result, Err(ProductionWriterError::AuthorityRejected(_))));
    assert_eq!(fixture.device.retire_calls.load(Ordering::SeqCst), 0);
    Ok(())
}
