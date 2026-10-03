use super::*;

type OwnerSnapshot = (String, i64, i64, i64);

#[derive(Debug, PartialEq)]
struct Snapshot {
    owner: OwnerSnapshot,
    batch: Option<EvidencePublicationBatchV1>,
    accepted: Option<EvidenceAcceptedFrontierV1>,
    pending: u64,
}

struct Fixture {
    temp: TempDir,
    store: HeptaEvidenceStore,
    clock: Arc<AtomicU64>,
    lease: EvidencePublicationOwnerLeaseV1,
    batch: EvidencePublicationBatchV1,
    frontier: Sha256Digest,
    backend: Sha256Digest,
}

impl Fixture {
    async fn new() -> Self {
        let temp = TempDir::new().expect("temp dir");
        let mut store = HeptaEvidenceStore::open(&config(&temp))
            .await
            .expect("open store");
        let clock = Arc::new(AtomicU64::new(100));
        store.publication_test_time_ms = Some(Arc::clone(&clock));
        store
            .bind_recovery_store_id("store:clock")
            .await
            .expect("enroll");
        insert_evidence(&store, "clock", /*recorded_at_ms*/ 10).await;
        let lease = store
            .claim_publication_owner("publisher:clock", /*lease_duration_ms*/ 1_000)
            .await
            .expect("claim");
        let batch = store
            .prepare_publication_batch(&lease, /*maximum_intents*/ 1)
            .await
            .expect("prepare")
            .expect("batch");
        Self {
            temp,
            store,
            clock,
            lease,
            batch,
            frontier: Sha256Digest::for_bytes(b"clock-frontier"),
            backend: Sha256Digest::for_bytes(b"clock-backend"),
        }
    }

    async fn snapshot(&self) -> Snapshot {
        Snapshot {
            owner: sqlx::query_as("SELECT owner_id, owner_generation, lease_expires_at_ms, updated_at_ms FROM evidence_publication_owner WHERE store_id = ?")
                .bind(&self.lease.store_id).fetch_one(&self.store.pool).await.expect("owner snapshot"),
            batch: self.store.publication_batch(&self.batch.batch_id).await.expect("batch snapshot"),
            accepted: self.store.latest_accepted_frontier(&self.lease.store_id).await.expect("accepted snapshot"),
            pending: self.store.pending_publication_count().await.expect("pending snapshot"),
        }
    }

    fn acknowledgement(&self) -> EvidenceFrontierDurableAckV1 {
        EvidenceFrontierDurableAckV1 {
            backend_id: "backend:clock".to_string(),
            backend_identity_sha256: self.backend.clone(),
            store_id: self.lease.store_id.clone(),
            frontier_generation: self.batch.proposed_frontier_generation,
            frontier_sha256: self.frontier.clone(),
            audit_sequence: 1,
        }
    }
}

fn assert_clock_error<T: std::fmt::Debug>(result: Result<T, EvidenceError>) {
    assert!(
        matches!(&result, Err(EvidenceError::Unavailable(message)) if message.contains("clock")),
        "expected a fail-closed publication clock error: {result:?}"
    );
}

#[tokio::test]
async fn claim_wait_resamples_clock_and_exact_expiry_advances_generation() {
    let fixture = Fixture::new().await;
    let blocker = fixture
        .store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("hold writer");
    let renewed = {
        let claim = fixture
            .store
            .claim_publication_owner("publisher:clock", /*lease_duration_ms*/ 500);
        tokio::pin!(claim);
        assert!(
            tokio::time::timeout(std::time::Duration::from_millis(25), claim.as_mut())
                .await
                .is_err()
        );
        fixture
            .clock
            .store(fixture.lease.lease_expires_at_unix_ms, Ordering::SeqCst);
        blocker.rollback().await.expect("release writer");
        claim.await.expect("fresh claim after expiry")
    };
    assert_eq!(
        renewed,
        EvidencePublicationOwnerLeaseV1 {
            store_id: fixture.lease.store_id.clone(),
            owner_id: fixture.lease.owner_id.clone(),
            owner_generation: 2,
            lease_expires_at_unix_ms: 1_600,
        }
    );
    assert_eq!(
        fixture
            .store
            .publication_batch(&fixture.batch.batch_id)
            .await
            .expect("batch"),
        Some(fixture.batch.clone())
    );
    assert_eq!(
        fixture
            .store
            .claim_publication_owner("publisher:clock", /*lease_duration_ms*/ 500)
            .await
            .expect("idempotent renewal"),
        renewed
    );
}

#[tokio::test]
async fn all_writers_reject_clock_rollback_and_invalid_range_without_mutation() {
    let fixture = Fixture::new().await;
    fixture.clock.store(120, Ordering::SeqCst);
    fixture
        .store
        .prepare_publication_batch(&fixture.lease, /*maximum_intents*/ 1)
        .await
        .expect("advance owner floor");
    let before = fixture.snapshot().await;
    assert_eq!(before.owner.3, 120);
    for now in [119, 0, i64::MAX as u64 + 1, u64::MAX] {
        fixture.clock.store(now, Ordering::SeqCst);
        assert_clock_error(
            fixture
                .store
                .claim_publication_owner("publisher:clock", /*lease_duration_ms*/ 100)
                .await,
        );
        assert_clock_error(
            fixture
                .store
                .prepare_publication_batch(&fixture.lease, /*maximum_intents*/ 1)
                .await,
        );
        assert_clock_error(
            fixture
                .store
                .mark_publication_dispatched(
                    &fixture.lease,
                    &fixture.batch.batch_id,
                    &fixture.frontier,
                    &fixture.backend,
                )
                .await,
        );
        assert_clock_error(
            fixture
                .store
                .mark_publication_indeterminate(&fixture.lease, &fixture.batch.batch_id)
                .await,
        );
        assert_clock_error(
            fixture
                .store
                .acknowledge_publication(
                    &fixture.lease,
                    &fixture.batch.batch_id,
                    &fixture.acknowledgement(),
                )
                .await,
        );
        assert_eq!(fixture.snapshot().await, before);
    }
    fixture.clock.store(i64::MAX as u64 - 50, Ordering::SeqCst);
    assert!(
        fixture
            .store
            .claim_publication_owner("publisher:clock", /*lease_duration_ms*/ 100)
            .await
            .is_err(),
        "lease expiry overflow must fail closed"
    );
    assert_eq!(fixture.snapshot().await, before);
    fixture.clock.store(120, Ordering::SeqCst);
    for duration in [0, MAX_PUBLICATION_LEASE_MS + 1] {
        assert!(
            fixture
                .store
                .claim_publication_owner("publisher:clock", duration)
                .await
                .is_err()
        );
        assert_eq!(fixture.snapshot().await, before);
    }
    let maximum = fixture
        .store
        .claim_publication_owner("publisher:clock", MAX_PUBLICATION_LEASE_MS)
        .await
        .expect("maximum supported duration");
    assert_eq!(
        maximum,
        EvidencePublicationOwnerLeaseV1 {
            store_id: fixture.lease.store_id.clone(),
            owner_id: fixture.lease.owner_id.clone(),
            owner_generation: fixture.lease.owner_generation,
            lease_expires_at_unix_ms: 120 + MAX_PUBLICATION_LEASE_MS,
        }
    );
}

#[tokio::test]
async fn exact_expiry_and_terminal_replays_preserve_receipts_and_fences() {
    let fixture = Fixture::new().await;
    fixture.clock.store(1_099, Ordering::SeqCst);
    fixture
        .store
        .mark_publication_dispatched(
            &fixture.lease,
            &fixture.batch.batch_id,
            &fixture.frontier,
            &fixture.backend,
        )
        .await
        .expect("dispatch immediately before expiry");
    let before = fixture.snapshot().await;
    fixture.clock.store(1_100, Ordering::SeqCst);
    assert!(
        fixture
            .store
            .acknowledge_publication(
                &fixture.lease,
                &fixture.batch.batch_id,
                &fixture.acknowledgement()
            )
            .await
            .is_err()
    );
    assert!(
        fixture
            .store
            .mark_publication_dispatched(
                &fixture.lease,
                &fixture.batch.batch_id,
                &fixture.frontier,
                &fixture.backend
            )
            .await
            .is_err()
    );
    assert!(
        fixture
            .store
            .mark_publication_indeterminate(&fixture.lease, &fixture.batch.batch_id)
            .await
            .is_err()
    );
    assert!(
        fixture
            .store
            .prepare_publication_batch(&fixture.lease, /*maximum_intents*/ 1)
            .await
            .is_err()
    );
    assert_eq!(fixture.snapshot().await, before);
    let successor = fixture
        .store
        .claim_publication_owner("publisher:successor", /*lease_duration_ms*/ 100)
        .await
        .expect("claim at exact expiry");
    assert_eq!(successor.owner_generation, 2);
    fixture.clock.store(1_101, Ordering::SeqCst);
    let acknowledgement = fixture.acknowledgement();
    assert_eq!(
        fixture
            .store
            .acknowledge_publication(&successor, &fixture.batch.batch_id, &acknowledgement)
            .await
            .expect("successor settles exact receipt"),
        EvidencePublicationAckDisposition::Acknowledged
    );
    let settled = fixture.snapshot().await;
    fixture.clock.store(1_102, Ordering::SeqCst);
    let mut wrong_receipt = acknowledgement.clone();
    wrong_receipt.audit_sequence += 1;
    assert!(
        fixture
            .store
            .acknowledge_publication(&successor, &fixture.batch.batch_id, &wrong_receipt)
            .await
            .is_err()
    );
    let mut wrong_fence = successor.clone();
    wrong_fence.lease_expires_at_unix_ms += 1;
    assert!(
        fixture
            .store
            .acknowledge_publication(&wrong_fence, &fixture.batch.batch_id, &acknowledgement)
            .await
            .is_err()
    );
    assert_eq!(
        fixture.snapshot().await,
        settled,
        "failed receipt/fence checks roll back the owner floor too"
    );
    assert_eq!(
        fixture
            .store
            .acknowledge_publication(&successor, &fixture.batch.batch_id, &acknowledgement)
            .await
            .expect("exact replay"),
        EvidencePublicationAckDisposition::AlreadyAcknowledged
    );
    let replayed = fixture.snapshot().await;
    assert_eq!(replayed.pending, 0);
    let mut expected_replay = settled;
    expected_replay.owner.3 = 1_102;
    assert_eq!(replayed, expected_replay);
}

#[tokio::test]
async fn legacy_batch_floor_failure_rolls_back_the_owner_floor_update() {
    let fixture = Fixture::new().await;
    fixture.clock.store(200, Ordering::SeqCst);
    fixture
        .store
        .mark_publication_dispatched(
            &fixture.lease,
            &fixture.batch.batch_id,
            &fixture.frontier,
            &fixture.backend,
        )
        .await
        .expect("dispatch");
    // This legitimate transition models pre-repair history, when publication
    // writes did not advance the separate owner's timestamp.
    sqlx::query("UPDATE evidence_publication_batches SET state = 'indeterminate', updated_at_ms = 300 WHERE batch_id = ?")
        .bind(&fixture.batch.batch_id).execute(&fixture.store.pool).await.expect("pre-repair batch history");
    let before = fixture.snapshot().await;
    fixture.clock.store(250, Ordering::SeqCst);
    assert_clock_error(
        fixture
            .store
            .prepare_publication_batch(&fixture.lease, /*maximum_intents*/ 1)
            .await,
    );
    assert_clock_error(
        fixture
            .store
            .mark_publication_dispatched(
                &fixture.lease,
                &fixture.batch.batch_id,
                &fixture.frontier,
                &fixture.backend,
            )
            .await,
    );
    assert_clock_error(
        fixture
            .store
            .mark_publication_indeterminate(&fixture.lease, &fixture.batch.batch_id)
            .await,
    );
    assert_clock_error(
        fixture
            .store
            .acknowledge_publication(
                &fixture.lease,
                &fixture.batch.batch_id,
                &fixture.acknowledgement(),
            )
            .await,
    );
    assert_eq!(fixture.snapshot().await, before);
}

#[tokio::test]
async fn cancellation_behind_a_writer_preserves_the_complete_projection() {
    let fixture = Fixture::new().await;
    let before = fixture.snapshot().await;
    let blocker = fixture
        .store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("hold writer");
    {
        let dispatch = fixture.store.mark_publication_dispatched(
            &fixture.lease,
            &fixture.batch.batch_id,
            &fixture.frontier,
            &fixture.backend,
        );
        tokio::pin!(dispatch);
        assert!(
            tokio::time::timeout(std::time::Duration::from_millis(25), dispatch.as_mut())
                .await
                .is_err()
        );
        fixture.clock.store(200, Ordering::SeqCst);
        // Drop the in-flight write before releasing its admission barrier.
    }
    blocker.rollback().await.expect("release writer");
    let next_writer = tokio::time::timeout(
        std::time::Duration::from_secs(5),
        fixture.store.pool.begin_with("BEGIN IMMEDIATE"),
    )
    .await
    .expect("cancelled write must permit a new writer")
    .expect("acquire new writer after cancellation");
    next_writer.rollback().await.expect("release probe writer");
    let after = tokio::time::timeout(std::time::Duration::from_secs(5), fixture.snapshot())
        .await
        .expect("read owner, batch and frontier after writer reuse");
    assert_eq!(after, before);
}

#[tokio::test]
async fn owner_clock_floor_survives_reopen() {
    let fixture = Fixture::new().await;
    fixture.clock.store(120, Ordering::SeqCst);
    fixture
        .store
        .prepare_publication_batch(&fixture.lease, /*maximum_intents*/ 1)
        .await
        .expect("advance floor");
    let before = fixture.snapshot().await;
    let Fixture {
        temp,
        store,
        clock,
        lease,
        batch,
        frontier,
        backend,
    } = fixture;
    store.close().await;
    let mut store = HeptaEvidenceStore::open(&config(&temp))
        .await
        .expect("reopen");
    store.publication_test_time_ms = Some(Arc::clone(&clock));
    clock.store(119, Ordering::SeqCst);
    let fixture = Fixture {
        temp,
        store,
        clock,
        lease,
        batch,
        frontier,
        backend,
    };
    assert_clock_error(
        fixture
            .store
            .claim_publication_owner("publisher:clock", /*lease_duration_ms*/ 100)
            .await,
    );
    assert_clock_error(
        fixture
            .store
            .prepare_publication_batch(&fixture.lease, /*maximum_intents*/ 1)
            .await,
    );
    assert_eq!(fixture.snapshot().await, before);
}
