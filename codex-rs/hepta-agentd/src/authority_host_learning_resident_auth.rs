//! Current original role evidence at the resident coordinator and consumer.
//! This authenticates observations; it neither dispatches nor re-signs them.

use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
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
use super::model::ResidentOriginalModelProofV3;
use super::profile::RootResidentLearningProfileV3;
use super::stages::ResidentOriginalStageOwnersV3;
use crate::LearningIterationRuntimeErrorV1 as Error;
use crate::LearningIterationStageOwnerPortsV1;

pub(super) struct ResidentOriginalEvidenceV3 {
    pub(super) signatures: Vec<SignedLearningEvidenceV1>,
    pub(super) model: Option<ResidentOriginalModelProofV3>,
}

pub(super) async fn original_attestations(
    owner: &Arc<ResidentRegisteredStateV3>,
    stages: &ResidentOriginalStageOwnersV3,
    verifier: &LearningEvidenceVerifierV1,
    snapshot: &LearningIterationSnapshotV1,
    cancellation: &CancellationToken,
) -> Result<ResidentOriginalEvidenceV3, Error> {
    owner.authority.profile.scope.validate_snapshot(snapshot)?;
    let has_model = snapshot
        .receipts
        .iter()
        .any(|receipt| receipt.observation.stage() == LearningIterationStageV1::Proposal);
    // This private concrete route reads the entire evaluated prefix once for
    // this checkpoint. All other profiles retain their original role protocol.
    // No cached signature set can substitute for this invocation's original I/O.
    owner.read(cancellation).await?;
    let evaluated =
        ResidentOriginalStageOwnersV3::read_original_evaluated_attestations(stages, snapshot)
            .await?;
    let signatures = if let Some(original) = evaluated {
        if has_model {
            return Err(Error::WrongScope);
        }
        original
    } else {
        if !has_model {
            stages.validate_recovery(snapshot).await?;
        }
        let mut signatures = Vec::with_capacity(snapshot.receipts.len());
        for receipt in snapshot
            .receipts
            .iter()
            .filter(|receipt| receipt.observation.stage() != LearningIterationStageV1::Proposal)
        {
            let (_, now) = owner.read(cancellation).await?;
            signatures.push(
                stages
                    .receipt_attestation(snapshot, receipt, now / 1_000)
                    .await?,
            );
        }
        signatures
    };
    // Model has no LearningEvidence role. This last actual Model read performs
    // its own D/T/E before/after reads and final original journal CURRENT.
    let original_model = if has_model {
        Some(ResidentOriginalStageOwnersV3::read_original_model(stages, snapshot).await?)
    } else {
        None
    };
    // All role I/O precedes this fresh Root clock and revalidation of every
    // retained complete signature, including the earliest observer window.
    let (_, fresh) = owner.read(cancellation).await?;
    ResidentOriginalStageOwnersV3::require_initial(
        stages,
        &owner.authority.profile.initial,
        &owner.authority.profile.scope,
        verifier,
    )?;
    let model = original_model
        .as_ref()
        .map(|original| {
            ResidentOriginalModelProofV3::from_original_readback(
                &owner.authority.profile,
                verifier,
                snapshot,
                &signatures,
                original,
                fresh / 1_000,
            )
        })
        .transpose()?;
    verify_original_evidence(
        &owner.authority.profile,
        verifier,
        snapshot,
        &signatures,
        model.as_ref(),
        fresh / 1_000,
    )?;
    Ok(ResidentOriginalEvidenceV3 { signatures, model })
}

pub(super) fn verify_attestations(
    profile: &RootResidentLearningProfileV3,
    verifier: &LearningEvidenceVerifierV1,
    snapshot: &LearningIterationSnapshotV1,
    signatures: &[SignedLearningEvidenceV1],
    now: u64,
) -> Result<(), Error> {
    verify_original_evidence(profile, verifier, snapshot, signatures, None, now)
}

pub(super) fn verify_original_evidence(
    profile: &RootResidentLearningProfileV3,
    verifier: &LearningEvidenceVerifierV1,
    snapshot: &LearningIterationSnapshotV1,
    signatures: &[SignedLearningEvidenceV1],
    model: Option<&ResidentOriginalModelProofV3>,
    now: u64,
) -> Result<(), Error> {
    verify_non_model_attestations(profile, verifier, snapshot, signatures, now)?;
    let proposal = snapshot
        .receipts
        .iter()
        .any(|receipt| receipt.observation.stage() == LearningIterationStageV1::Proposal);
    match (proposal, model) {
        (false, None) => Ok(()),
        (true, Some(model)) => model.require_original(profile, verifier, snapshot, signatures, now),
        (false, Some(_)) | (true, None) => Err(Error::WrongScope),
    }
}

/// A saved cold tuple is only a comparison pin. This function never returns
/// an original Model receipt or proof, and is reachable only in readonly bind.
pub(super) fn verify_model_comparison_pin(
    profile: &RootResidentLearningProfileV3,
    verifier: &LearningEvidenceVerifierV1,
    snapshot: &LearningIterationSnapshotV1,
    signatures: &[SignedLearningEvidenceV1],
    original_model: &[u8],
    now: u64,
) -> Result<(), Error> {
    verify_non_model_attestations(profile, verifier, snapshot, signatures, now)?;
    ResidentOriginalModelProofV3::decode_root_reply(
        original_model,
        profile,
        verifier,
        snapshot,
        signatures,
        now,
    )?;
    Ok(())
}

fn verify_non_model_attestations(
    profile: &RootResidentLearningProfileV3,
    verifier: &LearningEvidenceVerifierV1,
    snapshot: &LearningIterationSnapshotV1,
    signatures: &[SignedLearningEvidenceV1],
    now: u64,
) -> Result<(), Error> {
    profile
        .require_verifier(verifier)
        .map_err(|_| Error::WrongScope)?;
    profile.scope.validate_snapshot(snapshot)?;
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
    // Authenticate this distinct negative Candidate branch without changing
    // stage admission. Its actual Selector/C owners are still required by the
    // concrete continuation; these signed observations grant no execution.
    let evaluated_retention = matches!(
        snapshot.receipts.get(3).map(|receipt| &receipt.observation),
        Some(LearningIterationObservationV1::Evaluation {
            disposition: LearningEvaluationDispositionV1::NoUpdate,
            ..
        })
    );
    if evaluated_retention {
        let candidate = coordinator
            .candidate()
            .ok_or(Error::WrongScope)?
            .digest()
            .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
        let baseline = snapshot
            .request
            .selected_bundle
            .digest()
            .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
        let stages = [
            LearningIterationStageV1::Experience,
            LearningIterationStageV1::Dataset,
            LearningIterationStageV1::Training,
            LearningIterationStageV1::Evaluation,
            LearningIterationStageV1::Selection,
            LearningIterationStageV1::NextUse,
        ];
        if !(4..=6).contains(&snapshot.receipts.len())
            || !snapshot
                .receipts
                .iter()
                .zip(stages)
                .all(|(receipt, stage)| receipt.observation.stage() == stage)
            || !matches!(
                snapshot.receipts[2].observation,
                LearningIterationObservationV1::Training { .. }
            )
            || candidate == baseline
            || coordinator.next_task_bundle() != Some(&snapshot.request.selected_bundle)
            || snapshot.receipts.get(5).is_some_and(|receipt| {
                !matches!(
                    receipt.observation,
                    LearningIterationObservationV1::RetainedModelNextUse { .. }
                )
            })
        {
            return Err(Error::WrongScope);
        }
    }
    let proposal_count = snapshot
        .receipts
        .iter()
        .filter(|receipt| receipt.observation.stage() == LearningIterationStageV1::Proposal)
        .count();
    if snapshot.request != profile.initial.request
        || snapshot.owners != profile.initial.owners
        || proposal_count > 1
        || proposal_count == 1
            && (snapshot.receipts.len() != 5
                || snapshot.receipts[4].observation.stage() != LearningIterationStageV1::Proposal)
        || signatures.len() + proposal_count != snapshot.receipts.len()
        || signatures.len() > 5 && (!evaluated_retention || signatures.len() != 6)
        || verifier.trust_digest() != snapshot.owners.evidence_trust_digest
    {
        return Err(Error::WrongScope);
    }
    let mut verified = Vec::with_capacity(signatures.len());
    for (receipt, signature) in snapshot
        .receipts
        .iter()
        .filter(|receipt| receipt.observation.stage() != LearningIterationStageV1::Proposal)
        .zip(signatures)
    {
        let stage = receipt.observation.stage();
        let role = match stage {
            LearningIterationStageV1::Experience
            | LearningIterationStageV1::Dataset
            | LearningIterationStageV1::NextUse => LearningEvidenceRoleV1::Observer,
            LearningIterationStageV1::Training => LearningEvidenceRoleV1::Generator,
            LearningIterationStageV1::Selection => LearningEvidenceRoleV1::Selector,
            LearningIterationStageV1::Evaluation => {
                // This exact original Candidate payload is separately obtained
                // through the concrete Evaluator command. Its signature grants
                // no Model or version rights and cannot stand in for a panel.
                let mut training =
                    LearningIterationCoordinatorV1::from_snapshot(profile.initial.clone())?;
                if snapshot.receipts.len() < 4
                    || snapshot.training_no_update_v2().is_some()
                    || snapshot.receipts.get(3) != Some(receipt)
                {
                    return Err(Error::WrongScope);
                }
                for original in &snapshot.receipts[..3] {
                    training.record(original.clone(), original.observed_unix_seconds)?;
                }
                let candidate = training
                    .candidate()
                    .ok_or(Error::WrongScope)?
                    .digest()
                    .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
                if training.next_stage() != Some(LearningIterationStageV1::Evaluation)
                    || receipt.predecessor != training.snapshot().head_digest
                    || receipt.operation_id != profile.initial.request.operation_id
                    || receipt.observed_unix_seconds > signature.issued_at
                    || !matches!(&receipt.observation, LearningIterationObservationV1::Evaluation {
                        candidate_bundle, evaluation_profile, ..
                    } if *candidate_bundle == candidate
                        && *evaluation_profile == profile.initial.request.evaluation_profile)
                {
                    return Err(Error::WrongScope);
                }
                LearningEvidenceRoleV1::Evaluator
            }
            LearningIterationStageV1::Proposal => {
                return Err(Error::WrongScope);
            }
        };
        let payload = learning_iteration_receipt_signing_bytes_v1(receipt)?;
        let evidence = verifier
            .verify(role, signature, &payload, now)
            .map_err(Error::Evidence)?;
        if evidence.principal().principal_id != receipt.actor_id
            || &receipt.actor_id != snapshot.owners.owner(stage)
            || evidence.trust_digest() != snapshot.owners.evidence_trust_digest
            || evidence.objective_digest() != snapshot.request.envelope.objective_digest
            || evaluated_retention && receipt.observed_unix_seconds > signature.issued_at
        {
            return Err(Error::Evidence(SignedEvidenceError::ContextMismatch));
        }
        verified.push((stage, evidence));
    }
    for (stage, current) in &verified {
        let independent: &[LearningIterationStageV1] = match stage {
            LearningIterationStageV1::Evaluation => &[LearningIterationStageV1::Training],
            LearningIterationStageV1::Selection => {
                if snapshot.training_no_update_v2().is_none() && !evaluated_retention {
                    return Err(Error::WrongScope);
                }
                if evaluated_retention {
                    &[
                        LearningIterationStageV1::Training,
                        LearningIterationStageV1::Evaluation,
                    ]
                } else {
                    &[LearningIterationStageV1::Training]
                }
            }
            LearningIterationStageV1::NextUse if evaluated_retention => &[
                LearningIterationStageV1::Training,
                LearningIterationStageV1::Evaluation,
                LearningIterationStageV1::Selection,
            ],
            LearningIterationStageV1::NextUse => &[
                LearningIterationStageV1::Training,
                LearningIterationStageV1::Selection,
            ],
            _ => &[],
        };
        for predecessor in independent {
            let previous = verified
                .iter()
                .find(|(stage, _)| stage == predecessor)
                .ok_or(Error::Evidence(SignedEvidenceError::ContextMismatch))?;
            verify_signed_actor_separation(&previous.1, current, now).map_err(Error::Evidence)?;
        }
    }
    Ok(())
}
