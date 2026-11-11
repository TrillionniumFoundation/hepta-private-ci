//! The original external public API and a closed internal Trainer source.

use super::*;

/// Borrow the original owners for this read. No provider, attestor, arbitrary
/// receipt, caller clock or replacement trust is accepted. The full recovered
/// history is retained when asking the Trainer for its original attestation.
pub struct OriginalCellEvaluationReceiptSourcesV1<
    'a,
    S,
    C: AnchorWitnessStore,
    F: AnchorWitnessStore,
    E,
> {
    pub snapshot: &'a LearningIterationSnapshotV1,
    pub runner: &'a mut CellEvaluationRunnerV1<S>,
    pub journals: CellEvaluationJournalsV1<'a, C, F>,
    pub candidate_plan: &'a TemporalEvaluationPlan,
    pub baseline_plan: &'a TemporalEvaluationPlan,
    pub executions: &'a mut E,
    pub qualification: &'a CellEvaluationQualificationV1,
    pub context: &'a ProductQualificationContextV1,
    pub evidence: &'a SignedEvaluationEvidenceV1,
    pub timing: ProductTimingEvidenceV1<'a>,
    pub trainer: &'a LearningIterationEvidenceClientV1,
}

/// Borrow the original owners for this read. No provider, attestor, arbitrary
/// receipt, caller clock or replacement trust is accepted. The full recovered
/// history is retained when asking the Trainer for its original attestation.
pub(crate) struct ReceiptSources<
    'a,
    S,
    C: AnchorWitnessStore,
    F: AnchorWitnessStore,
    E,
> {
    pub(crate) snapshot: &'a LearningIterationSnapshotV1,
    pub(crate) runner: &'a mut CellEvaluationRunnerV1<S>,
    pub(crate) journals: CellEvaluationJournalsV1<'a, C, F>,
    pub(crate) candidate_plan: &'a TemporalEvaluationPlan,
    pub(crate) baseline_plan: &'a TemporalEvaluationPlan,
    pub(crate) executions: &'a mut E,
    pub(crate) qualification: &'a CellEvaluationQualificationV1,
    pub(crate) context: &'a ProductQualificationContextV1,
    pub(crate) evidence: &'a SignedEvaluationEvidenceV1,
    pub(crate) timing: ProductTimingEvidenceV1<'a>,
    pub(crate) trainer: OriginalCellEvaluationTrainerReadbackV1<'a>,
}


impl<'a, S, C: AnchorWitnessStore, F: AnchorWitnessStore, E>
    From<OriginalCellEvaluationReceiptSourcesV1<'a, S, C, F, E>>
    for ReceiptSources<'a, S, C, F, E>
{
    fn from(source: OriginalCellEvaluationReceiptSourcesV1<'a, S, C, F, E>) -> Self {
        Self {
            snapshot: source.snapshot,
            runner: source.runner,
            journals: source.journals,
            candidate_plan: source.candidate_plan,
            baseline_plan: source.baseline_plan,
            executions: source.executions,
            qualification: source.qualification,
            context: source.context,
            evidence: source.evidence,
            timing: source.timing,
            trainer: OriginalCellEvaluationTrainerReadbackV1::External(source.trainer),
        }
    }
}
