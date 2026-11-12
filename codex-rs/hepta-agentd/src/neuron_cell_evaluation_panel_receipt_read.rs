//! One borrowed middle slot of the original Bound panel read. This type has
//! no signature/CURRENT getter. Only the actual ReceiptOwner can consume it;
//! the enclosing Host must still close every panel and physical Trainer slot.

use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreV1;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use codex_hepta_neuron::AnchorWitnessStore;

use super::Cursor;
use super::Error;
use super::OriginalPanelTrainingPinV1;
use super::OriginalPanelTrainingProofV1;
use super::OriginalPanelTrainingReadV1;
use super::OriginalPanelTrainingSourceV1;
use super::ReceiptMode;
use crate::CellEvaluationReceiptV1;
use crate::LearningIterationEvidenceClientV1;
use crate::OriginalCellEvaluationQualificationConfigV1;
use crate::OriginalCellEvaluationReceiptErrorV1;
use crate::OriginalCellEvaluationReceiptOwnerV1;
use crate::OriginalCellEvaluationReceiptSourcesV1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1 as OwnerError;

pub(in super::super) enum OriginalPanelReceiptReadV1<'read, 'call> {
    Physical,
    Bound(OriginalBoundPanelReceiptReadV1<'read, 'call>),
}

/// The private constructor borrows the occupied proof at exactly 4m slots.
/// Dropping this value leaves that proof Refused, including a canceled await.
pub(crate) struct OriginalBoundPanelReceiptReadV1<'read, 'call> {
    proof: &'read mut OriginalPanelTrainingProofV1<'call>,
    original: &'call OriginalPanelTrainingPinV1,
    slot: usize,
    roles_verified: bool,
}

impl<'call> OriginalPanelTrainingReadV1<'call> {
    pub(in super::super) fn receipt_read(
        &mut self,
        trainer: &LearningIterationEvidenceClientV1,
        config: &crate::OriginalCellEvaluationQualificationConfigV1,
    ) -> Result<OriginalPanelReceiptReadV1<'_, 'call>, Error> {
        let Self::Panel(proof) = self else {
            return Ok(OriginalPanelReceiptReadV1::Physical);
        };
        let call = proof.call;
        let OriginalPanelTrainingSourceV1::Bound(original) = &call.source else {
            return Ok(OriginalPanelReceiptReadV1::Physical);
        };
        let previous = std::mem::replace(&mut proof.cursor, Cursor::Refused);
        let Cursor::Next(slot) = previous else {
            return Err(Error::CommitUncertain);
        };
        if !matches!(call.receipt, ReceiptMode::BoundReadback)
            || slot != call.slots / 2
            || proof.receipt_completed
        {
            return Err(Error::CommitUncertain);
        }
        original.require_member_source(trainer, config)?;
        Ok(OriginalPanelReceiptReadV1::Bound(
            OriginalBoundPanelReceiptReadV1 {
                proof,
                original,
                slot,
                roles_verified: false,
            },
        ))
    }
}

impl OriginalBoundPanelReceiptReadV1<'_, '_> {
    pub(crate) fn require_receipt_source(
        &self,
        owner: &OriginalCellEvaluationReceiptOwnerV1<impl AnchorWitnessStore>,
        source: &OriginalCellEvaluationReceiptSourcesV1<
            '_,
            impl FinalHoldoutCasStoreV1,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
            impl ProductEvaluationExecutionStoreV1,
        >,
    ) -> Result<(), OriginalCellEvaluationReceiptErrorV1> {
        let (receipt, _) = OriginalCellEvaluationReceiptOwnerV1::original_host_profile(owner);
        let original: &OriginalCellEvaluationQualificationConfigV1 = &self.original.config;
        if !matches!(self.proof.cursor, Cursor::Refused)
            || self.proof.receipt_completed
            || !std::ptr::eq(self.original.trainer.as_ref(), source.trainer)
            || source.snapshot != &original.training
            || source.context.generator != original.context.generator
            || source.context.evaluator != original.context.evaluator
            || source.context.retention_receipt_digests
                != original.context.retention_receipt_digests
            || source.context.unlearning_receipt_digest
                != original.context.unlearning_receipt_digest
            || source.evidence != &original.product_evidence
            || !matches!(&source.timing, ProductTimingEvidenceV1::Qualification)
            || receipt.training != original.training
            || receipt.scope != original.scope
            || receipt.plan != original.plan
            || receipt.signing.plan != *original.plan.product_plan()
            || receipt.signing.execution_namespace != original.execution_namespace
            || receipt.signing.signer.principal != original.context.evaluator
            || receipt.signing.verifier.trust_digest() != original.verifier.trust_digest()
            || receipt.signing.verifier.scope_digest() != original.verifier.scope_digest()
            || receipt.signing.verifier.objective_digest() != original.verifier.objective_digest()
        {
            return Err(
                OwnerError::Binding("same occupied panel receipt and original Trainer").into(),
            );
        }
        Ok(())
    }

    pub(crate) fn authenticate_roles(
        &mut self,
        owner: &OriginalCellEvaluationReceiptOwnerV1<impl AnchorWitnessStore>,
        source: &OriginalCellEvaluationReceiptSourcesV1<
            '_,
            impl FinalHoldoutCasStoreV1,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
            impl ProductEvaluationExecutionStoreV1,
        >,
        execution: &CellEvaluationReceiptV1,
    ) -> Result<(), OriginalCellEvaluationReceiptErrorV1> {
        if self.roles_verified {
            return Err(OwnerError::CommitUncertain.into());
        }
        self.require_receipt_source(owner, source)?;
        OriginalCellEvaluationReceiptOwnerV1::authenticate_original_panel_roles(
            owner,
            source,
            execution,
            &self.original.config.training_evidence,
        )?;
        self.roles_verified = true;
        Ok(())
    }

    pub(crate) fn finish(self, current: u64) -> Result<(), OriginalCellEvaluationReceiptErrorV1> {
        if !self.roles_verified
            || !matches!(self.proof.cursor, Cursor::Refused)
            || self.proof.receipt_completed
            || self.slot != self.proof.call.slots / 2
            || !matches!(self.proof.call.receipt, ReceiptMode::BoundReadback)
        {
            return Err(OwnerError::CommitUncertain.into());
        }
        self.original.authenticate(current).map_err(|_| {
            OwnerError::Binding("original Training validity at the middle receipt boundary")
        })?;
        self.proof.receipt_completed = true;
        self.proof.cursor = Cursor::Next(self.slot);
        Ok(())
    }
}
