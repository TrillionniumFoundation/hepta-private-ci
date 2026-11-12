//! Sealed material admission; original stage signatures are checked afresh.

use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::LearningProposalDispositionV1;

use super::*;

#[path = "cell_q24_model_projection.rs"]
mod projection;
#[cfg(target_os = "linux")]
pub(crate) use projection::RootQ24ModelProjectionDataV1;
#[cfg(target_os = "linux")]
pub(crate) use projection::project_original_root_model;
#[cfg(target_os = "linux")]
#[path = "cell_q24_model_root_admission.rs"]
mod root;
#[cfg(target_os = "linux")]
pub(super) use root::validate_original_root_material;

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
    model_owner_binding(
        dataset_cut.head_digest,
        original.scope_binding(),
        original.evidence_digest(),
    )
}

fn model_owner_binding(dataset_head: Digest32, scope: Digest32, training: Digest32) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.cell.q24.model-proposal-owner.v1\0",
        dataset_head.as_array(),
        scope.as_array(),
        training.as_array(),
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
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(inputs.training_cut.clone())?;
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
    projection::project_original_qualified_model(inputs, now)
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
