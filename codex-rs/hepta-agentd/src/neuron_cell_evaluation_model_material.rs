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
#[path = "neuron_cell_evaluation_model_material_connection.rs"]
mod connection;
#[path = "neuron_cell_evaluation_model_material_export.rs"]
mod export;
#[path = "neuron_cell_evaluation_model_material_member.rs"]
mod member;
#[path = "neuron_cell_evaluation_model_material_service.rs"]
mod service;
#[path = "neuron_cell_evaluation_model_material_verify.rs"]
mod verify;
#[path = "neuron_cell_evaluation_model_material_wire.rs"]
mod wire;

pub use connection::OriginalCellEvaluationModelMaterialClientV1;
pub use connection::OriginalCellEvaluationModelMaterialConnectionV1;
pub(crate) use connection::OriginalCellEvaluationModelReadV1;

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
    pub(crate) fn evaluation(&self) -> &LearningIterationReceiptV1 {
        &self.evaluation
    }
    pub(crate) fn candidate(&self) -> Digest32 {
        self.candidate
    }
    pub(crate) fn material_digest(&self) -> Digest32 {
        self.material
    }
}

impl OriginalCellEvaluationModelMaterialV1 {
    /// Canonical signed data only, borrowed inside the same native response.
    /// No Cell, Runner, Qualification or evidence owner is reconstructed.
    pub(crate) fn original_model_transfer_body(&self) -> &[u8] {
        &self.bytes
    }

    /// Only the private original Model response decoder calls this after its
    /// admitted peer exchange. Provisional material stays inside that transfer
    /// until actual native Model/Training and E Finish are acknowledged.
    pub(crate) fn from_original_model_response(
        material: &crate::OriginalCellQ24MaterialReceiptConfigV1,
        registration: &crate::OriginalCellEvaluationPanelRegistrationV1,
        dataset: &crate::OriginalCellQ24MaterialCommandReceiptV1,
        training: &crate::OriginalCellQ24TrainingCommandReceiptV1,
        evaluation: &Receipt,
        bytes: Vec<u8>,
        lower: u64,
    ) -> Result<Self, Error> {
        crate::OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
            dataset, material,
        ).map_err(|_| Error::Binding("original Model transfer Dataset context"))?;
        let context = Context::from_original_training(
            dataset.snapshot().clone(),
            material.scope.clone(),
            registration.clone(),
            material.verifier.clone(),
            training,
        )?;
        if context.initial()? != material.initial {
            return Err(Error::Binding("original Model transfer initial context"));
        }
        let body = codec::Body::decode(&bytes)?;
        if body.encode()? != bytes {
            return Err(Error::Binding("canonical complete original Model transfer"));
        }
        let current = super::now()?;
        super::require_clock(lower, current)?;
        verify::material(&context, evaluation, &bytes, current)?;
        let binding = Digest32::of_bytes(&bytes);
        Ok(Self {
            context,
            evaluation: evaluation.clone(),
            bytes,
            binding,
            observed_at: current,
        })
    }

    pub fn binding(&self) -> Digest32 {
        self.binding
    }
    pub(crate) fn original_evaluation(&self) -> &Receipt {
        &self.evaluation
    }
    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }

    /// Pure final verification only. The closed Model host must separately read
    /// the original Evaluator before and after its original Trainer lane work.
    pub(crate) fn authenticate_current(&self, current: u64) -> Result<(), Error> {
        if current < self.observed_at || Digest32::of_bytes(&self.bytes) != self.binding {
            return Err(Error::CommitUncertain);
        }
        verify::material(&self.context, &self.evaluation, &self.bytes, current)?;
        Ok(())
    }

    /// Require the same complete panel acceptance as Model admission, then
    /// match the original Selector's already enrolled primary evidence.
    /// No qualification seal is decoded or upgraded.
    pub(crate) fn require_original_selector_material(
        &self,
        config: &crate::OriginalCircuitModelSelectionReceiptConfigV1,
        current: u64,
    ) -> Result<(), Error> {
        self.require_original_model_input(
            &self.context.training,
            &self.context.training_evidence,
            current,
        )?;
        let body = codec::Body::decode(&self.bytes)?;
        let primary = body.members.first().ok_or(Error::Binding("original primary panel"))?;
        let (_, generator) = crate::learning_owner_evidence::decode(&primary.generator)?;
        let (_, evaluator) = crate::learning_owner_evidence::decode(&primary.evaluator)?;
        let (execution_payload, execution) = crate::learning_owner_evidence::decode(&primary.execution)?;
        if config.scope != self.context.scope
            || config.verifier.trust_digest() != self.context.verifier.trust_digest()
            || config.verifier.scope_digest() != self.context.verifier.scope_digest()
            || config.verifier.objective_digest() != self.context.verifier.objective_digest()
            || config.training_evidence != self.context.training_evidence
            || &config.evaluation_evidence != self.evaluation.attestation()
            || config.decision.request != self.evaluation.snapshot().request
            || config.decision.owners != self.evaluation.snapshot().owners
            || config.decision.receipts.len() != 5
            || config.decision.receipts[..4] != self.evaluation.snapshot().receipts
            || primary.record != serde_json::to_vec(config.qualification.comparison())?
            || config.qualification.comparison() != config.evaluation.plan().record()
            || Digest32::of_bytes(&primary.qualification) != config.qualification.product().evidence_digest
            || generator != config.product_evidence.generator_plan
            || evaluator != config.product_evidence.evaluator_bundle
            || &execution != config.execution_evidence.attestation()
            || execution_payload != codex_hepta_intelligence_eval::OriginalProductEvaluationExecutionEvidenceV1::signing_payload(&config.execution_evidence)
            || primary.execution_record != codex_hepta_intelligence_eval::OriginalProductEvaluationExecutionEvidenceV1::original_record(&config.execution_evidence)
        {
            return Err(Error::Binding("original Selector primary and full panel material"));
        }
        Ok(())
    }

    /// Pure transitive window for a new original Selector signature. It is
    /// derived only after full material verification and never renews evidence.
    pub(crate) fn original_publication_expiry(&self, current: u64) -> Result<u64, Error> {
        self.authenticate_current(current)?;
        let body = codec::Body::decode(&self.bytes)?;
        let mut expiry = self.context.training_evidence.expires_at
            .min(self.evaluation.attestation().expires_at);
        for member in &body.members {
            for (encoded, role) in [
                (&member.generator, codex_hepta_learning_ledger::LearningEvidenceRoleV1::Generator),
                (&member.evaluator, codex_hepta_learning_ledger::LearningEvidenceRoleV1::Evaluator),
                (&member.execution, codex_hepta_learning_ledger::LearningEvidenceRoleV1::Evaluator),
                (&member.freeze, codex_hepta_learning_ledger::LearningEvidenceRoleV1::Evaluator),
            ] {
                let (payload, signed) = crate::learning_owner_evidence::decode(encoded)?;
                let verified = self.context.verifier.verify(role, &signed, &payload, current)?;
                expiry = expiry.min(signed.expires_at).min(verified.principal().expires_at);
            }
        }
        if expiry <= current {
            return Err(Error::Binding("original complete panel signature window"));
        }
        Ok(expiry)
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
            || Digest32::of_bytes(&self.bytes) != self.binding
        {
            return Err(Error::Binding(
                "same original Model Training cut and full signature",
            ));
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
