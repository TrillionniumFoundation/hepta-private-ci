//! Closed pure projection of already read original Cell/Product material.
use codex_hepta_intelligence_eval::OriginalProductQualificationCommitmentsV1;

use super::*;

impl<S: FinalHoldoutCasStoreV1> CellEvaluationRunnerV1<S> {
    pub(crate) fn original_model_commitments(
        &self,
        receipt: &CellEvaluationReceiptV1,
        qualification: &CellEvaluationQualificationV1,
        request: &CellEvaluationQualificationRequestV1<'_>,
    ) -> Result<OriginalProductQualificationCommitmentsV1, CellEvaluationErrorV1> {
        if qualification.comparison() != receipt.plan().record()
            || !matches!(&request.timing, ProductTimingEvidenceV1::Qualification)
        {
            return Err(CellEvaluationErrorV1::Binding(
                "original Cell material projection",
            ));
        }
        receipt.require_original_signed_execution(&qualification.product().evaluator)?;
        ProductEvaluationRunnerV1::original_qualification_commitments(
            &self.product,
            receipt.temporal(),
            qualification.product(),
            request.context,
            request.evidence,
            request.verifier,
            request.now,
        )
        .map_err(CellEvaluationErrorV1::Product)
    }
}
