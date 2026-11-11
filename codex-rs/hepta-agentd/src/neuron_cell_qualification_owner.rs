//! Original Product qualification through the same guarded Cell runner.
//! The sealed comparison and both original task journals remain required. This
//! bridge neither runs another holdout nor constructs a publication from fields.

use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::LockedFileProductEvaluationExecutionStoreV1;
use codex_hepta_intelligence_eval::ProductQualificationContextV1;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_neuron::AnchorWitnessStore;

use super::CellEvaluationErrorV1;
use super::CellEvaluationJournalsV1;
use super::CellEvaluationPlanV1;
use super::CellEvaluationQualificationV1;
use super::CellEvaluationRunnerV1;
use crate::OriginalProductQualificationErrorV1;
use crate::OriginalProductQualificationOwnerV1;
use crate::OriginalProductQualificationSourceV1;

/// Borrow the original sealed Cell plan, drained journals, and current Product
/// source. These references do not provision any owner, signer, or authority.
pub struct OriginalCellQualificationSourceV1<'a, C: AnchorWitnessStore, F: AnchorWitnessStore> {
    pub plan: &'a CellEvaluationPlanV1,
    pub journals: CellEvaluationJournalsV1<'a, C, F>,
    pub product: OriginalProductQualificationSourceV1<'a>,
}

impl<C: AnchorWitnessStore, F: AnchorWitnessStore> OriginalCellQualificationSourceV1<'_, C, F> {
    fn require_original(&self) -> Result<(), CellEvaluationErrorV1> {
        if self.product.plan != self.plan.product_plan() {
            return Err(CellEvaluationErrorV1::Binding(
                "original Cell qualification product plan",
            ));
        }
        self.plan.require_journals(CellEvaluationJournalsV1 {
            candidate: self.journals.candidate,
            fixed_expert: self.journals.fixed_expert,
        })
    }
}

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQualificationErrorV1 {
    #[error("original Cell comparison: {0}")]
    Cell(#[from] CellEvaluationErrorV1),
    #[error("original qualification publication: {0}")]
    Publication(#[from] OriginalProductQualificationErrorV1),
    #[error("original Cell qualification completion is uncertain")]
    CommitUncertain,
}

impl CellEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1> {
    /// Publish only through the actual original Product owner, borrowing this
    /// runner's existing holdout owner. The two Cell journals are rechecked
    /// before the final complete publication readback. No receipt is returned
    /// when either source changed or the original acknowledgement is uncertain.
    pub fn publish_original_qualification(
        &mut self,
        owner: &mut OriginalProductQualificationOwnerV1<impl AnchorWitnessStore>,
        executions: &mut LockedFileProductEvaluationExecutionStoreV1,
        source: OriginalCellQualificationSourceV1<
            '_,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
        >,
        context: &ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
    ) -> Result<CellEvaluationQualificationV1, OriginalCellQualificationErrorV1> {
        source.require_original()?;
        let publication = OriginalProductQualificationOwnerV1::publish(
            owner,
            &mut self.product,
            executions,
            &source.product,
            context,
            evidence,
        )?;
        source.require_original()?;
        let retained = OriginalProductQualificationOwnerV1::readback(
            owner,
            &mut self.product,
            executions,
            &source.product,
        )?;
        if retained != publication {
            return Err(OriginalCellQualificationErrorV1::CommitUncertain);
        }
        Ok(CellEvaluationQualificationV1 {
            comparison: source.plan.record.clone(),
            product: retained,
        })
    }

    /// Restore the original Cell qualification without a provider, signer,
    /// caller-supplied publication or old signing context. The Product owner
    /// recovers those original bytes and verifies current trust and time.
    pub fn readback_original_qualification(
        &mut self,
        owner: &mut OriginalProductQualificationOwnerV1<impl AnchorWitnessStore>,
        executions: &mut LockedFileProductEvaluationExecutionStoreV1,
        source: OriginalCellQualificationSourceV1<
            '_,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
        >,
    ) -> Result<CellEvaluationQualificationV1, OriginalCellQualificationErrorV1> {
        source.require_original()?;
        let publication = OriginalProductQualificationOwnerV1::readback(
            owner,
            &mut self.product,
            executions,
            &source.product,
        )?;
        source.require_original()?;
        let retained = OriginalProductQualificationOwnerV1::readback(
            owner,
            &mut self.product,
            executions,
            &source.product,
        )?;
        if retained != publication {
            return Err(OriginalCellQualificationErrorV1::CommitUncertain);
        }
        Ok(CellEvaluationQualificationV1 {
            comparison: source.plan.record.clone(),
            product: retained,
        })
    }
}
