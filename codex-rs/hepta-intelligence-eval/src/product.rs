//! Canonical, authority-free product qualification facade.
//!
//! This module narrows the supported product ingress without removing historical
//! top-level re-exports in the current compatibility window. It intentionally
//! omits the raw `ProductEvaluationRunnerV1`, direct decision primitives, and
//! in-memory attempt journal. Receipts produced through this facade remain
//! `DENY_ALL`; selection, activation, promotion, and release are external.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

/// Failure while the selected-host owner samples its trusted wall clock.
/// Missing or uncertain time is never replaced by a caller-provided scalar.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SelectedHostClockErrorV1 {
    Unavailable,
    Indeterminate,
}

impl fmt::Display for SelectedHostClockErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for SelectedHostClockErrorV1 {}

/// Host-owned clock capability for selected-host qualification and recovery.
///
/// `binding` identifies the concrete clock authority/topology and must remain
/// stable and nonzero for one selected-host operation. The repository does not
/// self-qualify an implementation of this trait: target-host evidence must bind
/// clock provenance, units, rollback resistance and failure domain. The
/// evaluator samples this capability immediately before signed final use rather
/// than accepting a scalar evidence time from its caller.
pub trait SelectedHostClockV1 {
    fn binding(&self) -> Digest32;

    fn sample_current_time(&mut self) -> Result<u64, SelectedHostClockErrorV1>;
}

pub use crate::AnchoredProductEvaluationAttemptJournalV1;
pub use crate::DurableProductEvaluationAttemptJournalV1;
pub use crate::FencedFinalHoldoutOwnerV1;
pub use crate::FinalHoldoutCasStoreV1;
pub use crate::FinalHoldoutProviderV1;
pub use crate::ProductAttemptRecoveryErrorV1;
pub use crate::ProductEvaluationAttemptAnchorStoreV1;
pub use crate::ProductEvaluationAttemptAnchorV1;
pub use crate::ProductEvaluationAttemptJournalErrorV1;
pub use crate::ProductEvaluationAttemptPhaseV1;
pub use crate::ProductEvaluationAttemptReceiptV1;
pub use crate::ProductEvaluationError;
pub use crate::ProductEvidenceSinkErrorV1;
pub use crate::ProductFrozenEvaluationPlanV1;
pub use crate::ProductFrozenOutcomePlanV1;
pub use crate::ProductOutcomeEvaluationReceiptV1;
pub use crate::ProductOutcomeQualificationReceiptV1;
pub use crate::ProductProviderErrorV1;
pub use crate::ProductQualificationContextV1;
pub use crate::ProductQualificationEvidenceSinkV1;
pub use crate::ProductQualificationPublicationRecordV1;
pub use crate::ProductQualificationPublicationRequestV1;
pub use crate::ProductQualificationPublicationStoreErrorV1;
pub use crate::ProductQualificationPublicationStoreV1;
pub use crate::ProductQualificationReceiptV1;
pub use crate::ProductTemporalEvaluationReceiptV1;
pub use crate::ProductTimingEvidenceV1;
pub use crate::RecordedProductEvaluationErrorV1;
pub use crate::RecordedProductEvaluationRunnerV1;
pub use crate::ReconciledProductQualificationSinkV1;
pub use crate::SignedEvaluationEvidenceV1;
pub use crate::TemporalEvaluationPlan;
pub use crate::freeze_product_evaluation_plan_v1;
pub use crate::freeze_product_outcome_plan_v1;
pub use crate::reconcile_product_attempt_holdout_v1;
pub use crate::reconcile_product_attempt_publication_v1;
