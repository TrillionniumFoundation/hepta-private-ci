//! Verify complete owner observations with the existing learning trust owner.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;

use crate::LearningIterationOwnerPortsV1;
use crate::LearningIterationRuntimeErrorV1;

pub(super) async fn authenticate_iteration_receipt_v1(
    ports: &dyn LearningIterationOwnerPortsV1,
    verifier: &LearningEvidenceVerifierV1,
    coordinator: &LearningIterationCoordinatorV1,
    receipt: &LearningIterationReceiptV1,
    now: u64,
) -> Result<(), LearningIterationRuntimeErrorV1> {
    let snapshot = coordinator.snapshot();
    let current = verify_receipt(ports, verifier, snapshot, receipt, now).await?;
    let independent_stages: &[usize] = match receipt.observation.stage() {
        LearningIterationStageV1::Evaluation => &[2],
        LearningIterationStageV1::Selection => &[2, 3],
        LearningIterationStageV1::NextUse => &[2, 5],
        LearningIterationStageV1::Experience | LearningIterationStageV1::Dataset
        | LearningIterationStageV1::Training | LearningIterationStageV1::Proposal => &[],
    };
    for index in independent_stages {
        let earlier = snapshot.receipts.get(*index).ok_or(
            LearningIterationRuntimeErrorV1::Evidence(SignedEvidenceError::ContextMismatch),
        )?;
        let prior = verify_receipt(ports, verifier, snapshot, earlier, now).await?;
        verify_signed_actor_separation(&prior, &current, now)
            .map_err(LearningIterationRuntimeErrorV1::Evidence)?;
    }
    Ok(())
}

async fn verify_receipt(
    ports: &dyn LearningIterationOwnerPortsV1,
    verifier: &LearningEvidenceVerifierV1,
    snapshot: &LearningIterationSnapshotV1,
    receipt: &LearningIterationReceiptV1,
    now: u64,
) -> Result<VerifiedLearningEvidenceV1, LearningIterationRuntimeErrorV1> {
    let role = match receipt.observation.stage() {
        LearningIterationStageV1::Training => LearningEvidenceRoleV1::Generator,
        LearningIterationStageV1::Evaluation => LearningEvidenceRoleV1::Evaluator,
        LearningIterationStageV1::Selection => LearningEvidenceRoleV1::Selector,
        LearningIterationStageV1::Experience | LearningIterationStageV1::Dataset
        | LearningIterationStageV1::NextUse => LearningEvidenceRoleV1::Observer,
        LearningIterationStageV1::Proposal =>
            return Err(LearningIterationRuntimeErrorV1::Evidence(SignedEvidenceError::RoleMismatch)),
    };
    let payload = learning_iteration_receipt_signing_bytes_v1(receipt)?;
    let signature = ports.receipt_attestation(snapshot, receipt, now).await?;
    let verified = verifier.verify(role, &signature, &payload, now)
        .map_err(LearningIterationRuntimeErrorV1::Evidence)?;
    if verified.principal().principal_id != receipt.actor_id
        || &receipt.actor_id != snapshot.owners.owner(receipt.observation.stage())
        || verified.trust_digest() != snapshot.owners.evidence_trust_digest
        || verified.objective_digest() != snapshot.request.envelope.objective_digest
    {
        return Err(LearningIterationRuntimeErrorV1::Evidence(SignedEvidenceError::ContextMismatch));
    }
    Ok(verified)
}
