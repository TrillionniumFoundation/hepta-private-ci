//! Readonly original Evaluator material for the original Trainer's Model lane.
//! Neither the wire nor this value reconstructs a Runner, Cell or Qualification
//! seal. A completed transfer is one CURRENT observation, never an adoption
//! grant or a lease across a later Model operation.

use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use super::Error;
use super::Receipt;
use super::contract::Context;

#[path = "neuron_cell_evaluation_model_material_codec.rs"]
mod codec;
#[path = "neuron_cell_evaluation_model_material_verify.rs"]
mod verify;
#[path = "neuron_cell_evaluation_model_material_member.rs"]
mod member;
#[path = "neuron_cell_evaluation_model_material_export.rs"]
mod export;
#[path = "neuron_cell_evaluation_model_material_connection.rs"]
mod connection;
#[path = "neuron_cell_evaluation_model_material_wire.rs"]
mod wire;
#[path = "neuron_cell_evaluation_model_material_service.rs"]
mod service;

pub use connection::OriginalCellEvaluationModelMaterialClientV1;
pub use connection::OriginalCellEvaluationModelMaterialConnectionV1;

const MAX_BYTES: usize = 131_072;
const PAGE_BYTES: usize = 8192;
const MAX_PAGES: usize = MAX_BYTES / PAGE_BYTES;
const MAX_MEMBERS: usize = 17;

/// No Clone, Deserialize, public constructor or writable owner extraction.
pub struct OriginalCellEvaluationModelMaterialV1 {
    context: Context,
    evaluation: Receipt,
    bytes: Vec<u8>,
    binding: Digest32,
    observed_at: u64,
}

/// Closed, pure Model admission fields. The old local material/key algorithm
/// and this material use the same complete manifest encodings and digest domain.
pub(crate) struct OriginalCellEvaluationModelInputV1 {
    evaluation: LearningIterationReceiptV1,
    candidate: Digest32,
    material: Digest32,
}

impl OriginalCellEvaluationModelInputV1 {
    pub(crate) fn evaluation(&self) -> &LearningIterationReceiptV1 { &self.evaluation }
    pub(crate) fn candidate(&self) -> Digest32 { self.candidate }
    pub(crate) fn material_digest(&self) -> Digest32 { self.material }
}

impl OriginalCellEvaluationModelMaterialV1 {
    pub fn binding(&self) -> Digest32 { self.binding }
    pub(crate) fn original_evaluation(&self) -> &Receipt { &self.evaluation }
    pub fn authority(&self) -> AuthorityPosture { AuthorityPosture::DENY_ALL }

    /// Pure final verification only. The closed Model host must separately read
    /// the original Evaluator before and after its original Trainer lane work.
    pub(crate) fn authenticate_current(&self, current: u64) -> Result<(), Error> {
        if current < self.observed_at || Digest32::of_bytes(&self.bytes) != self.binding {
            return Err(Error::CommitUncertain);
        }
        verify::material(&self.context, &self.evaluation, &self.bytes, current)?;
        Ok(())
    }

    pub(crate) fn require_original_model_input(
        &self,
        training: &LearningIterationSnapshotV1,
        training_evidence: &SignedLearningEvidenceV1,
        current: u64,
    ) -> Result<OriginalCellEvaluationModelInputV1, Error> {
        if training != &self.context.training
            || training_evidence != &self.context.training_evidence
            || current < self.observed_at
        {
            return Err(Error::Binding("same original Model Training cut and full signature"));
        }
        let checked = verify::material(&self.context, &self.evaluation, &self.bytes, current)?;
        if !checked.qualified {
            return Err(Error::Binding("NoUpdate has no model proposal"));
        }
        Ok(OriginalCellEvaluationModelInputV1 {
            evaluation: self.evaluation.receipt().clone(),
            candidate: checked.candidate,
            material: checked.material,
        })
    }
}
