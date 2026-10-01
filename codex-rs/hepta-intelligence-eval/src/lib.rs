//! Independent deterministic candidate evaluation. Eligibility is not promotion.
#![forbid(unsafe_code)]

#[cfg(test)]
extern crate self as tempfile;

#[cfg(any(test, feature = "trusted-inprocess-eval"))]
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

mod calibration_cycle_scope;
mod calibration_preflight;
pub use calibration_preflight::CalibrationPreflightDispositionV1;
pub use calibration_preflight::CalibrationPreflightError;
pub use calibration_preflight::SignedCalibrationPreflightDecisionV1;
pub use calibration_preflight::SignedCalibrationPreflightRequestV1;
pub use calibration_preflight::calibration_cycle_preflight_signing_payload_v2;
pub use calibration_preflight::calibration_preflight_signing_payload_v1;
pub use calibration_preflight::decide_with_signed_calibration_cycle_v2;
pub use calibration_preflight::decide_with_signed_calibration_preflight_v1;
mod attempt_durability;
mod attempt_journal;
mod attempt_recovery;
mod closure;
mod durable_holdout;
mod fenced_holdout;
mod fenced_holdout_file;
mod holdout_journal;
mod ndu_convergence;
mod ndu_well_posedness;
#[cfg(test)]
mod test_tempfile;
pub use attempt_durability::DurableProductEvaluationAttemptJournalV1;
pub use attempt_journal::AnchoredProductEvaluationAttemptJournalV1;
pub use attempt_journal::InMemoryProductEvaluationAttemptJournalV1;
pub use attempt_journal::LockedFileProductEvaluationAttemptJournalV1;
pub use attempt_journal::ProductEvaluationAttemptAnchorStoreV1;
pub use attempt_journal::ProductEvaluationAttemptAnchorV1;
pub use attempt_journal::ProductEvaluationAttemptJournalErrorV1;
pub use attempt_journal::ProductEvaluationAttemptJournalV1;
pub use attempt_journal::ProductEvaluationAttemptPhaseV1;
pub use attempt_journal::ProductEvaluationAttemptReceiptV1;
pub use attempt_journal::ProductEvaluationAttemptTransitionV1;
pub use attempt_recovery::ProductAttemptRecoveryErrorV1;
pub use attempt_recovery::reconcile_product_attempt_holdout_v1;
pub use attempt_recovery::reconcile_product_attempt_publication_v1;
pub use durable_holdout::DurableFinalHoldoutJournalV1;
pub use durable_holdout::DurableHoldoutError;
pub use durable_holdout::HoldoutAnchorAuthorityV1;
pub use durable_holdout::HoldoutAnchorV1;
pub use fenced_holdout::FencedFinalHoldoutOwnerV1;
pub use fenced_holdout::FencedHoldoutError;
pub use fenced_holdout::FinalHoldoutCasAnchorV1;
pub use fenced_holdout::FinalHoldoutCasRecordV1;
pub use fenced_holdout::FinalHoldoutCasStoreError;
pub use fenced_holdout::FinalHoldoutCasStoreV1;
pub use fenced_holdout::HoldoutFenceIssuerV1;
pub use fenced_holdout::HoldoutWriterFenceV1;
pub use fenced_holdout_file::LockedFileCasCapacityV1;
pub use fenced_holdout_file::LockedFileCasCompactionReceiptV1;
pub use fenced_holdout_file::LockedFileCasErrorV1;
pub use fenced_holdout_file::LockedFileFinalHoldoutCasStoreV1;
#[cfg(test)]
pub(crate) use test_tempfile::NamedTempFile;
mod ope;
mod paired_supervised_estimate;
mod paired_supervised_facade;
mod paired_supervised_host_clock;
mod paired_supervised_plan;
mod paired_supervised_qualification;
mod paired_supervised_registration;
mod paired_supervised_runner;
mod paired_supervised_scope;
mod paired_supervised_values;
mod product_evidence_file;
mod product_registration;
pub use paired_supervised_estimate::PairedClassObservationV1;
pub use paired_supervised_estimate::PairedNativeObservationV1;
pub use paired_supervised_estimate::PairedObservationCutV1;
pub use paired_supervised_estimate::PairedObservedMetricV1;
pub use paired_supervised_estimate::PairedSupervisedEstimateV1;
pub use paired_supervised_estimate::PairedTaskObservationV1;
pub use paired_supervised_estimate::paired_observation_cut_signing_payload_v1;
pub use paired_supervised_facade::RegisteredPairedEvaluationRunnerV1;
pub use paired_supervised_plan::PairedBenchmarkPolicyV1;
pub use paired_supervised_plan::PairedEvidenceMetricsV1;
pub use paired_supervised_plan::PairedMetricContractV1;
pub use paired_supervised_plan::PairedMetricKindV1;
pub use paired_supervised_plan::PairedRuntimeBindingV1;
pub use paired_supervised_plan::PairedSupervisedErrorV1;
pub use paired_supervised_plan::PairedSupervisedPlanInputsV1;
pub use paired_supervised_plan::PairedSupervisedPlanV1;
pub use paired_supervised_plan::PairedTaskBindingV1;
pub use paired_supervised_plan::freeze_paired_supervised_plan_v1;
pub mod product;
mod product_runner;
mod reconciled_sink;
mod recorded_publication;
mod recorded_runner;
mod self_evolution_selection;
mod self_evolution_selection_v2;
pub use self_evolution_selection_v2::PreparedSelfEvolutionSelectionV2;
pub use self_evolution_selection_v2::SelfEvolutionSelectionInputsV2;
pub use self_evolution_selection_v2::SelfEvolutionSelectionPolicyV2;
pub use self_evolution_selection_v2::SelfEvolutionSelectionReceiptV2;
pub use self_evolution_selection_v2::VerifiedSelfEvolutionRollbackV2;
pub use self_evolution_selection_v2::VerifiedSelfEvolutionSelectionV2;
pub use self_evolution_selection_v2::admit_self_evolution_rollback_v2;
pub use self_evolution_selection_v2::admit_self_evolution_selection_v2;
pub use self_evolution_selection_v2::prepare_self_evolution_selection_v2;
pub use self_evolution_selection_v2::rollback_signing_payload_v2;
pub use self_evolution_selection_v2::selection_signing_payload_v2;
mod sequential;
mod signed_admission;
mod signed_evaluation;
mod task_execution_lineage;
mod task_lineage;
mod task_lineage_plan;
mod temporal_evaluation;
mod temporal_fold;

pub use task_execution_lineage::TaskExecutionRegistrationV1;
pub use task_execution_lineage::TaskExecutionWindowV1;
pub use task_execution_lineage::TaskObservedOutcomeV1;
pub use task_execution_lineage::TaskPredictionEventV1;
pub use task_execution_lineage::TaskPredictionLineageV1;
pub use task_lineage::FrozenTaskSourceLineageV1;
pub use task_lineage::TaskCrossFoldInputsV1;
pub use task_lineage::TaskLineageError;
pub use task_lineage::TaskSourceRecordV1;
pub use task_lineage::TaskSourceScopeV1;

pub use closure::CrossFoldPartitionV1;
pub use closure::CrossFoldPlanReceiptV1;
pub use closure::CrossFoldPlanV1;
pub use closure::EvaluationClaimScopeV1;
pub use closure::EvaluationClosureError;
pub use closure::EvaluationDirectionV1;
pub use closure::EvaluationIntervalV1;
pub use closure::FinalHoldoutRegistry;
pub use closure::HoldoutUseDispositionV1;
pub use closure::HoldoutUseReceiptV1;
pub use closure::IndependentEvaluationBundleV1;
pub use closure::IndependentEvaluationDecisionV1;
pub use closure::IndependentEvaluationDispositionV1;
pub use closure::MetricContractV1;
pub use closure::MetricGateV1;
pub use closure::MetricRoleContractV2;
pub use closure::MetricRoleV2;
#[cfg(any(test, feature = "trusted-inprocess-eval"))]
pub(crate) use closure::decide_independently;
pub(crate) use closure::decide_independently_v2;
pub use closure::freeze_cross_fold_plan;
pub use closure::freeze_cross_fold_plan_v2;

/// Trusted in-process compatibility surface.
///
/// This module is absent from default builds. It must never be used as a
/// qualification or production ingress because its direct decision functions
/// consume asserted principals rather than signature-verified evidence.
#[cfg(feature = "trusted-inprocess-eval")]
pub mod trusted_inprocess {
    use super::*;

    /// Legacy threshold comparator retained only for bounded compatibility tests.
    #[deprecated(
        note = "trusted in-process compatibility only; production must use signed evaluation admission"
    )]
    pub fn evaluate_legacy_inprocess_v1(
        request: EvaluationRequest,
    ) -> Result<EvaluationReceipt, Error> {
        super::evaluate(request)
    }

    /// Direct V1 evaluator for trusted in-process compatibility only.
    pub fn decide_independently(
        bundle: IndependentEvaluationBundleV1,
        now: u64,
    ) -> Result<IndependentEvaluationDecisionV1, EvaluationClosureError> {
        super::decide_independently(bundle, now)
    }

    /// Direct V2 evaluator for trusted in-process compatibility only.
    pub fn decide_independently_v2(
        bundle: IndependentEvaluationBundleV1,
        metric_roles: Vec<MetricRoleContractV2>,
        now: u64,
    ) -> Result<IndependentEvaluationDecisionV1, EvaluationClosureError> {
        super::decide_independently_v2(bundle, metric_roles, now)
    }
}
pub use holdout_journal::FinalHoldoutJournalError;
pub use holdout_journal::FinalHoldoutJournalReceiptV1;
pub use holdout_journal::FinalHoldoutJournalRecordV1;
pub use holdout_journal::FinalHoldoutJournalSnapshotV1;
pub use holdout_journal::FinalHoldoutJournalV1;
pub use ndu_convergence::NduConvergenceCertificateV1;
pub use ndu_convergence::NduConvergenceDecisionV1;
pub use ndu_convergence::NduConvergenceError;
pub use ndu_convergence::NduConvergenceEvidenceV1;
pub use ndu_convergence::NduMultipleSolutionDispositionV1;
pub use ndu_convergence::NduSubjectClassV1;
pub use ndu_convergence::decide_ndu_convergence_v1;
pub use ndu_convergence::ndu_convergence_evaluator_signing_payload_v1;
pub use ndu_convergence::ndu_convergence_producer_signing_payload_v1;
pub use ndu_well_posedness::NduAssumptionEvidenceV1;
pub use ndu_well_posedness::NduConditionalMeanEvidenceV1;
pub use ndu_well_posedness::NduContinuityScopeV1;
pub use ndu_well_posedness::NduWellPosednessCertificateV1;
pub use ndu_well_posedness::NduWellPosednessDecisionV1;
pub use ndu_well_posedness::NduWellPosednessError;
pub use ndu_well_posedness::NduWellPosednessEvidenceV1;
pub use ndu_well_posedness::decide_ndu_well_posedness_v1;
pub use ndu_well_posedness::ndu_well_posedness_evaluator_signing_payload_v1;
pub use ndu_well_posedness::ndu_well_posedness_producer_signing_payload_v1;
pub use ope::ClusterAssignment;
pub use ope::ClusterConfidenceError;
pub use ope::ClusterConfidencePlan;
pub use ope::ClusterOpeEstimate;
pub use ope::OpeAction;
pub use ope::OpeError;
pub use ope::OpeEstimate;
pub use ope::OpeInterval;
pub use ope::OpePlan;
pub use ope::OpeRow;
pub use ope::estimate_cluster_intervals;
pub use ope::estimate_ope;
pub use product_evidence_file::LockedFileProductEvidenceSinkV1;
pub use product_evidence_file::ProductPublicationRecoveryV1;
pub use product_registration::AuthenticatedProductRegistrationV1;
pub use product_registration::ProductRegistrationBindingV1;
pub use product_registration::product_registration_signing_payload_v1;
pub use product_runner::FinalHoldoutProviderV1;
pub use product_runner::ProductEvaluationError;
#[cfg(feature = "trusted-inprocess-eval")]
pub use product_runner::ProductEvaluationRunnerV1;
pub use product_runner::ProductEvidenceSinkErrorV1;
pub use product_runner::ProductFrozenEvaluationPlanV1;
pub use product_runner::ProductMetricSourceContractV1;
pub use product_runner::ProductMetricSourceV1;
pub use product_runner::ProductProviderErrorV1;
pub use product_runner::ProductQualificationContextV1;
pub use product_runner::ProductQualificationEvidenceSinkV1;
pub use product_runner::ProductQualificationReceiptV1;
pub use product_runner::ProductTemporalEvaluationReceiptV1;
pub use product_runner::ProductTimingEvidenceV1;
pub use product_runner::TemporalComparisonInputsV1;
pub use product_runner::freeze_product_evaluation_plan_v1;
pub use reconciled_sink::ProductQualificationPublicationRecordV1;
pub use reconciled_sink::ProductQualificationPublicationRequestV1;
pub use reconciled_sink::ProductQualificationPublicationStoreErrorV1;
pub use reconciled_sink::ProductQualificationPublicationStoreV1;
pub use reconciled_sink::ReconciledProductQualificationSinkV1;
pub use recorded_runner::RecordedProductEvaluationErrorV1;
pub use recorded_runner::RecordedProductEvaluationRunnerV1;
pub use self_evolution_selection::PreparedSelfEvolutionSelectionV1;
pub use self_evolution_selection::SelfEvolutionSelectionError;
pub use self_evolution_selection::SelfEvolutionSelectionPolicyV1;
pub use self_evolution_selection::SelfEvolutionSelectionReceiptV1;
pub use self_evolution_selection::SelfEvolutionSelectionRequestV1;
pub use self_evolution_selection::VerifiedSelfEvolutionRollbackV1;
pub use self_evolution_selection::VerifiedSelfEvolutionSelectionV1;
pub use self_evolution_selection::admit_self_evolution_rollback_v1;
pub use self_evolution_selection::admit_self_evolution_selection_v1;
pub use self_evolution_selection::prepare_self_evolution_selection_v1;
pub use self_evolution_selection::rollback_signing_payload_v1;
pub use self_evolution_selection::selection_signing_payload_v1;
pub use sequential::DepthSupport;
pub use sequential::FiniteHorizonEstimand;
pub use sequential::SequentialError;
pub use sequential::SequentialEstimate;
pub use sequential::SequentialEvidenceGap;
pub use sequential::SequentialPlan;
pub use sequential::TerminalRewardConvention;
pub use sequential::Trajectory;
pub use sequential::TrajectoryAction;
pub use sequential::TrajectoryBoundary;
pub use sequential::TrajectoryClaimScope;
pub use sequential::TrajectoryEstimate;
pub use sequential::TrajectoryStep;
pub use sequential::estimate_sequential;
pub use signed_admission::SignedEligibilityAdmissionError;
pub use signed_admission::SignedEligibilityAdmissionReceiptV1;
pub use signed_admission::admit_signed_eligibility_v2;
pub use signed_evaluation::SignedEvaluationDecisionV1;
pub use signed_evaluation::SignedEvaluationError;
pub use signed_evaluation::SignedEvaluationEvidenceV1;
#[cfg(test)]
pub(crate) use signed_evaluation::decide_with_signed_evidence_v1;
pub(crate) use signed_evaluation::decide_with_signed_evidence_v2;
pub use signed_evaluation::evaluation_signing_payload_v1;
pub use signed_evaluation::evaluation_signing_payload_v2;

pub use temporal_evaluation::TemporalEvaluationError;
pub use temporal_evaluation::TemporalEvaluationPlan;
pub use temporal_evaluation::TemporalEvaluationReceipt;
pub use temporal_evaluation::evaluate_temporal_holdout;
pub use temporal_fold::HeldOutPrediction;
pub use temporal_fold::HeldOutTarget;
pub use temporal_fold::OutcomeTrainingSample;
pub use temporal_fold::TemporalFoldError;
pub use temporal_fold::TemporalFoldPlan;
pub use temporal_fold::TemporalFoldReceipt;
pub use temporal_fold::fit_temporal_fold;

#[cfg(any(test, feature = "trusted-inprocess-eval"))]
const MAX_METRICS: usize = 128;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Direction {
    Maximize,
    Minimize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MetricComparison {
    pub metric_id: StableId,
    pub direction: Direction,
    pub candidate: FixedQ32,
    pub baseline: FixedQ32,
    pub minimum_delta: FixedQ32,
    /// Classification retained in the immutable evidence receipt. Every
    /// registered threshold is eligibility-gating; this flag does not erase a
    /// non-hard threshold or silently strengthen its preregistered value.
    pub hard: bool,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvaluationRequest {
    pub evaluation_id: StableId,
    pub evaluator_id: StableId,
    pub candidate_id: StableId,
    pub candidate_producer_id: StableId,
    pub baseline_id: StableId,
    pub objective_digest: Digest32,
    pub comparisons: Vec<MetricComparison>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Disposition {
    EligibleForFurtherReview,
    Ineligible,
    InsufficientEvidence,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvaluationReceipt {
    pub evaluation_id: StableId,
    pub candidate_id: StableId,
    pub baseline_id: StableId,
    pub disposition: Disposition,
    pub failed_metrics: Vec<StableId>,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    SelfEvaluation,
    EmptyDigest(&'static str),
    MetricLimitExceeded,
    DuplicateMetric(String),
    Arithmetic,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for Error {}

#[cfg(any(test, feature = "trusted-inprocess-eval"))]
fn evaluate(mut request: EvaluationRequest) -> Result<EvaluationReceipt, Error> {
    if request.evaluator_id == request.candidate_producer_id {
        return Err(Error::SelfEvaluation);
    }
    if request.objective_digest.is_zero() {
        return Err(Error::EmptyDigest("objective"));
    }
    if request.comparisons.len() > MAX_METRICS {
        return Err(Error::MetricLimitExceeded);
    }

    request
        .comparisons
        .sort_by(|left, right| left.metric_id.cmp(&right.metric_id));
    let mut seen = BTreeSet::new();
    let mut failed_metrics = Vec::new();
    let mut insufficient = request.comparisons.is_empty();
    for metric in &request.comparisons {
        if !seen.insert(metric.metric_id.clone()) {
            return Err(Error::DuplicateMetric(metric.metric_id.to_string()));
        }
        if metric.support_digest.is_zero() {
            insufficient = true;
            continue;
        }
        let delta = match metric.direction {
            Direction::Maximize => subtract(metric.candidate, metric.baseline)?,
            Direction::Minimize => subtract(metric.baseline, metric.candidate)?,
        };
        if delta.raw() < metric.minimum_delta.raw() {
            failed_metrics.push(metric.metric_id.clone());
        }
    }

    let disposition = if !failed_metrics.is_empty() {
        Disposition::Ineligible
    } else if insufficient {
        Disposition::InsufficientEvidence
    } else {
        Disposition::EligibleForFurtherReview
    };
    let evidence_digest = digest(&request, disposition, &failed_metrics);
    Ok(EvaluationReceipt {
        evaluation_id: request.evaluation_id,
        candidate_id: request.candidate_id,
        baseline_id: request.baseline_id,
        disposition,
        failed_metrics,
        evidence_digest,
    })
}

#[cfg(any(test, feature = "trusted-inprocess-eval"))]
fn subtract(left: FixedQ32, right: FixedQ32) -> Result<FixedQ32, Error> {
    let raw = i128::from(left.raw()) - i128::from(right.raw());
    Ok(FixedQ32::from_raw(
        i64::try_from(raw).map_err(|_| Error::Arithmetic)?,
    ))
}

#[cfg(any(test, feature = "trusted-inprocess-eval"))]
fn digest(request: &EvaluationRequest, disposition: Disposition, failed: &[StableId]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.intelligence-eval.v1");
    for id in [
        &request.evaluation_id,
        &request.evaluator_id,
        &request.candidate_id,
        &request.candidate_producer_id,
        &request.baseline_id,
    ] {
        push_id(&mut bytes, id);
    }
    bytes.extend_from_slice(request.objective_digest.as_array());
    bytes.push(match disposition {
        Disposition::EligibleForFurtherReview => 0,
        Disposition::Ineligible => 1,
        Disposition::InsufficientEvidence => 2,
    });
    for metric in &request.comparisons {
        push_id(&mut bytes, &metric.metric_id);
        bytes.push(match metric.direction {
            Direction::Maximize => 0,
            Direction::Minimize => 1,
        });
        bytes.extend_from_slice(&metric.candidate.raw().to_be_bytes());
        bytes.extend_from_slice(&metric.baseline.raw().to_be_bytes());
        bytes.extend_from_slice(&metric.minimum_delta.raw().to_be_bytes());
        bytes.push(u8::from(metric.hard));
        bytes.extend_from_slice(metric.support_digest.as_array());
    }
    for id in failed {
        push_id(&mut bytes, id);
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;

mod longitudinal_time;
pub use longitudinal_time::LongitudinalTimeEvidenceV1;
pub use longitudinal_time::ObservedFutureWindowV1;
pub(crate) use longitudinal_time::decide_with_signed_longitudinal_evidence_v3;
pub use longitudinal_time::future_window_signing_payload_v1;
pub use longitudinal_time::longitudinal_evaluation_signing_payload_v3;

#[cfg(test)]
#[path = "signed_qualification_e2e_tests.rs"]
mod signed_qualification_e2e_tests;

#[cfg(all(target_os = "linux", feature = "fixed-eval-host"))]
mod fixed_calibration_cycle_evaluator;
#[cfg(all(target_os = "linux", feature = "fixed-eval-host"))]
mod fixed_calibration_host;
#[cfg(all(target_os = "linux", feature = "fixed-eval-host"))]
pub use fixed_calibration_host::initialize_fixed_evaluator_key;
#[cfg(all(target_os = "linux", feature = "fixed-eval-host"))]
pub use fixed_calibration_host::run_fixed_calibration_evaluator;

#[cfg(all(target_os = "linux", feature = "fixed-eval-host"))]
mod fixed_calibration_cycle_host;
#[cfg(all(target_os = "linux", feature = "fixed-eval-host"))]
mod fixed_product_host;
#[cfg(all(target_os = "linux", feature = "fixed-eval-host"))]
pub use fixed_calibration_cycle_host::resume_fixed_calibration_evaluation;
#[cfg(all(target_os = "linux", feature = "fixed-eval-host"))]
pub use fixed_calibration_cycle_host::run_fixed_calibration_cycle;
#[cfg(all(target_os = "linux", feature = "fixed-eval-host"))]
mod fixed_product_source;
#[cfg(all(target_os = "linux", feature = "fixed-eval-host"))]
pub use fixed_product_host::inspect_fixed_product_evaluation;

#[cfg(all(target_os = "linux", feature = "fixed-eval-host"))]
mod fixed_holdout_custody;
#[cfg(all(target_os = "linux", feature = "fixed-eval-host"))]
pub use fixed_holdout_custody::inspect_fixed_source_holdout;
#[cfg(all(target_os = "linux", feature = "fixed-eval-host"))]
pub use fixed_holdout_custody::prepare_fixed_source_holdout;

pub use paired_supervised_qualification::ProductPairedQualificationReceiptV1;
pub use paired_supervised_qualification::paired_evaluation_signing_payload_v1;
pub use paired_supervised_registration::AuthenticatedPairedRegistrationV1;
pub use paired_supervised_registration::paired_registration_signing_payload_v1;
pub use paired_supervised_runner::PairedFinalHoldoutProviderV1;
pub use paired_supervised_runner::ProductPairedEvaluationReceiptV1;
pub use paired_supervised_runner::SignedPairedObservationCutV1;

#[cfg(test)]
mod paired_supervised_test_support;
#[cfg(test)]
mod paired_supervised_tests;

#[cfg(test)]
mod paired_supervised_boundary_tests;

#[cfg(test)]
mod paired_supervised_current_trust_tests;

#[cfg(test)]
mod calibration_cycle_tests;
mod outcome_channels;
mod outcome_receipt;
pub use outcome_channels::FinalOutcomeHoldoutProviderV1;
pub use outcome_channels::ProductFrozenOutcomePlanV1;
pub use outcome_channels::ProductOutcomeChannelContractV1;
pub use outcome_channels::ProductOutcomeInputV1;
pub use outcome_channels::freeze_product_outcome_plan_v1;
pub use outcome_channels::product_outcome_inputs_digest_v1;
pub use outcome_receipt::ProductOutcomeEstimateV1;
pub use outcome_receipt::ProductOutcomeEvaluationReceiptV1;
pub use outcome_receipt::ProductOutcomeQualificationReceiptV1;
