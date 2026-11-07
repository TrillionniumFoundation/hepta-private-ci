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

use crate::AgentdState;
use crate::LearningIterationOwnerPortsV1;
use crate::LearningIterationRuntimeErrorV1;
use crate::learning_iteration::require_ready;

/// Protected checkpoint data does not restore its separate current signatures.
/// Rebuild each original predecessor context without executing or checkpointing
/// a stage. Proposal has no learning-signature role: the host's restore contract
/// still authenticates its original durable proposal and independent anchor.
pub(super) async fn authenticate_restored_iteration_v1(
    state: &AgentdState,
    ports: &dyn LearningIterationOwnerPortsV1,
    verifier: &LearningEvidenceVerifierV1,
    coordinator: &LearningIterationCoordinatorV1,
    clock: &(impl Fn() -> Result<u64, LearningIterationRuntimeErrorV1> + Send + Sync),
) -> Result<(), LearningIterationRuntimeErrorV1> {
    let snapshot = coordinator.snapshot();
    let mut predecessor =
        LearningIterationCoordinatorV1::new(snapshot.request.clone(), snapshot.owners.clone())?;
    for receipt in &snapshot.receipts {
        if receipt.observation.stage() != LearningIterationStageV1::Proposal {
            authenticate_iteration_receipt_v1(state, ports, verifier, &predecessor, receipt, clock)
                .await?;
        }
        // Structural replay uses the original observation time. A completed
        // iteration can be read after its work deadline if current evidence is
        // still valid; this never renews that deadline or authorizes new work.
        predecessor.record(receipt.clone(), receipt.observed_unix_seconds)?;
    }
    Ok(())
}

pub(super) async fn authenticate_iteration_receipt_v1(
    state: &AgentdState,
    ports: &dyn LearningIterationOwnerPortsV1,
    verifier: &LearningEvidenceVerifierV1,
    coordinator: &LearningIterationCoordinatorV1,
    receipt: &LearningIterationReceiptV1,
    clock: &(impl Fn() -> Result<u64, LearningIterationRuntimeErrorV1> + Send + Sync),
) -> Result<(), LearningIterationRuntimeErrorV1> {
    let current_time = || {
        require_ready(state)?;
        clock()
    };
    authenticate_iteration_receipt_at_clock_v1(ports, verifier, coordinator, receipt, &current_time)
        .await
}

async fn authenticate_iteration_receipt_at_clock_v1(
    ports: &dyn LearningIterationOwnerPortsV1,
    verifier: &LearningEvidenceVerifierV1,
    coordinator: &LearningIterationCoordinatorV1,
    receipt: &LearningIterationReceiptV1,
    clock: &(impl Fn() -> Result<u64, LearningIterationRuntimeErrorV1> + Send + Sync),
) -> Result<(), LearningIterationRuntimeErrorV1> {
    let snapshot = coordinator.snapshot();
    let current = verify_receipt(ports, verifier, snapshot, receipt, clock).await?;
    let independent_stages: &[LearningIterationStageV1] = match receipt.observation.stage() {
        LearningIterationStageV1::Evaluation => &[LearningIterationStageV1::Training],
        LearningIterationStageV1::Selection => &[
            LearningIterationStageV1::Training,
            LearningIterationStageV1::Evaluation,
        ],
        LearningIterationStageV1::NextUse => &[
            LearningIterationStageV1::Training,
            LearningIterationStageV1::Selection,
        ],
        LearningIterationStageV1::Experience
        | LearningIterationStageV1::Dataset
        | LearningIterationStageV1::Training
        | LearningIterationStageV1::Proposal => &[],
    };
    for stage in independent_stages {
        let earlier = snapshot
            .receipts
            .iter()
            .find(|earlier| earlier.observation.stage() == *stage)
            .ok_or(LearningIterationRuntimeErrorV1::Evidence(
                SignedEvidenceError::ContextMismatch,
            ))?;
        let prior = verify_receipt(ports, verifier, snapshot, earlier, clock).await?;
        verify_signed_actor_separation(&prior, &current, clock()?)
            .map_err(LearningIterationRuntimeErrorV1::Evidence)?;
    }
    Ok(())
}

async fn verify_receipt(
    ports: &dyn LearningIterationOwnerPortsV1,
    verifier: &LearningEvidenceVerifierV1,
    snapshot: &LearningIterationSnapshotV1,
    receipt: &LearningIterationReceiptV1,
    clock: &(impl Fn() -> Result<u64, LearningIterationRuntimeErrorV1> + Send + Sync),
) -> Result<VerifiedLearningEvidenceV1, LearningIterationRuntimeErrorV1> {
    let role = match receipt.observation.stage() {
        LearningIterationStageV1::Training => LearningEvidenceRoleV1::Generator,
        LearningIterationStageV1::Evaluation => LearningEvidenceRoleV1::Evaluator,
        LearningIterationStageV1::Selection => LearningEvidenceRoleV1::Selector,
        LearningIterationStageV1::Experience
        | LearningIterationStageV1::Dataset
        | LearningIterationStageV1::NextUse => LearningEvidenceRoleV1::Observer,
        LearningIterationStageV1::Proposal => {
            return Err(LearningIterationRuntimeErrorV1::Evidence(
                SignedEvidenceError::RoleMismatch,
            ));
        }
    };
    let payload = learning_iteration_receipt_signing_bytes_v1(receipt)?;
    let signature = ports
        .receipt_attestation(snapshot, receipt, clock()?)
        .await?;
    let now = clock()?;
    let verified = verifier
        .verify(role, &signature, &payload, now)
        .map_err(LearningIterationRuntimeErrorV1::Evidence)?;
    if verified.principal().principal_id != receipt.actor_id
        || &receipt.actor_id != snapshot.owners.owner(receipt.observation.stage())
        || verified.trust_digest() != snapshot.owners.evidence_trust_digest
        || verified.objective_digest() != snapshot.request.envelope.objective_digest
    {
        return Err(LearningIterationRuntimeErrorV1::Evidence(
            SignedEvidenceError::ContextMismatch,
        ));
    }
    Ok(verified)
}
