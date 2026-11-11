//! Current original role evidence at the resident coordinator and consumer.
//! This authenticates observations; it neither dispatches nor re-signs them.

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use std::sync::Arc;
use tokio_util::sync::CancellationToken;

use super::gate::ResidentRegisteredStateV3;
use super::profile::RootResidentLearningProfileV3;
use crate::LearningIterationRuntimeErrorV1 as Error;
use crate::LearningIterationStageOwnerPortsV1;
use crate::OriginalCellQ24NoUpdateStageOwnersV1;

pub(super) async fn original_attestations(
    owner: &Arc<ResidentRegisteredStateV3>,
    stages: &OriginalCellQ24NoUpdateStageOwnersV1,
    verifier: &LearningEvidenceVerifierV1,
    snapshot: &LearningIterationSnapshotV1,
    cancellation: &CancellationToken,
) -> Result<Vec<SignedLearningEvidenceV1>, Error> {
    owner.authority.profile.scope.validate_snapshot(snapshot)?;
    stages.validate_recovery(snapshot).await?;
    let mut signatures = Vec::with_capacity(snapshot.receipts.len());
    for receipt in &snapshot.receipts {
        let (_, now) = owner.read(cancellation).await?;
        signatures.push(stages.receipt_attestation(snapshot, receipt, now / 1_000).await?);
    }
    // All role I/O precedes this fresh Root clock and revalidation of every
    // retained complete signature, including the earliest observer window.
    let (_, fresh) = owner.read(cancellation).await?;
    verify_attestations(&owner.authority.profile, verifier, snapshot, &signatures, fresh / 1_000)?;
    Ok(signatures)
}

pub(super) fn verify_attestations(
    profile: &RootResidentLearningProfileV3,
    verifier: &LearningEvidenceVerifierV1,
    snapshot: &LearningIterationSnapshotV1,
    signatures: &[SignedLearningEvidenceV1],
    now: u64,
) -> Result<(), Error> {
    profile.scope.validate_snapshot(snapshot)?;
    if snapshot.request != profile.initial.request || snapshot.owners != profile.initial.owners
        || signatures.len() != snapshot.receipts.len()
        || signatures.len() > 5
        || verifier.trust_digest() != snapshot.owners.evidence_trust_digest
    {
        return Err(Error::WrongScope);
    }
    let mut verified = Vec::with_capacity(signatures.len());
    for (receipt, signature) in snapshot.receipts.iter().zip(signatures) {
        let stage = receipt.observation.stage();
        let role = match stage {
            LearningIterationStageV1::Experience | LearningIterationStageV1::Dataset
            | LearningIterationStageV1::NextUse => LearningEvidenceRoleV1::Observer,
            LearningIterationStageV1::Training => LearningEvidenceRoleV1::Generator,
            LearningIterationStageV1::Selection => LearningEvidenceRoleV1::Selector,
            LearningIterationStageV1::Evaluation | LearningIterationStageV1::Proposal =>
                return Err(Error::OwnerUnavailable("resident Candidate evaluation/Model route is absent")),
        };
        let payload = learning_iteration_receipt_signing_bytes_v1(receipt)?;
        let evidence = verifier.verify(role, signature, &payload, now).map_err(Error::Evidence)?;
        if evidence.principal().principal_id != receipt.actor_id
            || &receipt.actor_id != snapshot.owners.owner(stage)
            || evidence.trust_digest() != snapshot.owners.evidence_trust_digest
            || evidence.objective_digest() != snapshot.request.envelope.objective_digest
        {
            return Err(Error::Evidence(SignedEvidenceError::ContextMismatch));
        }
        verified.push((stage, evidence));
    }
    for (stage, current) in &verified {
        let independent: &[LearningIterationStageV1] = match stage {
            LearningIterationStageV1::Selection => {
                if snapshot.training_no_update_v2().is_none() {
                    return Err(Error::WrongScope);
                }
                &[LearningIterationStageV1::Training]
            }
            LearningIterationStageV1::NextUse =>
                &[LearningIterationStageV1::Training, LearningIterationStageV1::Selection],
            _ => &[],
        };
        for predecessor in independent {
            let previous = verified.iter().find(|(stage, _)| stage == predecessor)
                .ok_or(Error::Evidence(SignedEvidenceError::ContextMismatch))?;
            verify_signed_actor_separation(&previous.1, current, now).map_err(Error::Evidence)?;
        }
    }
    Ok(())
}
