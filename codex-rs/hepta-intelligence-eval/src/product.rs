//! Canonical, authority-free product qualification facade.
//!
//! This module narrows the supported product ingress without removing historical
//! top-level re-exports in the current compatibility window. It intentionally
//! omits the raw `ProductEvaluationRunnerV1`, direct decision primitives, and
//! in-memory attempt journal. Receipts produced through this facade remain
//! `DENY_ALL`; selection, activation, promotion, and release are external.

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
