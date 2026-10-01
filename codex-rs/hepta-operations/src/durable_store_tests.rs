use super::*;

use std::collections::BTreeSet;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
#[cfg(unix)]
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicI64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::task::Poll;
use std::time::Duration;

use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

fn stable_id(value: &str) -> StableId {
    StableId::new(value).expect("test identifier")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("test generation")
}

fn intent(payload: &[u8]) -> OperationIntentV1 {
    OperationIntentV1 {
        scope_id: stable_id("scope:test"),
        operation_id: stable_id("operation:test:durable"),
        expected_predecessor: None,
        destination: stable_id("automation.taskflow"),
        payload_digest: Digest32::of_bytes(payload),
        owner_generation: generation(1),
    }
}

fn controlled_clock(
    first: &mut DurableOperationStore,
    second: &mut DurableOperationStore,
) -> (Arc<AtomicI64>, Arc<AtomicUsize>) {
    let now = Arc::new(AtomicI64::new(1000));
    let samples = Arc::new(AtomicUsize::new(0));
    let clock_now = Arc::clone(&now);
    let clock_samples = Arc::clone(&samples);
    let clock: TestClock = Arc::new(move || {
        clock_samples.fetch_add(1, Ordering::SeqCst);
        Ok(clock_now.load(Ordering::SeqCst))
    });
    first.clock = Some(Arc::clone(&clock));
    second.clock = Some(clock);
    (now, samples)
}

async fn poll_pending_once<F: Future>(mut future: Pin<&mut F>) {
    std::future::poll_fn(|context| {
        assert!(future.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;
}

#[tokio::test]
async fn queued_writer_samples_clock_after_the_committed_predecessor_cut() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let mut first = DurableOperationStore::open(&path).await.expect("first");
    let mut second = DurableOperationStore::open(&path).await.expect("second");
    let (clock, samples) = controlled_clock(&mut first, &mut second);
    let operation = intent(b"serialized clock");
    first
        .prepare_intent(&operation)
        .await
        .expect("original prepare");
    let mut predecessor = first
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("held writer");
    sqlx::query("UPDATE operation_ledger SET updated_at_ms = 2000")
        .execute(&mut *predecessor)
        .await
        .expect("predecessor advances durable clock");
    sqlx::query("UPDATE cross_owner_outbox SET updated_at_ms = 2000")
        .execute(&mut *predecessor)
        .await
        .expect("matching atomic outbox update");
    samples.store(0, Ordering::SeqCst);
    let pending = second.prepare_intent(&operation);
    tokio::pin!(pending);
    // Poll the real method while another SQLite connection owns the write
    // fence. No wall-clock sample may authorize this still-blocked request.
    poll_pending_once(pending.as_mut()).await;
    assert_eq!(samples.load(Ordering::SeqCst), 0);
    clock.store(2000, Ordering::SeqCst);
    predecessor
        .commit()
        .await
        .expect("release predecessor fence");
    let prepared = pending
        .await
        .expect("normal writer reorder is not clock rollback");
    assert_eq!(prepared.disposition, PrepareDisposition::AlreadyPresent);
    assert_eq!(prepared.record.updated_at_unix_ms, 2000);

    // An actual clock rollback remains fail closed even for an exact retry.
    clock.store(1999, Ordering::SeqCst);
    assert!(matches!(
        second.prepare_intent(&operation).await,
        Err(DurableOperationError::ClockRollback)
    ));
    assert_eq!(
        second
            .operation(&operation.scope_id, &operation.operation_id)
            .await
            .expect("unchanged row")
            .expect("existing identity"),
        prepared.record
    );
    first.close().await;
    second.close().await;
}

#[tokio::test]
async fn blocked_renewal_checks_lease_expiry_at_the_acquired_writer_cut() {
    for after_wait in [1050, 1100] {
        let directory = tempfile::tempdir().expect("tempdir");
        let path = directory.path().join("operations.sqlite3");
        let mut first = DurableOperationStore::open(&path).await.expect("first");
        let mut second = DurableOperationStore::open(&path).await.expect("second");
        let (clock, samples) = controlled_clock(&mut first, &mut second);
        let operation = intent(b"blocked lease boundary");
        first.prepare_intent(&operation).await.expect("prepare");
        let claim = first
            .claim_next(
                &operation.destination,
                &stable_id("worker:test"),
                generation(1),
                Duration::from_millis(100),
            )
            .await
            .expect("claim")
            .expect("lease");
        assert_eq!(claim.expires_at_unix_ms, 1100);
        let before = (
            first
                .operation(&operation.scope_id, &operation.operation_id)
                .await
                .expect("operation")
                .expect("record"),
            first
                .outbox_status(
                    &operation.destination,
                    &operation.scope_id,
                    &operation.operation_id,
                )
                .await
                .expect("outbox")
                .expect("row"),
        );
        let held_writer = first
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .expect("held SQLite writer");
        samples.store(0, Ordering::SeqCst);
        let pending = second.renew_claim(&claim, Duration::from_millis(200));
        tokio::pin!(pending);
        poll_pending_once(pending.as_mut()).await;
        assert_eq!(samples.load(Ordering::SeqCst), 0);
        clock.store(after_wait, Ordering::SeqCst);
        held_writer
            .commit()
            .await
            .expect("release writer after clock advances");
        let result = pending.await;
        let after = (
            second
                .operation(&operation.scope_id, &operation.operation_id)
                .await
                .expect("operation after wait")
                .expect("record"),
            second
                .outbox_status(
                    &operation.destination,
                    &operation.scope_id,
                    &operation.operation_id,
                )
                .await
                .expect("outbox after wait")
                .expect("row"),
        );
        if after_wait == 1100 {
            assert!(matches!(result, Err(DurableOperationError::StaleLease)));
            assert_eq!(after, before);
        } else {
            let renewed = result.expect("still-live claim can renew after waiting");
            let mut expected_claim = claim.clone();
            expected_claim.fence += 1;
            expected_claim.expires_at_unix_ms = 1250;
            assert_eq!(renewed, expected_claim);
            let (mut expected_operation, mut expected_outbox) = before;
            expected_operation.writer_fence += 1;
            expected_operation.revision += 1;
            expected_operation.updated_at_unix_ms = 1050;
            expected_outbox.fence += 1;
            expected_outbox.lease_until_unix_ms = Some(1250);
            expected_outbox.updated_at_unix_ms = 1050;
            assert_eq!(after, (expected_operation, expected_outbox));
        }
        first.close().await;
        second.close().await;
    }
}

#[cfg(unix)]
struct ClaimPersistenceClock {
    operation_clock: Arc<AtomicI64>,
    after_persistence: i64,
    armed: AtomicBool,
    samples: AtomicUsize,
}

#[cfg(unix)]
impl codex_hepta_contracts::AuthorityClock for ClaimPersistenceClock {
    fn now_unix_ms(&self) -> Result<u64, codex_hepta_contracts::AuthorityTrustError> {
        if self.armed.load(Ordering::SeqCst) && self.samples.fetch_add(1, Ordering::SeqCst) > 0 {
            // The second claim-time sample happens after append_claim fsync.
            self.operation_clock
                .store(self.after_persistence, Ordering::SeqCst);
        }
        u64::try_from(self.operation_clock.load(Ordering::SeqCst))
            .map_err(|_| codex_hepta_contracts::AuthorityTrustError::Invalid)
    }
}

#[cfg(unix)]
#[tokio::test]
async fn dispatch_rechecks_lease_after_final_use_claim_persistence() {
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    for after_persistence in [1099, 1100] {
        let directory = tempfile::tempdir().expect("tempdir");
        let path = directory.path().join("operations.sqlite3");
        let mut store = DurableOperationStore::open(&path).await.expect("store");
        let operation_clock = Arc::new(AtomicI64::new(1000));
        let clock = Arc::clone(&operation_clock);
        store.clock = Some(Arc::new(move || Ok(clock.load(Ordering::SeqCst))));
        let operation = intent(b"claim persistence lease boundary");
        store.prepare_intent(&operation).await.expect("prepare");
        let claim = store
            .claim_next(
                &operation.destination,
                &stable_id("worker:test"),
                generation(1),
                Duration::from_millis(100),
            )
            .await
            .expect("claim")
            .expect("lease");
        let before = (
            store
                .operation(&operation.scope_id, &operation.operation_id)
                .await
                .expect("original operation")
                .expect("row"),
            store
                .outbox_status(
                    &operation.destination,
                    &operation.scope_id,
                    &operation.operation_id,
                )
                .await
                .expect("original outbox")
                .expect("row"),
        );
        operation_clock.store(1050, Ordering::SeqCst);
        let authority_clock = Arc::new(ClaimPersistenceClock {
            operation_clock,
            after_persistence,
            armed: AtomicBool::new(false),
            samples: AtomicUsize::new(0),
        });
        // Reuse the actual trusted signing fixture and durable authority state,
        // with a controlled time window that remains live across both cases.
        let (original_authority, mut signed, authority_dir) = authority_fixture(&operation, 31);
        drop(original_authority);
        signed.grant.not_before_unix_ms = 1000;
        signed.grant.expires_at_unix_ms = 10000;
        let signing = SigningKey::from_bytes(&[47; 32]);
        signed.signature = signing
            .sign(&signed.grant.signing_bytes().expect("grant bytes"))
            .to_bytes()
            .to_vec();
        let authority = FinalUseAuthority::open_state_dir_with_clock(
            authority_dir.path(),
            "security-owner".to_string(),
            signing.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
            authority_clock.clone(),
        )
        .expect("controlled durable authority");
        authority_clock.armed.store(true, Ordering::SeqCst);
        let result = store.authorize_dispatch(&authority, &signed, &claim).await;
        let after = (
            store
                .operation(&operation.scope_id, &operation.operation_id)
                .await
                .expect("operation after claim")
                .expect("row"),
            store
                .outbox_status(
                    &operation.destination,
                    &operation.scope_id,
                    &operation.operation_id,
                )
                .await
                .expect("outbox after claim")
                .expect("row"),
        );
        assert_eq!(
            authority
                .capacity()
                .expect("durable nonce capacity")
                .used_nonces,
            1
        );
        assert!(matches!(
            authority.claim(&signed, &signed.grant.binding),
            Err(codex_hepta_contracts::FinalUseError::AlreadyClaimed)
        ));
        if after_persistence == 1100 {
            assert!(matches!(result, Err(DurableOperationError::StaleLease)));
            assert_eq!(after, before);
        } else {
            let authorized = result.expect("claim remains live before lease deadline");
            assert_eq!(authorized.claim(), &claim);
            let (mut expected_operation, expected_outbox) = before;
            expected_operation.state = DurableOperationState::Dispatching;
            expected_operation.authority_epoch = Some(9);
            expected_operation.authority_digest = Some(Digest32::of_bytes(
                &signed.grant.signing_bytes().expect("authority bytes"),
            ));
            expected_operation.revision += 1;
            expected_operation.updated_at_unix_ms = 1099;
            assert_eq!(after, (expected_operation, expected_outbox));
        }
        store.close().await;
    }
}

#[tokio::test]
async fn prepare_is_atomic_and_survives_reopen() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let operation = intent(b"payload");
    let store = DurableOperationStore::open(&path).await.expect("open");
    let prepared = store.prepare_intent(&operation).await.expect("prepare");
    assert_eq!(prepared.disposition, PrepareDisposition::Inserted);
    let counts: (i64, i64) = sqlx::query_as(
        "SELECT (SELECT COUNT(*) FROM operation_ledger),
                (SELECT COUNT(*) FROM cross_owner_outbox)",
    )
    .fetch_one(&store.pool)
    .await
    .expect("counts");
    assert_eq!(counts, (1, 1));
    store.close().await;

    let reopened = DurableOperationStore::open(&path).await.expect("reopen");
    let record = reopened
        .operation(&operation.scope_id, &operation.operation_id)
        .await
        .expect("lookup")
        .expect("operation");
    assert_eq!(record.state, DurableOperationState::Prepared);
    let outbox = reopened
        .outbox_status(
            &operation.destination,
            &operation.scope_id,
            &operation.operation_id,
        )
        .await
        .expect("outbox")
        .expect("outbox row");
    assert_eq!(outbox.state, DurableOutboxState::Queued);
}

#[tokio::test]
async fn exact_multiwriter_prepare_is_idempotent_and_payload_drift_conflicts() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let first = DurableOperationStore::open(&path).await.expect("open one");
    let second = DurableOperationStore::open(&path).await.expect("open two");
    let operation = intent(b"payload");
    let a = operation.clone();
    let b = operation.clone();
    let (left, right) = tokio::join!(first.prepare_intent(&a), second.prepare_intent(&b));
    let left = left.expect("left");
    let right = right.expect("right");
    assert!(matches!(
        (left.disposition, right.disposition),
        (
            PrepareDisposition::Inserted,
            PrepareDisposition::AlreadyPresent
        ) | (
            PrepareDisposition::AlreadyPresent,
            PrepareDisposition::Inserted
        ) | (
            PrepareDisposition::AlreadyPresent,
            PrepareDisposition::AlreadyPresent
        )
    ));
    let changed = intent(b"changed");
    assert!(matches!(
        first.prepare_intent(&changed).await,
        Err(DurableOperationError::Conflict(_))
    ));
}

#[tokio::test]
async fn expired_safe_lease_can_be_taken_over_by_higher_generation() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let first = DurableOperationStore::open(&path).await.expect("open one");
    let second = DurableOperationStore::open(&path).await.expect("open two");
    let operation = intent(b"payload");
    first.prepare_intent(&operation).await.expect("prepare");
    let stale = first
        .claim_next(
            &operation.destination,
            &stable_id("worker:one"),
            generation(1),
            Duration::from_millis(1),
        )
        .await
        .expect("claim")
        .expect("claim row");
    tokio::time::sleep(Duration::from_millis(5)).await;
    let current = second
        .claim_next(
            &operation.destination,
            &stable_id("worker:two"),
            generation(2),
            Duration::from_secs(1),
        )
        .await
        .expect("takeover")
        .expect("current claim");
    assert!(current.fence > stale.fence);
    assert_eq!(current.owner_generation, generation(2));
    assert!(matches!(
        first.renew_claim(&stale, Duration::from_secs(1)).await,
        Err(DurableOperationError::StaleLease)
    ));
}

#[cfg(unix)]
fn authority_fixture(
    operation: &OperationIntentV1,
    nonce: u8,
) -> (
    codex_hepta_contracts::FinalUseAuthority,
    SignedFinalUseGrant,
    tempfile::TempDir,
) {
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use std::os::unix::fs::PermissionsExt;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    let signing = SigningKey::from_bytes(&[47; 32]);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner".to_owned(),
        authority_epoch: 9,
        grant_id: format!("grant-{nonce}"),
        nonce: [nonce; 32],
        binding: operation.final_use_binding(),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signature = signing
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    let directory = tempfile::tempdir().expect("authority tempdir");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
        .expect("permissions");
    let authority = codex_hepta_contracts::FinalUseAuthority::open_state_dir(
        directory.path(),
        "security-owner".to_owned(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    (
        authority,
        SignedFinalUseGrant { grant, signature },
        directory,
    )
}

#[cfg(unix)]
#[tokio::test]
async fn crash_after_dispatch_admission_recovers_as_indeterminate_not_retryable() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let operation = intent(b"payload");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store.prepare_intent(&operation).await.expect("prepare");
    let claim = store
        .claim_next(
            &operation.destination,
            &stable_id("worker:one"),
            generation(1),
            Duration::from_secs(30),
        )
        .await
        .expect("claim")
        .expect("row");
    let (authority, signed, _authority_dir) = authority_fixture(&claim.intent, 5);
    let authorized = store
        .authorize_dispatch(&authority, &signed, &claim)
        .await
        .expect("authorize dispatch");
    drop(authorized);
    // Expire only after the durable dispatch admission. Do not race a 1ms
    // lease against authority initialization, signing and filesystem sync.
    sqlx::query(
        "UPDATE cross_owner_outbox SET lease_until_ms = ?
         WHERE destination = ? AND scope_id = ? AND operation_id = ?",
    )
    .bind(now_millis().expect("expiry clock"))
    .bind(operation.destination.as_str())
    .bind(operation.scope_id.as_str())
    .bind(operation.operation_id.as_str())
    .execute(&store.pool)
    .await
    .expect("expire admitted dispatch fixture");
    store.close().await;

    let reopened = DurableOperationStore::open(&path).await.expect("reopen");
    let record = reopened
        .operation(&operation.scope_id, &operation.operation_id)
        .await
        .expect("lookup")
        .expect("operation");
    assert_eq!(record.state, DurableOperationState::Indeterminate);
    assert!(
        reopened
            .claim_next(
                &operation.destination,
                &stable_id("worker:two"),
                generation(2),
                Duration::from_secs(1),
            )
            .await
            .expect("claim query")
            .is_none()
    );
}

#[cfg(unix)]
#[tokio::test]
async fn acknowledgement_loss_stays_indeterminate_until_terminal_observer() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let operation = intent(b"payload");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store.prepare_intent(&operation).await.expect("prepare");
    let claim = store
        .claim_next(
            &operation.destination,
            &stable_id("worker:one"),
            generation(1),
            Duration::from_secs(1),
        )
        .await
        .expect("claim")
        .expect("row");
    let (authority, signed, _authority_dir) = authority_fixture(&claim.intent, 6);
    let authorized = store
        .authorize_dispatch(&authority, &signed, &claim)
        .await
        .expect("authorize dispatch");
    let value = store
        .execute_authorized(authorized, |_| DispatchEffect::Dispatched {
            value: 7,
            dispatch_digest: Digest32::of_bytes(b"sent"),
            acknowledgement_digest: None,
        })
        .await
        .expect("effect");
    assert_eq!(value, 7);
    let unknown = store
        .operation(&operation.scope_id, &operation.operation_id)
        .await
        .expect("lookup")
        .expect("operation");
    assert_eq!(unknown.state, DurableOperationState::Indeterminate);
    let terminal = store
        .observe_terminal(
            &operation.scope_id,
            &operation.operation_id,
            &ReconciliationReceiptV1 {
                outcome: ReconciliationOutcome::Applied,
                evidence_digest: Digest32::of_bytes(b"destination-observed"),
                observer_id: stable_id("observer:automation"),
                observer_generation: generation(1),
            },
        )
        .await
        .expect("reconcile");
    assert_eq!(terminal.state, DurableOperationState::Applied);
    let outbox = store
        .outbox_status(
            &operation.destination,
            &operation.scope_id,
            &operation.operation_id,
        )
        .await
        .expect("outbox")
        .expect("row");
    assert_eq!(outbox.state, DurableOutboxState::Acknowledged);
}

#[cfg(unix)]
#[tokio::test]
async fn newer_generation_adopts_unsettled_dispatch_and_fences_predecessor() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let operation = intent(b"owner-handoff-payload");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store.prepare_intent(&operation).await.expect("prepare");
    let stale_claim = store
        .claim_next(
            &operation.destination,
            &stable_id("worker:old-generation"),
            generation(1),
            Duration::from_secs(30),
        )
        .await
        .expect("claim")
        .expect("row");
    let (authority, signed, _authority_dir) = authority_fixture(&stale_claim.intent, 17);
    let authorized = store
        .authorize_dispatch(&authority, &signed, &stale_claim)
        .await
        .expect("authorize");
    store
        .execute_authorized(authorized, |_| DispatchEffect::Dispatched {
            value: (),
            dispatch_digest: Digest32::of_bytes(b"transport-dispatched"),
            acknowledgement_digest: Some(Digest32::of_bytes(b"transport-acknowledged")),
        })
        .await
        .expect("dispatch");

    let before = store
        .operation(&operation.scope_id, &operation.operation_id)
        .await
        .expect("lookup")
        .expect("operation");
    assert_eq!(before.state, DurableOperationState::Dispatched);
    assert_eq!(before.intent.owner_generation, generation(1));

    let adopted = store
        .adopt_unsettled_generation(&operation.scope_id, &operation.operation_id, generation(2))
        .await
        .expect("adopt newer generation");
    assert_eq!(adopted.intent.owner_generation, generation(2));
    assert_eq!(adopted.state, DurableOperationState::Indeterminate);
    assert!(adopted.writer_fence > stale_claim.fence);
    let outbox = store
        .outbox_status(
            &operation.destination,
            &operation.scope_id,
            &operation.operation_id,
        )
        .await
        .expect("outbox")
        .expect("row");
    assert_eq!(outbox.intent.owner_generation, generation(2));
    assert_eq!(outbox.state, DurableOutboxState::Acknowledged);
    assert_eq!(outbox.fence, adopted.writer_fence);

    assert!(matches!(
        store
            .observe_terminal(
                &operation.scope_id,
                &operation.operation_id,
                &ReconciliationReceiptV1 {
                    outcome: ReconciliationOutcome::Applied,
                    evidence_digest: Digest32::of_bytes(b"stale-terminal-evidence"),
                    observer_id: stable_id("observer:old-generation"),
                    observer_generation: generation(1),
                },
            )
            .await,
        Err(DurableOperationError::StaleGeneration)
    ));

    let replay = store
        .adopt_unsettled_generation(&operation.scope_id, &operation.operation_id, generation(2))
        .await
        .expect("same generation replay");
    assert_eq!(replay, adopted);

    let terminal = store
        .observe_terminal(
            &operation.scope_id,
            &operation.operation_id,
            &ReconciliationReceiptV1 {
                outcome: ReconciliationOutcome::Applied,
                evidence_digest: Digest32::of_bytes(b"destination-terminal-evidence"),
                observer_id: stable_id("observer:new-generation"),
                observer_generation: generation(2),
            },
        )
        .await
        .expect("current generation terminal observation");
    assert_eq!(terminal.state, DurableOperationState::Applied);
}

#[cfg(unix)]
#[tokio::test]
async fn proven_not_dispatched_requeues_with_a_new_fence() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let operation = intent(b"payload");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store.prepare_intent(&operation).await.expect("prepare");
    let claim = store
        .claim_next(
            &operation.destination,
            &stable_id("worker:one"),
            generation(1),
            Duration::from_secs(1),
        )
        .await
        .expect("claim")
        .expect("row");
    let (authority, signed, _authority_dir) = authority_fixture(&claim.intent, 7);
    let authorized = store
        .authorize_dispatch(&authority, &signed, &claim)
        .await
        .expect("authorize");
    store
        .execute_authorized(authorized, |_| DispatchEffect::NotDispatched {
            value: (),
            reason_digest: Digest32::of_bytes(b"connection-refused-before-write"),
            retry_after: Duration::ZERO,
        })
        .await
        .expect("classify");
    let next = store
        .claim_next(
            &operation.destination,
            &stable_id("worker:two"),
            generation(1),
            Duration::from_secs(1),
        )
        .await
        .expect("reclaim")
        .expect("row");
    assert!(next.fence > claim.fence);
    assert_eq!(next.attempts, 2);
}

#[tokio::test]
async fn terminal_gc_writes_tombstone_and_prevents_resurrection() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let operation = intent(b"payload");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store.prepare_intent(&operation).await.expect("prepare");
    let claim = store
        .claim_next(
            &operation.destination,
            &stable_id("worker:one"),
            generation(1),
            Duration::from_secs(1),
        )
        .await
        .expect("claim")
        .expect("row");
    sqlx::query(
        "UPDATE operation_ledger SET state = 'indeterminate', indeterminate_digest = ?,
         revision = revision + 1 WHERE scope_id = ? AND operation_id = ?",
    )
    .bind(Digest32::of_bytes(b"fixture").as_array().as_slice())
    .bind(operation.scope_id.as_str())
    .bind(operation.operation_id.as_str())
    .execute(&store.pool)
    .await
    .expect("fixture state");
    let terminal = store
        .observe_terminal(
            &operation.scope_id,
            &operation.operation_id,
            &ReconciliationReceiptV1 {
                outcome: ReconciliationOutcome::NotApplied,
                evidence_digest: Digest32::of_bytes(b"not-applied"),
                observer_id: stable_id("observer:test"),
                observer_generation: claim.owner_generation,
            },
        )
        .await
        .expect("terminal");
    let settled_at = terminal.terminal_at_unix_ms.expect("terminal timestamp");
    assert!(settled_at > 0);
    assert_eq!(
        store
            .prune_terminal(settled_at - 1, 10)
            .await
            .expect("before inclusive cutoff"),
        0
    );
    let pruned = store
        .prune_terminal(settled_at, 10)
        .await
        .expect("prune at inclusive cutoff");
    assert_eq!(pruned, 1);
    assert!(matches!(
        store.prepare_intent(&operation).await,
        Err(DurableOperationError::Retired(_))
    ));
}

#[tokio::test]
async fn retirement_never_discards_an_unreconciled_external_effect() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let operation = intent(b"retirement-payload");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store.prepare_intent(&operation).await.expect("prepare");
    let claim = store
        .claim_next(
            &operation.destination,
            &stable_id("worker:retirement"),
            generation(1),
            Duration::from_secs(1),
        )
        .await
        .expect("claim")
        .expect("row");

    sqlx::query(
        "UPDATE operation_ledger SET state = 'indeterminate', indeterminate_digest = ?,
         revision = revision + 1 WHERE scope_id = ? AND operation_id = ?",
    )
    .bind(
        Digest32::of_bytes(b"effect-may-have-crossed")
            .as_array()
            .as_slice(),
    )
    .bind(operation.scope_id.as_str())
    .bind(operation.operation_id.as_str())
    .execute(&store.pool)
    .await
    .expect("fixture indeterminate");

    assert_eq!(
        store.prune_terminal(u64::MAX, 10).await.expect("prune"),
        0,
        "retirement/GC must not erase an unresolved external effect",
    );
    let still_open = store
        .operation(&operation.scope_id, &operation.operation_id)
        .await
        .expect("lookup")
        .expect("operation remains");
    assert_eq!(still_open.state, DurableOperationState::Indeterminate);

    store
        .observe_terminal(
            &operation.scope_id,
            &operation.operation_id,
            &ReconciliationReceiptV1 {
                outcome: ReconciliationOutcome::Applied,
                evidence_digest: Digest32::of_bytes(b"terminal-retirement-observation"),
                observer_id: stable_id("observer:retirement"),
                observer_generation: claim.owner_generation,
            },
        )
        .await
        .expect("reconcile before retirement");
    assert_eq!(store.prune_terminal(u64::MAX, 10).await.expect("prune"), 1);
    assert!(matches!(
        store.prepare_intent(&operation).await,
        Err(DurableOperationError::Retired(_))
    ));
}

#[tokio::test]
async fn migration_checksum_tamper_fails_reopen() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store.close().await;
    let pool = crate::sqlite::open_durable_pool(&path)
        .await
        .expect("raw open");
    sqlx::query("UPDATE _sqlx_migrations SET checksum = X'00' WHERE version = 1")
        .execute(&pool)
        .await
        .expect("tamper");
    pool.close().await;
    assert!(matches!(
        DurableOperationStore::open(&path).await,
        Err(DurableOperationError::Corrupt(_))
    ));
}

#[tokio::test]
async fn future_migration_lineage_blocks_old_binary_reopen() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store.close().await;
    let pool = crate::sqlite::open_durable_pool(&path)
        .await
        .expect("raw open");
    sqlx::query(
        "INSERT INTO _sqlx_migrations
         (version, description, success, checksum, execution_time)
         VALUES (999, 'future_kernel_operations_schema', 1, X'00', 0)",
    )
    .execute(&pool)
    .await
    .expect("install future migration marker");
    pool.close().await;

    assert!(matches!(
        DurableOperationStore::open(&path).await,
        Err(DurableOperationError::Corrupt(_))
    ));
}

#[tokio::test]
async fn corrupt_database_fails_closed() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store.close().await;
    std::fs::write(&path, b"not a sqlite database").expect("corrupt");
    assert!(DurableOperationStore::open(&path).await.is_err());
}

#[tokio::test]
async fn retirement_cutoff_range_never_retires_pending_work_or_relaxes_batch_limits() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let operation = intent(b"pending cutoff boundary");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store.prepare_intent(&operation).await.expect("prepare");
    for cutoff in [0, 1, i64::MAX as u64, (i64::MAX as u64) + 1, u64::MAX] {
        assert_eq!(store.prune_terminal(cutoff, 1).await.expect("cutoff"), 0);
        assert_eq!(
            store
                .operation(&operation.scope_id, &operation.operation_id)
                .await
                .expect("lookup")
                .expect("pending identity retained")
                .state,
            DurableOperationState::Prepared
        );
    }
    for limit in [0, MAX_DURABLE_CLAIM_BATCH + 1] {
        assert!(matches!(
            store.prune_terminal(u64::MAX, limit).await,
            Err(DurableOperationError::Invalid("prune limit"))
        ));
    }
    // The query-bound rule is not a permissive replacement for value storage.
    assert!(matches!(
        to_i64(u64::MAX),
        Err(DurableOperationError::Capacity)
    ));
    store.close().await;
}
