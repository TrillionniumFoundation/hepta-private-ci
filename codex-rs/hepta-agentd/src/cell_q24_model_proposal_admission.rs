//! Sealed material admission; original stage signatures are checked afresh.

use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::LearningProposalDispositionV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;

use super::*;

pub(super) fn owner_binding<T: AnchorWitnessStore>(
    trainer: &mut CellQ24TrainingOwnerV1<T>,
    dataset_cut: &LearningIterationSnapshotV1,
) -> Result<(Digest32, Digest32), Error> {
    let original = CellQ24TrainingOwnerV1::read_learning_observation(trainer, dataset_cut)?;
    if !matches!(
        original.observation(),
        LearningIterationObservationV1::Training { .. }
    ) {
        return Err(Error::Binding("NoUpdate has no model proposal"));
    }
    Ok((
        original.scope_binding(),
        original_binding(dataset_cut, &original),
    ))
}

fn original_binding(
    dataset_cut: &LearningIterationSnapshotV1,
    original: &crate::CellQ24TrainingObservationV2,
) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.cell.q24.model-proposal-owner.v1\0",
        dataset_cut.head_digest.as_array(),
        original.scope_binding().as_array(),
        original.evidence_digest().as_array(),
    ])
}

pub(super) struct Admission {
    cut: LearningIterationSnapshotV1,
    candidate: Digest32,
    material: Digest32,
}

pub(super) fn validate<T: AnchorWitnessStore, S: FinalHoldoutCasStoreV1>(
    trainer: &mut CellQ24TrainingOwnerV1<T>,
    dataset_cut: &LearningIterationSnapshotV1,
    scope: Digest32,
    owner_binding: Digest32,
    inputs: &CellQ24ModelProposalInputsV1<'_, S>,
    now: u64,
) -> Result<Admission, Error> {
    let mut coordinator =
        LearningIterationCoordinatorV1::from_snapshot(inputs.training_cut.clone())?;
    let cut = coordinator.snapshot();
    let original = CellQ24TrainingOwnerV1::read_learning_observation(trainer, dataset_cut)?;
    let training = cut
        .receipts
        .last()
        .ok_or(Error::Binding("original Training receipt"))?;
    if cut.request != dataset_cut.request
        || cut.owners != dataset_cut.owners
        || cut.receipts.len() != dataset_cut.receipts.len() + 1
        || !cut.receipts.starts_with(&dataset_cut.receipts)
        || coordinator.next_stage() != Some(LearningIterationStageV1::Evaluation)
        || original.scope_binding() != scope
        || original_binding(dataset_cut, &original) != owner_binding
        || original.iteration_head() != training.predecessor
        || original.evidence_digest() != training.evidence_digest
        || original.observation() != &training.observation
    {
        return Err(Error::Binding("exact original Training extension"));
    }
    let verified = inputs.request.verifier.verify(
        LearningEvidenceRoleV1::Generator,
        inputs.training_attestation,
        &learning_iteration_receipt_signing_bytes_v1(training)?,
        now,
    )?;
    if verified.principal().principal_id != cut.owners.trainer
        || verified.principal() != &inputs.qualification.product().generator
        || verified.trust_digest() != cut.owners.evidence_trust_digest
        || verified.objective_digest() != cut.request.envelope.objective_digest
    {
        return Err(Error::Binding("original Training signer"));
    }
    let candidate = coordinator
        .candidate()
        .ok_or(Error::Binding("trained candidate"))?;
    let comparison = inputs.evaluation.plan().record();
    for (bundle, manifest) in [
        (candidate, &comparison.candidate.manifest),
        (
            &cut.request.selected_bundle,
            &comparison.fixed_expert.manifest,
        ),
    ] {
        crate::cell_composed_q24::validate_manifest(bundle, manifest)
            .map_err(|_| Error::Binding("complete Q24 generation manifest"))?;
    }
    let candidate = candidate.digest().map_err(LearningIterationError::from)?;
    let timing = match &inputs.request.timing {
        ProductTimingEvidenceV1::Qualification => ProductTimingEvidenceV1::Qualification,
        ProductTimingEvidenceV1::SystemLongitudinal {
            timing,
            minimum_window_micros,
        } => ProductTimingEvidenceV1::SystemLongitudinal {
            timing,
            minimum_window_micros: *minimum_window_micros,
        },
    };
    let request = CellEvaluationQualificationRequestV1 {
        context: inputs.request.context,
        evidence: inputs.request.evidence,
        timing,
        verifier: inputs.request.verifier,
        now,
    };
    let evaluation = crate::prepare_cell_learning_evaluation_v1(
        inputs.runner,
        cut,
        inputs.evaluation,
        inputs.qualification,
        &request,
    )?;
    if !matches!(
        evaluation.observation,
        LearningIterationObservationV1::Evaluation {
            disposition: LearningEvaluationDispositionV1::Qualified,
            ..
        }
    ) {
        return Err(Error::Binding("NoUpdate has no model proposal"));
    }
    // Complete canonical manifest payloads, both evaluated journals and the
    // original training observation enter this record, not only a model name.
    let material = crate::cell_q24_model_material::original_model_material_digest(
        original.evidence_digest(), &comparison.candidate.manifest,
        &comparison.fixed_expert.manifest, comparison.candidate.journal_cut,
        comparison.fixed_expert.journal_cut,
        inputs.evaluation.plan().product_plan().frozen_plan.plan_digest,
        inputs.qualification.product().evidence_digest,
    )?;
    coordinator.record(evaluation.clone(), evaluation.observed_unix_seconds)?;
    Ok(Admission {
        cut: coordinator.snapshot().clone(),
        candidate,
        material,
    })
}

impl Admission {
    pub(super) fn key(&self, owner: Digest32) -> ProductEvaluationExecutionKeyV1 {
        ProductEvaluationExecutionKeyV1 {
            plan_id: self.cut.request.operation_id.clone(),
            binding_digest: Digest32::of_parts(&[
                b"hepta.cell.q24.model-proposal.v1\0",
                owner.as_array(),
                self.cut.head_digest.as_array(),
                self.material.as_array(),
            ]),
        }
    }
    pub(super) fn encode(&self, at: u64) -> Result<Vec<u8>, Error> {
        let lower = self
            .cut
            .receipts
            .last()
            .ok_or(Error::Binding("Evaluation cut"))?
            .observed_unix_seconds;
        if at < lower || at >= self.cut.request.envelope.expiry_unix_seconds {
            return Err(Error::Binding("original proposal deadline"));
        }
        let mut bytes = b"HQ24PROP".to_vec();
        bytes.extend_from_slice(self.cut.head_digest.as_array());
        bytes.extend_from_slice(self.material.as_array());
        bytes.extend_from_slice(&at.to_le_bytes());
        Ok(bytes)
    }
    pub(super) fn decode(
        &self,
        state: ProductEvaluationExecutionStateV1,
    ) -> Result<CellQ24ModelProposalReceiptV1, Error> {
        let ProductEvaluationExecutionStateV1::Completed(bytes) = state else {
            return Err(Error::Pending);
        };
        let time: [u8; 8] = bytes
            .get(72..80)
            .ok_or(Error::Binding("proposal record length"))?
            .try_into()
            .map_err(|_| Error::Binding("proposal time"))?;
        let at = u64::from_le_bytes(time);
        if self.encode(at)? != bytes {
            return Err(Error::Binding("original proposal bytes"));
        }
        let composition =
            Digest32::of_parts(&[b"hepta.cell.q24.model-proposal-receipt.v1\0", &bytes]);
        let receipt = LearningIterationReceiptV1 {
            operation_id: self.cut.request.operation_id.clone(),
            predecessor: self.cut.head_digest,
            actor_id: self.cut.owners.proposal.clone(),
            evidence_digest: composition,
            observed_unix_seconds: at,
            observation: LearningIterationObservationV1::Proposal {
                candidate_bundle: self.candidate,
                proposal_id: self.cut.request.operation_id.clone(),
                composition_digest: composition,
                disposition: LearningProposalDispositionV1::UpdateCandidates,
            },
        };
        let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(self.cut.clone())?;
        coordinator.record(receipt.clone(), at)?;
        Ok(CellQ24ModelProposalReceiptV1 { receipt })
    }
}

#[cfg(target_os = "linux")]
#[path = "cell_q24_model_current_admission.rs"]
mod current;
#[cfg(target_os = "linux")]
pub(super) use current::validate_current_material;
