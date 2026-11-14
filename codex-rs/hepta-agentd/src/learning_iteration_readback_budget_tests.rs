//! Actor deadline regressions use synthetic current attestations and paused
//! Tokio time. The work envelope still expires against the real host clock.

use pretty_assertions::assert_eq;

use super::*;

struct DelayedOwnerPorts {
    inner: Arc<CurrentEvidencePorts>,
    restore_delay: Duration,
    attestation_delay: Duration,
}

impl LearningIterationOwnerPortsV1 for DelayedOwnerPorts {
    fn restore<'a>(
        &'a self,
        request: &'a LearningIterationRequestV1,
    ) -> LearningIterationOwnerFutureV1<'a, Option<LearningIterationSnapshotV1>> {
        Box::pin(async move {
            tokio::time::sleep(self.restore_delay).await;
            self.inner.restore(request).await
        })
    }

    fn checkpoint<'a>(
        &'a self,
        expected: Digest32,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, Digest32> {
        self.inner.checkpoint(expected, snapshot)
    }

    fn execute_stage<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    ) -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1> {
        self.inner.execute_stage(snapshot, stage)
    }

    fn prepare_proposal<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1> {
        self.inner.prepare_proposal(snapshot)
    }

    fn receipt_attestation<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        receipt: &'a LearningIterationReceiptV1,
        now: u64,
    ) -> LearningIterationOwnerFutureV1<'a, SignedLearningEvidenceV1> {
        Box::pin(async move {
            tokio::time::sleep(self.attestation_delay).await;
            self.inner.receipt_attestation(snapshot, receipt, now).await
        })
    }
}

#[tokio::test]
async fn expired_learning_readback_allows_multiple_bounded_original_owner_reads() {
    let daemon = AgentdFixture::new();
    let original = CurrentEvidencePorts::new();
    let mut request = iteration_request(&daemon);
    request.envelope.expiry_unix_seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
        - 1;
    let snapshot = completed_snapshot(request, &original.inner, Decision::EvaluatedNoUpdate).await;
    install_checkpoint(&original.inner, &snapshot);
    let ports = Arc::new(DelayedOwnerPorts {
        inner: Arc::clone(&original),
        restore_delay: Duration::ZERO,
        // Each synthetic delay is below the owner's 500 ms exchange bound;
        // the eleven reads together exceed the expired work's old 1 s timeout.
        attestation_delay: Duration::from_millis(125),
    });
    let (handle, owner) = ok(learning_iteration_channel_v1(
        daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        original.inner.owners(),
        ports,
        original.inner.verifier.clone(),
        /*capacity*/ 1,
    ));
    let cancellation = CancellationToken::new();
    let state = daemon.state();
    tokio::time::pause();
    let worker = tokio::spawn(owner.run(state, cancellation.clone()));
    let started = tokio::time::Instant::now();
    let recovered = ok(handle.readback(snapshot.request.clone()).await);
    assert!(started.elapsed() > Duration::from_secs(1));
    assert_eq!(recovered, snapshot);
    assert_no_work_or_checkpoint(&original.inner, &snapshot);
    cancellation.cancel();
    ok(ok(worker.await));
}

#[tokio::test]
async fn stalled_learning_readback_exhausts_its_budget_without_repeating_or_writing() {
    let daemon = AgentdFixture::new();
    let original = CurrentEvidencePorts::new();
    let mut request = iteration_request(&daemon);
    request.envelope.expiry_unix_seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
        - 1;
    let snapshot = completed_snapshot(request, &original.inner, Decision::EvaluatedNoUpdate).await;
    install_checkpoint(&original.inner, &snapshot);
    let ports = Arc::new(DelayedOwnerPorts {
        inner: Arc::clone(&original),
        restore_delay: Duration::ZERO,
        attestation_delay: Duration::from_secs(60),
    });
    let (handle, owner) = ok(learning_iteration_channel_v1(
        daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        original.inner.owners(),
        ports,
        original.inner.verifier.clone(),
        /*capacity*/ 1,
    ));
    let cancellation = CancellationToken::new();
    let state = daemon.state();
    tokio::time::pause();
    let worker = tokio::spawn(owner.run(state, cancellation.clone()));
    let result = tokio::time::timeout(
        Duration::from_secs(31),
        handle.readback(snapshot.request.clone()),
    )
    .await
    .expect("the actor bounds reconciliation before its original owner returns");
    assert!(matches!(
        result,
        Err(LearningIterationRuntimeErrorV1::CommitUncertain)
    ));
    assert_no_work_or_checkpoint(&original.inner, &snapshot);
    cancellation.cancel();
    ok(ok(worker.await));
}

#[tokio::test]
async fn learning_submit_keeps_its_work_deadline_while_restoring_a_checkpoint() {
    let daemon = AgentdFixture::new();
    let original = CurrentEvidencePorts::new();
    let mut request = iteration_request(&daemon);
    request.envelope.expiry_unix_seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
        + 5;
    let snapshot = completed_snapshot(request, &original.inner, Decision::EvaluatedNoUpdate).await;
    install_checkpoint(&original.inner, &snapshot);
    let ports = Arc::new(DelayedOwnerPorts {
        inner: Arc::clone(&original),
        restore_delay: Duration::from_secs(10),
        attestation_delay: Duration::ZERO,
    });
    let (handle, owner) = ok(learning_iteration_channel_v1(
        daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        original.inner.owners(),
        ports,
        original.inner.verifier.clone(),
        /*capacity*/ 1,
    ));
    let cancellation = CancellationToken::new();
    let state = daemon.state();
    tokio::time::pause();
    let worker = tokio::spawn(owner.run(state, cancellation.clone()));
    let result = tokio::time::timeout(
        Duration::from_secs(6),
        handle.submit(snapshot.request.clone()),
    )
    .await
    .expect("submission retains its work timeout rather than the readback budget");
    assert!(matches!(
        result,
        Err(LearningIterationRuntimeErrorV1::CommitUncertain)
    ));
    assert_no_work_or_checkpoint(&original.inner, &snapshot);
    cancellation.cancel();
    ok(ok(worker.await));
}
