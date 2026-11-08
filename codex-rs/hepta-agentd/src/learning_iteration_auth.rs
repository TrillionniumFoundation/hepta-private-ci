//! Verify complete owner observations with the existing learning trust owner.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;

use crate::LearningIterationOwnerPortsV1;
use crate::LearningIterationRuntimeErrorV1;

pub(super) async fn authenticate_restored_iteration_v1(
    ports: &dyn LearningIterationOwnerPortsV1,
    verifier: &LearningEvidenceVerifierV1,
    restored: &LearningIterationCoordinatorV1,
    now: u64,
) -> Result<(), LearningIterationRuntimeErrorV1> {
    let snapshot = restored.snapshot();
    let historical_only = restored.next_stage().is_none();
    let mut replay =
        LearningIterationCoordinatorV1::new(snapshot.request.clone(), snapshot.owners.clone())?;
    for receipt in &snapshot.receipts {
        if receipt.observed_unix_seconds > now {
            return Err(LearningIterationRuntimeErrorV1::Evidence(
                SignedEvidenceError::ContextMismatch,
            ));
        }
        // Proposal belongs to its existing anchored owner, not an evidence
        // signer. Restore must authenticate that owner's independent head.
        if receipt.observation.stage() != LearningIterationStageV1::Proposal {
            authenticate_receipt(ports, verifier, &replay, receipt, now, historical_only).await?;
        }
        replay.record(receipt.clone(), receipt.observed_unix_seconds)?;
    }
    Ok(())
}

pub(super) async fn authenticate_iteration_receipt_v1(
    ports: &dyn LearningIterationOwnerPortsV1,
    verifier: &LearningEvidenceVerifierV1,
    coordinator: &LearningIterationCoordinatorV1,
    receipt: &LearningIterationReceiptV1,
    now: u64,
) -> Result<(), LearningIterationRuntimeErrorV1> {
    authenticate_receipt(
        ports,
        verifier,
        coordinator,
        receipt,
        now,
        /*historical_only*/ false,
    )
    .await
}

async fn authenticate_receipt(
    ports: &dyn LearningIterationOwnerPortsV1,
    verifier: &LearningEvidenceVerifierV1,
    coordinator: &LearningIterationCoordinatorV1,
    receipt: &LearningIterationReceiptV1,
    now: u64,
    historical_only: bool,
) -> Result<(), LearningIterationRuntimeErrorV1> {
    let snapshot = coordinator.snapshot();
    // The owner always receives real current time, including historical reads.
    let mut attestations = vec![(
        receipt,
        ports.receipt_attestation(snapshot, receipt, now).await?,
    )];
    let independent_stages: &[usize] = match receipt.observation.stage() {
        LearningIterationStageV1::Evaluation => &[2],
        LearningIterationStageV1::Selection => &[2, 3],
        LearningIterationStageV1::NextUse => &[2, 5],
        LearningIterationStageV1::Experience
        | LearningIterationStageV1::Dataset
        | LearningIterationStageV1::Training
        | LearningIterationStageV1::Proposal => &[],
    };
    for index in independent_stages {
        let earlier =
            snapshot
                .receipts
                .get(*index)
                .ok_or(LearningIterationRuntimeErrorV1::Evidence(
                    SignedEvidenceError::ContextMismatch,
                ))?;
        attestations.push((
            earlier,
            ports.receipt_attestation(snapshot, earlier, now).await?,
        ));
    }
    let verification_time = if historical_only {
        // This proves a common historical validity window, not the actual
        // admission time or current permission. No Verified evidence escapes.
        let historical = attestations
            .iter()
            .fold(receipt.observed_unix_seconds, |at, (_, signed)| {
                at.max(signed.issued_at)
            });
        if historical > now || historical >= snapshot.request.envelope.expiry_unix_seconds {
            return Err(LearningIterationRuntimeErrorV1::Evidence(
                SignedEvidenceError::ValidityWindow,
            ));
        }
        historical
    } else {
        now
    };
    let current = verify_receipt(
        verifier,
        snapshot,
        receipt,
        &attestations[0].1,
        verification_time,
    )?;
    for (earlier, signature) in attestations.iter().skip(1) {
        let prior = verify_receipt(verifier, snapshot, earlier, signature, verification_time)?;
        verify_signed_actor_separation(&prior, &current, verification_time)
            .map_err(LearningIterationRuntimeErrorV1::Evidence)?;
    }
    Ok(())
}

fn verify_receipt(
    verifier: &LearningEvidenceVerifierV1,
    snapshot: &LearningIterationSnapshotV1,
    receipt: &LearningIterationReceiptV1,
    signature: &SignedLearningEvidenceV1,
    verification_time: u64,
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
    let verified = verifier
        .verify(role, signature, &payload, verification_time)
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
