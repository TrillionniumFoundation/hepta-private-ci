//! Exact E/D/T/B pins for the independent evaluated-retention Version purpose.
//! Only original opaque owner readbacks construct this private context.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_types::Digest32;

use super::super::OriginalCircuitEvaluatedRetentionContextV1;
use super::super::context::PublicationAccess;
use super::Error;
use super::RetainedVersionOriginV1;
use super::now;
use super::require_clock;
use crate::OriginalCellEvaluationCommandReceiptV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;

pub(super) struct OriginalEvaluatedVersionCut {
    pub(super) material: OriginalCellQ24MaterialReceiptConfigV1,
    pub(super) dataset: OriginalCellQ24MaterialCommandReceiptV1,
    pub(super) evaluated: OriginalCircuitEvaluatedRetentionContextV1,
    pub(super) binding: Digest32,
    pub(super) initial_binding: Digest32,
}

impl OriginalEvaluatedVersionCut {
    pub(super) fn from_original(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        dataset: OriginalCellQ24MaterialCommandReceiptV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
        evaluation: &OriginalCellEvaluationCommandReceiptV1,
        origin: RetainedVersionOriginV1,
    ) -> Result<Self, Error> {
        let started = now()?;
        OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
            &dataset, &material,
        )?;
        let evaluated = match origin {
            RetainedVersionOriginV1::Fresh => {
                OriginalCircuitEvaluatedRetentionContextV1::from_original_evaluation(
                    material.scope.clone(),
                    material.verifier.clone(),
                    training,
                    evaluation,
                )?
            }
            RetainedVersionOriginV1::Recovered => {
                OriginalCircuitEvaluatedRetentionContextV1::recover_original_evaluation(
                    material.scope.clone(),
                    material.verifier.clone(),
                    training,
                    evaluation,
                )?
            }
        };
        let (initial_binding, fresh) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)?;
        require_clock(started, fresh)?;
        let mut cut = Self {
            material,
            dataset,
            evaluated,
            binding: Digest32::ZERO,
            initial_binding,
        };
        cut.binding = cut.authenticate(fresh, PublicationAccess::Readback)?;
        Ok(cut)
    }

    pub(super) fn authenticate(
        &self,
        at: u64,
        access: PublicationAccess,
    ) -> Result<Digest32, Error> {
        let decision = self.evaluated.authenticate(at, access)?;
        let prefix = decision.snapshot();
        let initial =
            LearningIterationCoordinatorV1::new(prefix.request.clone(), prefix.owners.clone())?;
        let (scope, verifier, _) = self.evaluated.receipt_configuration();
        if initial.snapshot() != &self.material.initial
            || scope != self.material.scope
            || verifier.trust_digest() != self.material.verifier.trust_digest()
            || verifier.scope_digest() != self.material.verifier.scope_digest()
            || verifier.objective_digest() != self.material.verifier.objective_digest()
            || self.dataset.snapshot().request != prefix.request
            || self.dataset.snapshot().owners != prefix.owners
            || self.dataset.snapshot().receipts != prefix.receipts[..2]
            || self.dataset.snapshot().head_digest != prefix.receipts[2].predecessor
        {
            return Err(Error::Binding(
                "same original evaluated initial and Dataset cut",
            ));
        }
        let mut material_signatures = Vec::new();
        for original in self.dataset.attestations() {
            material_signatures.extend_from_slice(&original.signing_bytes());
            material_signatures.extend_from_slice(&original.signature);
        }
        Ok(Digest32::of_parts(&[
            b"hepta.agentd.original-evaluated-version.command.v1\0",
            self.initial_binding.as_array(),
            &encode_original_owner_snapshot_v1(prefix)?,
            scope.binding().as_array(),
            verifier.trust_digest().as_array(),
            verifier.scope_digest().as_array(),
            verifier.objective_digest().as_array(),
            &material_signatures,
            self.evaluated.receipt_context_binding().as_array(),
        ]))
    }

    pub(super) fn require_fresh(
        &self,
        started: u64,
        access: PublicationAccess,
    ) -> Result<(), Error> {
        let (binding, at) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(
                &self.material,
            )?;
        let fresh = OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
            &self.dataset,
            &self.material,
        )?;
        require_clock(started, at)?;
        require_clock(at, fresh)?;
        if binding != self.initial_binding || self.authenticate(fresh, access)? != self.binding {
            return Err(Error::Binding(
                "same original complete evaluated Version context",
            ));
        }
        Ok(())
    }

    pub(super) fn duplicate_response_pin(&self) -> Self {
        Self {
            material: self.material.clone(),
            dataset: self.dataset.clone(),
            evaluated: self.evaluated.clone_for_original_receipt(),
            binding: self.binding,
            initial_binding: self.initial_binding,
        }
    }
}
