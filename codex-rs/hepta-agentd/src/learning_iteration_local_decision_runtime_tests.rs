//! Original runtime/signature controls with explicit synthetic stage owners.
//! Actual CURRENT/parent-use files are tested in neuron_generation_local_decision_tests.

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningLocalDecisionV2;
use codex_hepta_learning_artifacts::LearningLocalDispositionV2;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use crate::learning_iteration_channel_scoped_v2;
use super::*;
use pretty_assertions::assert_eq;

struct LocalPorts {
    original: Arc<IterationPorts>,
    cuts: Vec<LearningIterationSnapshotV1>,
    lose_decision_ack: AtomicBool,
    invalidate_decision_after_receipts: Option<usize>,
}

impl LearningIterationOwnerPortsV1 for LocalPorts {
    fn frozen_scope_binding(&self) -> Option<Digest32> { self.original.frozen_scope_binding() }
    fn restore<'a>(&'a self, request: &'a LearningIterationRequestV1)
        -> LearningIterationOwnerFutureV1<'a, Option<LearningIterationSnapshotV1>> {
        self.original.restore(request)
    }
    fn checkpoint<'a>(&'a self, expected: Digest32, next: &'a LearningIterationSnapshotV1)
        -> LearningIterationOwnerFutureV1<'a, Digest32> {
        Box::pin(async move {
            let head = self.original.checkpoint(expected, next).await?;
            if Some(next.receipts.len()) == self.invalidate_decision_after_receipts {
                *ok(self.original.corrupt_stage.lock()) = Some(LearningIterationStageV1::Selection);
            }
            if next.receipts.len() == 6 && self.lose_decision_ack.swap(false, Ordering::SeqCst) {
                return Err(LearningIterationRuntimeErrorV1::CommitUncertain);
            }
            Ok(head)
        })
    }
    fn execute_stage<'a>(&'a self, snapshot: &'a LearningIterationSnapshotV1, stage: LearningIterationStageV1)
        -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1> {
        Box::pin(async move {
            ok(self.original.executed.lock()).push(stage);
            self.cuts.iter().filter_map(|cut| cut.receipts.last())
                .find(|receipt| receipt.predecessor == snapshot.head_digest && receipt.observation.stage() == stage)
                .cloned().ok_or(LearningIterationRuntimeErrorV1::OwnerUnavailable("original local stage"))
        })
    }
    fn prepare_proposal<'a>(&'a self, snapshot: &'a LearningIterationSnapshotV1)
        -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1> {
        self.original.prepare_proposal(snapshot)
    }
    fn receipt_attestation<'a>(&'a self, snapshot: &'a LearningIterationSnapshotV1,
        receipt: &'a LearningIterationReceiptV1, now: u64)
        -> LearningIterationOwnerFutureV1<'a, SignedLearningEvidenceV1> {
        self.original.receipt_attestation(snapshot, receipt, now)
    }
}

async fn cuts(request: LearningIterationRequestV1, ports: &IterationPorts) -> Vec<LearningIterationSnapshotV1> {
    let complete = completed_snapshot(request, ports, Decision::Update).await;
    let mut prefix = complete.clone();
    prefix.receipts.truncate(5);
    prefix.head_digest = complete.receipts[5].predecessor;
    let mut c = ok(LearningIterationCoordinatorV1::from_snapshot(prefix));
    let mut cuts = vec![c.snapshot().clone()];
    let retained_bundle = ok(c.snapshot().request.selected_bundle.digest());
    let local = LearningIterationObservationV1::LocalDecisionV2(LearningLocalDecisionV2 {
        proposal_head: c.snapshot().head_digest,
        candidate_bundle: ok(c.candidate().unwrap().digest()),
        selected_bundle: retained_bundle,
        policy_digest: digest("host-local-policy"), reason_digest: digest("host-local-reason"),
        disposition: LearningLocalDispositionV2::RetainParent,
    });
    record_observation(&mut c, local);
    cuts.push(c.snapshot().clone());
    record_observation(&mut c, LearningIterationObservationV1::Selection {
        candidate_bundle: retained_bundle, selection_digest: digest("original-parent-selection"),
    });
    cuts.push(c.snapshot().clone());
    let request = &c.snapshot().request;
    let partition = CellStatePartitionV1 {
        principal_id: request.principal_id.clone(), agent_id: request.agent_id.clone(),
        cell_id: request.cell_id.clone(), run_id: id("run:local-retained-next"),
    };
    record_observation(&mut c, LearningIterationObservationV1::RetainedModelNextUse {
        retained_bundle, state_partition: partition, checkpoint_digest: digest("fresh-parent-state"),
        selection_digest: digest("original-parent-selection"), committed_step_receipt: digest("fresh-parent-step"),
        task_owner_publication: digest("original-parent-task-owner"),
    });
    cuts.push(c.snapshot().clone());
    cuts
}

#[tokio::test]
async fn scoped_runtime_persists_local_decision_before_selection_and_recovers_lost_ack() {
    let daemon = AgentdFixture::new();
    let request = iteration_request(&daemon);
    let mut original = recovery_ports(Decision::Update, Trust::Independent);
    let scope = ok(FrozenLearningScopeV2::freeze(&request, &original.owners(),
        LearningUpdateScopeV2::Cell, digest("test-rule")));
    original.scope_binding = Some(scope.binding());
    let cuts = cuts(request.clone(), &original).await;
    install_checkpoint(&original, &cuts[0]);
    let ports = Arc::new(LocalPorts { original: Arc::new(original), cuts: cuts.clone(),
        lose_decision_ack: AtomicBool::new(true), invalidate_decision_after_receipts: None });
    let (_, runtime) = ok(learning_iteration_channel_scoped_v2(daemon.identity.agent_id.clone(),
        1, ports.original.owners(), ports.clone(), ports.original.verifier.clone(), 2, scope));
    assert!(matches!(runtime.process(&daemon.state(), request.clone(), || Ok(60)).await,
        Err(LearningIterationRuntimeErrorV1::CommitUncertain)));
    assert_eq!(ok(ports.original.checkpoint.lock()).as_ref(), Some(&cuts[1]));
    assert_eq!(*ok(ports.original.executed.lock()), vec![LearningIterationStageV1::Selection]);
    let completed = ok(runtime.process(&daemon.state(), request.clone(), || Ok(60)).await);
    assert_eq!(completed, cuts[3]);
    assert_eq!(*ok(ports.original.executed.lock()), vec![LearningIterationStageV1::Selection,
        LearningIterationStageV1::Selection, LearningIterationStageV1::NextUse]);
    install_checkpoint(&ports.original, &completed);
    assert_eq!(ok(runtime.process_readback(&daemon.state(), request, || Ok(60)).await), completed);
    assert_no_work_or_checkpoint(&ports.original, &completed);
}

#[tokio::test]
async fn invalidated_local_evidence_blocks_publication_before_owner_execution() {
    for cut in [6, 7] {
    let daemon = AgentdFixture::new();
    let request = iteration_request(&daemon);
    let mut original = recovery_ports(Decision::Update, Trust::Independent);
    let scope = ok(FrozenLearningScopeV2::freeze(&request, &original.owners(),
        LearningUpdateScopeV2::Cell, digest("test-rule")));
    original.scope_binding = Some(scope.binding());
    let cuts = cuts(request.clone(), &original).await;
    install_checkpoint(&original, &cuts[0]);
    let ports = Arc::new(LocalPorts { original: Arc::new(original), cuts: cuts.clone(),
        lose_decision_ack: AtomicBool::new(false), invalidate_decision_after_receipts: Some(cut) });
    let (_, runtime) = ok(learning_iteration_channel_scoped_v2(daemon.identity.agent_id.clone(),
        1, ports.original.owners(), ports.clone(), ports.original.verifier.clone(), 2, scope));
    assert!(matches!(runtime.process(&daemon.state(), request, || Ok(60)).await,
        Err(LearningIterationRuntimeErrorV1::Evidence(_))));
    assert_eq!(ok(ports.original.checkpoint.lock()).as_ref(), Some(&cuts[cut - 5]));
    assert_eq!(*ok(ports.original.executed.lock()), vec![LearningIterationStageV1::Selection; cut - 5]);
    }
}

#[tokio::test]
async fn local_decision_cannot_restore_with_legacy_owner_or_invalid_selector_authority() {
    for fault in ["legacy", "selector-controller", "signature", "none"] {
        let daemon = AgentdFixture::new();
        let request = iteration_request(&daemon);
        let mut original = recovery_ports(Decision::Update, if fault == "selector-controller" {
            Trust::SharedSelectorController
        } else { Trust::Independent });
        let scope = ok(FrozenLearningScopeV2::freeze(&request, &original.owners(),
            LearningUpdateScopeV2::Cell, digest("test-rule")));
        if fault != "legacy" { original.scope_binding = Some(scope.binding()); }
        let complete = cuts(request.clone(), &original).await.pop().unwrap();
        install_checkpoint(&original, &complete);
        if fault == "signature" { *ok(original.corrupt_stage.lock()) = Some(LearningIterationStageV1::Selection); }
        let original = Arc::new(original);
        let runtime = if fault == "legacy" { runtime(&daemon, &original) } else {
            ok(learning_iteration_channel_scoped_v2(daemon.identity.agent_id.clone(), 1,
                original.owners(), original.clone(), original.verifier.clone(), 2, scope)).1
        };
        let result = runtime.process_readback(&daemon.state(), request, || Ok(60)).await;
        if fault == "none" { assert_eq!(ok(result), complete); }
        else { assert!(result.is_err()); }
        if fault == "legacy" { assert!(ok(original.attested.lock()).is_empty()); }
        assert_no_work_or_checkpoint(&original, &complete);
    }
}
