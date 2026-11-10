//! The owner independently pins CURRENT while the ordinary worker recovers
//! historical receipts. Signatures and model observations remain test fixtures.

use pretty_assertions::assert_eq;

use super::*;

struct CurrentHeadPorts {
    inner: Arc<IterationPorts>,
    current: LearningIterationSnapshotV1,
    observed: Mutex<Vec<LearningIterationSnapshotV1>>,
}

impl LearningIterationOwnerPortsV1 for CurrentHeadPorts {
    fn restore<'a>(
        &'a self,
        request: &'a LearningIterationRequestV1,
    ) -> LearningIterationOwnerFutureV1<'a, Option<LearningIterationSnapshotV1>> {
        self.inner.restore(request)
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
            ok(self.observed.lock()).push(snapshot.clone());
            // The evidence owner checks its independently retained CURRENT,
            // not merely the caller's immutable operation or receipt digest.
            if snapshot != &self.current {
                return Err(LearningIterationRuntimeErrorV1::CommitUncertain);
            }
            self.inner.receipt_attestation(snapshot, receipt, now).await
        })
    }
}

fn current_runtime(
    daemon: &AgentdFixture,
    ports: &Arc<CurrentHeadPorts>,
) -> crate::LearningIterationRuntimeBootstrapV1 {
    let (_, owner) = ok(learning_iteration_channel_v1(
        daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        ports.inner.owners(),
        ports.clone(),
        ports.inner.verifier.clone(),
        /*capacity*/ 2,
    ));
    owner
}

#[tokio::test]
async fn recovery_reads_each_historical_signature_against_original_current() {
    for decision in [
        Decision::EvaluatedNoUpdate,
        Decision::ProposedNoUpdate,
        Decision::Update,
    ] {
        let daemon = AgentdFixture::new();
        let inner = Arc::new(recovery_ports(decision, Trust::Independent));
        let completed = completed_snapshot(iteration_request(&daemon), &inner, decision).await;
        let mut prefix = ok(LearningIterationCoordinatorV1::new(
            completed.request.clone(),
            completed.owners.clone(),
        ));
        for receipt in &completed.receipts {
            ok(prefix.record(receipt.clone(), receipt.observed_unix_seconds));
            let snapshot = prefix.snapshot().clone();
            install_checkpoint(&inner, &snapshot);
            let ports = Arc::new(CurrentHeadPorts {
                inner: Arc::clone(&inner),
                current: snapshot.clone(),
                observed: Mutex::default(),
            });
            let recovered = ok(current_runtime(&daemon, &ports)
                .process_readback(&daemon.state(), snapshot.request.clone(), || Ok(60))
                .await);
            assert_eq!(recovered, snapshot);
            let observed = ok(ports.observed.lock());
            assert!(!observed.is_empty());
            assert_eq!(*observed, vec![snapshot.clone(); observed.len()]);
            assert_no_work_or_checkpoint(&inner, &snapshot);
        }
    }
}

#[tokio::test]
async fn completed_resume_uses_original_current_for_updated_and_retained_bundles() {
    for decision in [
        Decision::EvaluatedNoUpdate,
        Decision::ProposedNoUpdate,
        Decision::Update,
    ] {
        let daemon = AgentdFixture::new();
        let inner = Arc::new(recovery_ports(decision, Trust::Independent));
        let mut request = iteration_request(&daemon);
        request.envelope.expiry_unix_seconds = 55;
        let snapshot = completed_snapshot(request, &inner, decision).await;
        install_checkpoint(&inner, &snapshot);
        let ports = Arc::new(CurrentHeadPorts {
            inner: Arc::clone(&inner),
            current: snapshot.clone(),
            observed: Mutex::default(),
        });
        let recovered = ok(current_runtime(&daemon, &ports)
            .process(&daemon.state(), snapshot.request.clone(), || Ok(60))
            .await);
        assert_eq!(recovered, snapshot);
        let observed = ok(ports.observed.lock());
        assert!(!observed.is_empty());
        assert_eq!(*observed, vec![snapshot.clone(); observed.len()]);
        assert_no_work_or_checkpoint(&inner, &snapshot);
    }
}

#[tokio::test]
async fn recovery_refuses_a_checkpoint_behind_the_original_evidence_owner() {
    let daemon = AgentdFixture::new();
    let decision = Decision::EvaluatedNoUpdate;
    let inner = Arc::new(recovery_ports(decision, Trust::Independent));
    let completed = completed_snapshot(iteration_request(&daemon), &inner, decision).await;
    let mut prefix = ok(LearningIterationCoordinatorV1::new(
        completed.request.clone(),
        completed.owners.clone(),
    ));
    for receipt in completed.receipts.iter().take(3) {
        ok(prefix.record(receipt.clone(), receipt.observed_unix_seconds));
    }
    let stale = prefix.snapshot().clone();
    install_checkpoint(&inner, &stale);
    let ports = Arc::new(CurrentHeadPorts {
        inner: Arc::clone(&inner),
        current: completed,
        observed: Mutex::default(),
    });
    assert!(matches!(
        current_runtime(&daemon, &ports)
            .process_readback(&daemon.state(), stale.request.clone(), || Ok(60))
            .await,
        Err(LearningIterationRuntimeErrorV1::CommitUncertain)
    ));
    assert_eq!(*ok(ports.observed.lock()), vec![stale.clone()]);
    assert!(ok(inner.attested.lock()).is_empty());
    assert_no_work_or_checkpoint(&inner, &stale);
}
