//! Verify complete owner observations with the existing learning trust owner.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;

use crate::AgentdState;
use crate::LearningIterationOwnerPortsV1;
use crate::LearningIterationRuntimeErrorV1;
use crate::learning_iteration::require_ready;

#[path = "learning_iteration_receipt_validation.rs"]
mod validation;
pub(crate) use validation::OriginalReceiptVerificationV1;
pub(crate) use validation::independent_receipt_stages;

/// Protected checkpoint data does not restore its separate current signatures.
/// Replay each original predecessor locally, but read evidence against the
/// complete restored CURRENT. Passing a historical prefix to the owner would
/// replace the checkpoint head it must reconcile. Proposal has no learning-
/// signature role: the host still authenticates its original durable proposal
/// and independent anchor. This neither executes nor checkpoints a stage.
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
            authenticate_iteration_receipt_v1(state, ports, verifier, coordinator, receipt, clock)
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
    // A later publication/use cannot outlive the explicit local decision's
    // current authorization. Re-read its original signed evidence as well.
    if let Some(decision) = snapshot.receipts.iter().find(|earlier| {
        matches!(
            earlier.observation,
            codex_hepta_learning_artifacts::LearningIterationObservationV1::LocalDecisionV2(_)
        )
    }) {
        verify_receipt(ports, verifier, snapshot, decision, clock).await?;
    }
    let independent_stages = independent_receipt_stages(snapshot, receipt);
    for stage in independent_stages {
        let earlier = snapshot
            .receipts
            .iter()
            .rev()
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
    let verification = OriginalReceiptVerificationV1::new(verifier, snapshot, receipt)?;
    let signature = ports
        .receipt_attestation(snapshot, receipt, clock()?)
        .await?;
    verification.verify(&signature, clock()?)
}
