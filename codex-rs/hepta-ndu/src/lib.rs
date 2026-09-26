//! Deterministic NDU feasibility, policy-bound aggregation, tolerant Pareto
//! comparison and bounded preference primitives, with a separately versioned
//! native shadow covariance regression profile.
//!
//! Mathematical evaluations and local solver receipts are deny-all advisory
//! evidence: they are never operations, independent convergence certificates,
//! selections, promotions, releases or external effects. The separately named
//! authenticated owner may consume externally issued final-use grants for its
//! durable projection mutations; it cannot mint or widen those grants.

#![forbid(unsafe_code)]

mod candidate_quarantine;
mod coefficient_profile;
mod conditional_moments;
mod covariance;
mod covariance_profile;
mod error;
mod evaluation_digest;
mod evaluator;
mod fixed;
mod hierarchy;
mod model;
mod operational_metrics;
mod owner;
mod owner_binding;
mod preference;
mod projection_journal;
mod projection_store;
mod protocol;
mod recursive;
mod scoring;
mod validated_scalarization;
mod z_conversion;

pub use candidate_quarantine::CandidateQuarantineReasonV1;
pub use candidate_quarantine::NduEvaluationReceiptV3;
pub use candidate_quarantine::QuarantinedCandidateV1;
pub use candidate_quarantine::evaluate_candidates_with_quarantine;
pub use coefficient_profile::AdmittedNduCoefficientProfileV1;
pub use coefficient_profile::NduCoefficientProfileError;
pub use coefficient_profile::NduCoefficientProfileV1;
pub use coefficient_profile::NduCoefficientProjectionV1;
pub use coefficient_profile::admit_ndu_coefficient_profile;
pub use coefficient_profile::project_z_estimate_to_coefficient_q24;
pub use coefficient_profile::validate_ndu_coefficient_projection_v1;
pub use conditional_moments::ConditionalMomentSampleV1;
pub use conditional_moments::ConditionalMomentsV1;
pub use conditional_moments::estimate_conditional_moments;
pub use covariance::ZEstimateV1;
pub use covariance::solve_backward_regression;
pub use covariance_profile::AdmittedCovarianceProfileV1;
pub use covariance_profile::CovarianceConventionV1;
pub use covariance_profile::CovarianceError;
pub use covariance_profile::NduCovarianceProfileV1;
pub use covariance_profile::admit_covariance_profile;
pub use error::NduError;
pub use evaluator::canonical_evaluation_policy_digest;
pub use evaluator::canonical_scalarization_digest;
pub use evaluator::canonical_utility_profile_digest;
#[allow(deprecated)]
pub use evaluator::evaluate_candidates;
pub use evaluator::evaluate_candidates_with_policy;
pub use evaluator::legacy_evaluation_policy;
pub use fixed::mul_q32_ties_even;
pub use hierarchy::HierarchyNodeV1;
pub use hierarchy::HierarchySnapshotV1;
pub use hierarchy::HierarchyValidationErrorV1;
pub use hierarchy::hierarchy_snapshot_digest;
pub use hierarchy::validate_staged_updates_against_snapshot;
pub use model::AggregationOperator;
pub use model::AxisAggregationRule;
pub use model::AxisDirection;
pub use model::AxisLimit;
pub use model::AxisValue;
pub use model::CandidateRejectionReason;
pub use model::CandidateUtility;
pub use model::ContributionSet;
pub use model::EvaluationDisposition;
pub use model::EvaluationPolicyV1;
pub use model::FeasibilityPosture;
pub use model::NduEvaluationReceipt;
pub use model::NduEvaluationReceiptV2;
pub use model::RejectedCandidate;
pub use model::RequiredOrganSet;
pub use model::ScalarizationProfile;
pub use model::SubjectClass;
pub use model::UtilityContribution;
pub use model::UtilityProfile;
pub use operational_metrics::NduBackupPolicyV1;
pub use operational_metrics::NduOperationalMetricSnapshotV1;
pub use operational_metrics::NduOperationalMetricsV1;
pub use operational_metrics::NduOperationsError;
pub use operational_metrics::NduRestoreDrillReceiptV1;
pub use operational_metrics::validate_backup_policy_v1;
pub use operational_metrics::validate_restore_drill_receipt_v1;
pub use owner::NduAuthenticatedEvaluationReceiptV1;
pub use owner::NduAuthenticatedOwnerV1;
pub use owner::NduOwnerContextV1;
pub use owner::NduOwnerError;
pub use owner::NduOwnerMutationV1;
pub use owner::NduProductionPolicyV1;
pub use preference::NduSolverIterationReceipt;
pub use preference::NduSolverTerminationReceipt;
pub use preference::PreferenceState;
pub use preference::SolveDisposition;
pub use preference::UpdateGeneration;
pub use preference::solve_preference_target;
pub use preference::validate_staged_updates;
pub use projection_journal::NduProjectionEntryV1;
pub use projection_journal::NduProjectionJournalError;
pub use projection_journal::NduProjectionJournalV1;
pub use projection_journal::NduProjectionKindV1;
pub use projection_store::NduProjectionStoreError;
pub use projection_store::NduProjectionStoreV1;
pub use protocol::NduIterationContextV1;
pub use protocol::NduIterationReceiptV1;
pub use protocol::bind_solver_iteration_receipt_v1;
pub use protocol::solve_preference_target_with_context_v1;
pub use recursive::RecursiveUtilityError;
pub use recursive::RecursiveUtilityPath;
pub use recursive::RecursiveUtilityReceipt;
pub use recursive::UtilityEvent;
pub use recursive::evaluate_recursive_utility;
pub use validated_scalarization::ValidatedScalarizationProfileV1;
pub use z_conversion::AdmittedZConversionProfileV1;
pub use z_conversion::NduZConversionProfileV1;
pub use z_conversion::ZConversionError;
pub use z_conversion::ZCoordinateConventionV1;
pub use z_conversion::ZQ24ConversionReceiptV1;
pub use z_conversion::admit_z_conversion_profile;
pub use z_conversion::convert_z_to_original_q24;
