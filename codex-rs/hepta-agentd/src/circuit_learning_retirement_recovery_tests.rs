//! Retain the ACK/retirement crash boundary on real SQLite. These fixture
//! owners cannot execute or authenticate learning and grant no acceptance.

use pretty_assertions::assert_eq;
use sqlx::SqlitePool;

use super::*;

struct UnavailableLearningPorts {
    calls: AtomicUsize,
}

impl UnavailableLearningPorts {
    fn unavailable<T>(&self) -> LearningIterationOwnerFutureV1<'_, T> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Box::pin(async {
            Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                "offline fixture",
            ))
        })
    }
}

impl LearningIterationOwnerPortsV1 for UnavailableLearningPorts {
    fn restore<'a>(
        &'a self,
        _request: &'a LearningIterationRequestV1,
    ) -> LearningIterationOwnerFutureV1<'a, Option<LearningIterationSnapshotV1>> {
        self.unavailable()
    }
    fn checkpoint<'a>(
        &'a self,
        _expected: Digest32,
        _snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, Digest32> {
        self.unavailable()
    }
    fn execute_stage<'a>(
        &'a self,
        _snapshot: &'a LearningIterationSnapshotV1,
        _stage: LearningIterationStageV1,
    ) -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1> {
        self.unavailable()
    }
    fn prepare_proposal<'a>(
        &'a self,
        _snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1> {
        self.unavailable()
    }
    fn receipt_attestation<'a>(
        &'a self,
        _snapshot: &'a LearningIterationSnapshotV1,
        _receipt: &'a LearningIterationReceiptV1,
        _now: u64,
    ) -> LearningIterationOwnerFutureV1<'a, SignedLearningEvidenceV1> {
        self.unavailable()
    }
}

async fn acknowledged_before_retirement(
    daemon: &AgentdFixture,
    original: &CurrentEvidencePorts,
) -> (
    AutomationStore,
    LearningIterationRequestV1,
    CircuitLearningDeliveryV1,
) {
    let (store, request) = completed_circuit_named(daemon, "ack-crash-window").await;
    let snapshot = completed_snapshot(
        request.clone(),
        &original.inner,
        Decision::EvaluatedNoUpdate,
    )
    .await;
    let initial = ok(LearningIterationCoordinatorV1::new(
        request.clone(),
        original.inner.owners(),
    ));
    let request_digest = ok(Sha256Digest::parse(
        initial.snapshot().head_digest.to_string(),
    ));
    let intent = ok(store
        .circuit_learning_delivery(request.source_run_id.as_str())
        .await)
    .unwrap()
    .intent;
    assert!(ok(store
        .claim_circuit_learning(&intent, &request_digest)
        .await));
    ok(store
        .acknowledge_circuit_learning(
            &intent,
            &request_digest,
            &ok(Sha256Digest::parse(snapshot.head_digest.to_string())),
        )
        .await);
    let acknowledged = ok(store
        .circuit_learning_delivery(request.source_run_id.as_str())
        .await)
    .unwrap();
    // Drop the only database owner before reopening the crash-boundary bytes.
    store.close().await;
    drop(store);
    let reopened = ok(AutomationStore::open(&daemon.identity.layout).await);
    assert_eq!(
        ok(reopened
            .circuit_learning_delivery(request.source_run_id.as_str())
            .await),
        Some(acknowledged.clone())
    );
    (reopened, request, acknowledged)
}

async fn inspect(store: &AutomationStore) -> SqlitePool {
    let sqlite_home = ok(codex_utils_absolute_path::AbsolutePathBuf::try_from(
        store
            .path()
            .parent()
            .expect("the durable store has a parent directory")
            .to_path_buf(),
    ));
    ok(codex_state::SqliteConfig::new_for_testing(sqlite_home)
        .open_read_only_pool(store.path())
        .await)
}

async fn retired(pool: &SqlitePool, request: &LearningIterationRequestV1) -> i64 {
    ok(sqlx::query_scalar(
        "SELECT retired FROM circuit_learning_outbox_v1 WHERE owner_agent_id = ? AND run_id = ?",
    )
    .bind(request.agent_id.as_str())
    .bind(request.source_run_id.as_str())
    .fetch_one(pool)
    .await)
}

#[tokio::test]
async fn cold_ack_cleanup_releases_slot_without_contacting_unavailable_learning_owners() {
    let daemon = AgentdFixture::new();
    let original = CurrentEvidencePorts::new();
    let (store, request, acknowledged) = acknowledged_before_retirement(&daemon, &original).await;
    let inspection = inspect(&store).await;
    assert_eq!(retired(&inspection, &request).await, 0);
    let write_attempt = sqlx::query(
        "UPDATE circuit_learning_outbox_v1 SET retired = 1 WHERE owner_agent_id = ? AND run_id = ?",
    )
    .bind(request.agent_id.as_str())
    .bind(request.source_run_id.as_str())
    .execute(&inspection)
    .await;
    assert!(
        write_attempt.is_err(),
        "original post-recovery inspection must not write the outbox"
    );
    assert_eq!(retired(&inspection, &request).await, 0);
    let ports = Arc::new(UnavailableLearningPorts {
        calls: AtomicUsize::new(0),
    });
    let (state, cognitive) = admitted_state(&daemon).await;
    let (handle, bootstrap) = ok(learning_iteration_channel_v1(
        daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        original.inner.owners(),
        ports.clone(),
        original.inner.verifier.clone(),
        /*capacity*/ 1,
    ));
    let mut bootstrap = ok(bootstrap.with_circuit_learning_delivery(request.clone()));
    let delivery = bootstrap.take_circuit_delivery().unwrap();
    drop(handle);
    let cancellation = CancellationToken::new();
    let actor = tokio::spawn(bootstrap.run(state.clone(), cancellation.clone()));
    let delivery = tokio::spawn(delivery.run(store.clone(), state, cancellation.clone()));
    tokio::time::timeout(Duration::from_secs(5), async {
        while retired(&inspection, &request).await == 0 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("exact historical ACK retired without an owner call");
    assert_eq!(
        ok(store
            .circuit_learning_delivery(request.source_run_id.as_str())
            .await),
        Some(acknowledged)
    );
    assert_eq!(ports.calls.load(Ordering::SeqCst), 0);
    assert!(!delivery.is_finished());
    cancellation.cancel();
    ok(ok(tokio::time::timeout(Duration::from_secs(5), delivery)
        .await
        .unwrap()));
    ok(ok(tokio::time::timeout(Duration::from_secs(5), actor)
        .await
        .unwrap()));
    inspection.close().await;
    cognitive.close().await;
    store.close().await;
}

#[tokio::test]
async fn ack_cleanup_refuses_changed_request_owners_and_stale_ack_without_mutation() {
    let daemon = AgentdFixture::new();
    let original = CurrentEvidencePorts::new();
    let owners = original.inner.owners();
    let (store, request, acknowledged) = acknowledged_before_retirement(&daemon, &original).await;
    let inspection = inspect(&store).await;
    let mut changed = vec![request.clone(); 5];
    changed[0].source_run_id = id("other-source");
    changed[1].operation_id = id("other-operation");
    changed[2].completed_task_receipt = digest("other-receipt");
    changed[3].envelope.objective_digest = digest("other-objective");
    changed[4].budget.maximum_training_steps += 1;
    for changed in changed {
        assert!(matches!(
            crate::circuit_learning_delivery::retire_acknowledged_delivery(
                &store,
                &changed,
                &owners,
                &acknowledged,
            )
            .await,
            Err(LearningIterationRuntimeErrorV1::WrongScope)
        ));
    }
    let mut changed_owners = owners.clone();
    changed_owners.trainer = id("other-trainer");
    assert!(matches!(
        crate::circuit_learning_delivery::retire_acknowledged_delivery(
            &store,
            &request,
            &changed_owners,
            &acknowledged,
        )
        .await,
        Err(LearningIterationRuntimeErrorV1::WrongScope)
    ));
    let mut stale = acknowledged.clone();
    stale.acknowledged_head = Some(ok(Sha256Digest::parse(digest("other-head").to_string())));
    assert!(matches!(
        crate::circuit_learning_delivery::retire_acknowledged_delivery(
            &store, &request, &owners, &stale,
        )
        .await,
        Err(LearningIterationRuntimeErrorV1::CommitUncertain)
    ));
    assert_eq!(retired(&inspection, &request).await, 0);
    assert_eq!(
        ok(store
            .circuit_learning_delivery(request.source_run_id.as_str())
            .await),
        Some(acknowledged)
    );
    inspection.close().await;
    store.close().await;
}
