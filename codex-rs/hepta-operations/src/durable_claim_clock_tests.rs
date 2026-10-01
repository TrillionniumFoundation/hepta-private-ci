use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicI64;
use std::sync::atomic::Ordering;
use std::task::Poll;
use std::time::Duration;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::DispatchClaim;
use crate::DurableOperationClock;
use crate::DurableOperationError;
use crate::DurableOperationIntentV1;
use crate::DurableOperationRecord;
use crate::DurableOperationState;
use crate::DurableOperationStore;
use crate::DurableOutboxState;
use crate::MAX_DURABLE_OUTBOX_ATTEMPTS;
use crate::OutboxStatusV1;
use crate::RecoveryDisposition;

#[derive(Clone)]
struct ManualClock {
    now: Arc<AtomicI64>,
    samples: Arc<Mutex<Vec<i64>>>,
    after_next_sample: Arc<Mutex<Option<i64>>>,
}

impl ManualClock {
    fn new(now: i64) -> Self {
        Self {
            now: Arc::new(AtomicI64::new(now)),
            samples: Arc::new(Mutex::new(Vec::new())),
            after_next_sample: Arc::new(Mutex::new(None)),
        }
    }

    fn set(&self, now: i64) {
        self.now.store(now, Ordering::SeqCst);
    }

    fn set_after_next_sample(&self, now: i64) {
        *self.after_next_sample.lock().expect("clock transition") = Some(now);
    }

    fn clear_samples(&self) {
        self.samples.lock().expect("clock samples").clear();
    }

    fn samples(&self) -> Vec<i64> {
        self.samples.lock().expect("clock samples").clone()
    }
}

impl DurableOperationClock for ManualClock {
    fn now_unix_millis(&self) -> Result<i64, DurableOperationError> {
        let now = self.now.load(Ordering::SeqCst);
        self.samples.lock().expect("clock samples").push(now);
        if let Some(next) = self
            .after_next_sample
            .lock()
            .expect("clock transition")
            .take()
        {
            self.set(next);
        }
        Ok(now)
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable identifier")
}

fn intent(operation: &str) -> DurableOperationIntentV1 {
    DurableOperationIntentV1 {
        scope_id: id("scope.claim-clock"),
        operation_id: id(operation),
        expected_predecessor: None,
        destination: id("learning.ledger"),
        payload_digest: Digest32::of_bytes(operation.as_bytes()),
        owner_generation: Generation::new(1).expect("generation"),
    }
}

async fn fixture() -> (
    tempfile::TempDir,
    DurableOperationStore,
    ManualClock,
    DurableOperationIntentV1,
) {
    let directory = tempfile::tempdir().expect("temporary directory");
    let clock = ManualClock::new(2_000);
    let store = DurableOperationStore::open_with_clock(
        &directory.path().join("operations.sqlite"),
        Arc::new(clock.clone()),
    )
    .await
    .expect("durable store");
    let operation = intent("operation.claim-clock");
    store.prepare_intent(&operation).await.expect("prepare");
    clock.clear_samples();
    (directory, store, clock, operation)
}

async fn snapshot(
    store: &DurableOperationStore,
    operation: &DurableOperationIntentV1,
) -> (DurableOperationRecord, OutboxStatusV1) {
    let record = store
        .operation(&operation.scope_id, &operation.operation_id)
        .await
        .expect("operation lookup")
        .expect("operation record");
    let outbox = store
        .outbox_status(
            &operation.destination,
            &operation.scope_id,
            &operation.operation_id,
        )
        .await
        .expect("outbox lookup")
        .expect("outbox record");
    (record, outbox)
}

async fn live_claim(
    store: &DurableOperationStore,
    operation: &DurableOperationIntentV1,
    lease: Duration,
) -> DispatchClaim {
    store
        .claim_next(
            &operation.destination,
            &id("worker.claim-clock"),
            operation.owner_generation,
            lease,
        )
        .await
        .expect("claim at owned time")
        .expect("prepared operation")
}

async fn require_pending<F: Future>(mut future: Pin<&mut F>) {
    std::future::poll_fn(|context| {
        assert!(future.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;
}

#[tokio::test]
async fn exact_claim_resamples_owned_clock_after_expiry_recovery() {
    let (_directory, store, clock, operation) = fixture().await;
    // Recovery sees 2_000; the exact claim must take its own later sample.
    clock.set_after_next_sample(3_000);
    let claim = store
        .claim_operation(
            &operation.scope_id,
            &operation.operation_id,
            &id("worker.exact-clock"),
            operation.owner_generation,
            Duration::from_millis(100),
        )
        .await
        .expect("exact claim uses owned clock")
        .expect("prepared operation");
    assert_eq!(clock.samples(), vec![2_000, 3_000]);
    assert_eq!(claim.expires_at_unix_ms, 3_100);
    let (record, outbox) = snapshot(&store, &operation).await;
    assert_eq!(record.updated_at_unix_ms, 3_000);
    assert_eq!(outbox.updated_at_unix_ms, 3_000);
    assert_eq!(outbox.lease_until_unix_ms, Some(3_100));
    assert_eq!(claim.intent, operation);
    store.close().await;
}

#[tokio::test]
async fn deferral_uses_owned_clock_for_retry_eligibility() {
    let (_directory, store, clock, operation) = fixture().await;
    let claim = live_claim(&store, &operation, Duration::from_secs(10)).await;
    let (before, _) = snapshot(&store, &operation).await;
    clock.set(2_500);
    clock.clear_samples();
    store
        .defer_pre_dispatch_claim_v1(&claim, Duration::from_millis(100))
        .await
        .expect("defer an unused live claim");
    assert_eq!(clock.samples(), vec![2_500]);
    let (record, outbox) = snapshot(&store, &operation).await;
    assert_eq!(record.intent, operation);
    assert_eq!(record.state, DurableOperationState::Prepared);
    assert_eq!(record.writer_fence, claim.fence + 1);
    assert_eq!(record.revision, before.revision + 1);
    assert_eq!(record.updated_at_unix_ms, 2_500);
    assert_eq!(outbox.state, DurableOutboxState::Queued);
    assert_eq!(outbox.fence, claim.fence + 1);
    assert_eq!(outbox.attempts, 0);
    assert_eq!(outbox.worker_id, None);
    assert_eq!(outbox.lease_until_unix_ms, None);
    assert_eq!(outbox.updated_at_unix_ms, 2_500);
    assert_eq!(outbox.next_eligible_unix_ms, 2_600);
    store.close().await;
}

#[tokio::test]
async fn exact_claim_rejects_second_transaction_clock_rollback_without_mutation() {
    let (_directory, store, clock, operation) = fixture().await;
    let other = intent("operation.newer-clock");
    clock.set(3_000);
    store
        .prepare_intent(&other)
        .await
        .expect("newer active row");
    let before = snapshot(&store, &operation).await;
    let other_before = snapshot(&store, &other).await;
    clock.clear_samples();
    // The preliminary recovery is valid. Roll back only its successor sample;
    // the target's own older timestamp cannot detect the unrelated newer row.
    clock.set_after_next_sample(2_500);
    let error = store
        .claim_operation(
            &operation.scope_id,
            &operation.operation_id,
            &id("worker.rollback-clock"),
            operation.owner_generation,
            Duration::from_millis(100),
        )
        .await
        .expect_err("rollback during exact writer admission");
    assert!(matches!(error, DurableOperationError::ClockRollback));
    assert_eq!(clock.samples(), vec![3_000, 2_500]);
    assert_eq!(snapshot(&store, &operation).await, before);
    assert_eq!(snapshot(&store, &other).await, other_before);
    store.close().await;
}

#[tokio::test]
async fn deferral_rejects_global_clock_rollback_without_mutating_live_claim() {
    let (_directory, store, clock, operation) = fixture().await;
    let claim = live_claim(&store, &operation, Duration::from_secs(10)).await;
    let other = intent("operation.newer-clock");
    clock.set(3_000);
    store
        .prepare_intent(&other)
        .await
        .expect("newer active row");
    let before = snapshot(&store, &operation).await;
    let other_before = snapshot(&store, &other).await;
    clock.set(2_500);
    clock.clear_samples();
    let error = store
        .defer_pre_dispatch_claim_v1(&claim, Duration::from_millis(100))
        .await
        .expect_err("global rollback despite locally live lease");
    assert!(matches!(error, DurableOperationError::ClockRollback));
    assert_eq!(clock.samples(), vec![2_500]);
    assert_eq!(snapshot(&store, &operation).await, before);
    assert_eq!(snapshot(&store, &other).await, other_before);
    store.close().await;
}

#[tokio::test]
async fn deferral_samples_owned_clock_only_after_writer_admission() {
    let (_directory, store, clock, operation) = fixture().await;
    let claim = live_claim(&store, &operation, Duration::from_secs(10)).await;
    // Warm a second connection before holding the real SQLite writer lock.
    let spare = store.pool.acquire().await.expect("spare connection");
    let blocker = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("hold writer admission");
    drop(spare);
    clock.set(1_000);
    clock.clear_samples();
    let mut deferred =
        std::pin::pin!(store.defer_pre_dispatch_claim_v1(&claim, Duration::from_millis(100)));
    require_pending(deferred.as_mut()).await;
    assert!(clock.samples().is_empty(), "blocked writer sampled clock");
    clock.set(3_000);
    blocker.commit().await.expect("release writer admission");
    tokio::time::timeout(Duration::from_secs(2), deferred)
        .await
        .expect("bounded writer completion")
        .expect("fresh time after admission");
    assert_eq!(clock.samples(), vec![3_000]);
    let (record, outbox) = snapshot(&store, &operation).await;
    assert_eq!(record.updated_at_unix_ms, 3_000);
    assert_eq!(outbox.updated_at_unix_ms, 3_000);
    assert_eq!(outbox.next_eligible_unix_ms, 3_100);
    store.close().await;
}

#[tokio::test]
async fn deferral_does_not_requeue_a_lease_expired_during_writer_wait() {
    let (_directory, store, clock, operation) = fixture().await;
    let claim = live_claim(&store, &operation, Duration::from_secs(1)).await;
    assert_eq!(claim.expires_at_unix_ms, 3_000);
    let before = snapshot(&store, &operation).await;
    let spare = store.pool.acquire().await.expect("spare connection");
    let blocker = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("hold writer admission");
    drop(spare);
    clock.clear_samples();
    let mut deferred =
        std::pin::pin!(store.defer_pre_dispatch_claim_v1(&claim, Duration::from_millis(100)));
    require_pending(deferred.as_mut()).await;
    assert!(clock.samples().is_empty(), "blocked writer sampled clock");
    clock.set(3_000);
    blocker.commit().await.expect("release writer admission");
    let error = tokio::time::timeout(Duration::from_secs(2), deferred)
        .await
        .expect("bounded writer completion")
        .expect_err("lease expired before actual writer admission");
    assert!(
        matches!(error, DurableOperationError::Conflict(value) if value == operation.operation_id)
    );
    assert_eq!(clock.samples(), vec![3_000]);
    assert_eq!(snapshot(&store, &operation).await, before);
    store.close().await;
}

#[tokio::test]
async fn recovered_outbox_clock_floor_rejects_exact_claims_without_mutation() {
    let (_directory, store, clock, operation) = fixture().await;
    live_claim(&store, &operation, Duration::from_millis(100)).await;
    let other = intent("operation.older-queued-clock");
    store
        .prepare_intent(&other)
        .await
        .expect("older prepared row");
    clock.set(3_000);
    store
        .recover_expired_leases()
        .await
        .expect("recover unused lease");
    let before = snapshot(&store, &operation).await;
    let other_before = snapshot(&store, &other).await;
    // Unused lease recovery advances only the outbox's durable timestamp.
    assert_eq!(before.0.updated_at_unix_ms, 2_000);
    assert_eq!(before.1.updated_at_unix_ms, 3_000);
    assert_eq!(before.1.state, DurableOutboxState::Queued);
    clock.set(2_500);
    clock.clear_samples();
    for target in [&operation, &other] {
        let error = store
            .claim_operation(
                &target.scope_id,
                &target.operation_id,
                &id("worker.outbox-floor-clock"),
                target.owner_generation,
                Duration::from_millis(100),
            )
            .await
            .expect_err("active outbox timestamp is a durable clock floor");
        assert_eq!(
            error.recovery_disposition(),
            RecoveryDisposition::RepairClockOrStore
        );
        assert!(matches!(error, DurableOperationError::ClockRollback));
        assert_eq!(snapshot(&store, &operation).await, before);
        assert_eq!(snapshot(&store, &other).await, other_before);
    }
    assert_eq!(clock.samples(), vec![2_500, 2_500]);
    store.close().await;
}

#[tokio::test]
async fn recovered_outbox_clock_floor_rejects_other_live_deferral_without_mutation() {
    let (_directory, store, clock, operation) = fixture().await;
    live_claim(&store, &operation, Duration::from_millis(100)).await;
    let other = intent("operation.older-live-clock");
    store
        .prepare_intent(&other)
        .await
        .expect("older prepared row");
    let claim = store
        .claim_operation(
            &other.scope_id,
            &other.operation_id,
            &id("worker.older-live-clock"),
            other.owner_generation,
            Duration::from_secs(10),
        )
        .await
        .expect("other exact claim")
        .expect("other prepared operation");
    clock.set(3_000);
    store
        .recover_expired_leases()
        .await
        .expect("recover only short lease");
    let before = snapshot(&store, &operation).await;
    let other_before = snapshot(&store, &other).await;
    assert_eq!(before.0.updated_at_unix_ms, 2_000);
    assert_eq!(before.1.updated_at_unix_ms, 3_000);
    assert_eq!(other_before.1.state, DurableOutboxState::Leased);
    clock.set(2_500);
    clock.clear_samples();
    let error = store
        .defer_pre_dispatch_claim_v1(&claim, Duration::from_millis(100))
        .await
        .expect_err("unrelated recovered outbox detects clock rollback");
    assert_eq!(
        error.recovery_disposition(),
        RecoveryDisposition::RepairClockOrStore
    );
    assert!(matches!(error, DurableOperationError::ClockRollback));
    assert_eq!(clock.samples(), vec![2_500]);
    assert_eq!(snapshot(&store, &operation).await, before);
    assert_eq!(snapshot(&store, &other).await, other_before);
    store.close().await;
}

#[tokio::test]
async fn settled_outbox_timestamp_does_not_block_new_prepared_work() {
    let (_directory, store, clock, operation) = fixture().await;
    for attempt in 0..MAX_DURABLE_OUTBOX_ATTEMPTS {
        clock.set(2_000 + i64::from(attempt));
        live_claim(&store, &operation, Duration::from_millis(1)).await;
    }
    clock.set(3_000);
    let error = store
        .claim_next(
            &operation.destination,
            &id("worker.settled-clock"),
            operation.owner_generation,
            Duration::from_millis(1),
        )
        .await
        .expect_err("attempt limit settles the operation");
    assert!(matches!(error, DurableOperationError::Capacity));
    let settled = snapshot(&store, &operation).await;
    assert_eq!(settled.0.state, DurableOperationState::Quarantined);
    assert_eq!(settled.0.updated_at_unix_ms, 3_000);
    assert_eq!(settled.1.state, DurableOutboxState::Quarantined);
    assert_eq!(settled.1.updated_at_unix_ms, 3_000);
    clock.set(2_500);
    let other = intent("operation.after-settled-clock");
    store
        .prepare_intent(&other)
        .await
        .expect("settled timestamps are excluded");
    let claim = store
        .claim_operation(
            &other.scope_id,
            &other.operation_id,
            &id("worker.after-settled-clock"),
            other.owner_generation,
            Duration::from_millis(100),
        )
        .await
        .expect("claim after settled future timestamp")
        .expect("new prepared operation");
    assert_eq!(claim.intent, other);
    assert_eq!(claim.expires_at_unix_ms, 2_600);
    assert_eq!(snapshot(&store, &operation).await, settled);
    store.close().await;
}
