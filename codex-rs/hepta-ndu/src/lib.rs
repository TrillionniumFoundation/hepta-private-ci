//! Deterministic NDU feasibility, policy-bound aggregation, tolerant Pareto
//! comparison and bounded preference primitives, with a separately versioned
//! native shadow covariance regression profile.
//!
//! This crate is authority-free: an advisory recommendation or local solver
//! receipt is never an operation, independent convergence certificate,
//! selection, promotion, release or external effect. The projection journal is
//! an owner-local durability reference, not a production writer activation.

#![forbid(unsafe_code)]

mod conditional_moments;
mod covariance;
mod covariance_profile;
mod error;
mod evaluation_digest;
mod evaluator;
mod fixed;
mod model;
mod preference;
mod projection_journal;
mod protocol;
mod recursive;
mod scoring;

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
pub use evaluator::evaluate_candidates;
pub use evaluator::evaluate_candidates_with_policy;
pub use evaluator::legacy_evaluation_policy;
pub use fixed::mul_q32_ties_even;
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
pub use protocol::NduIterationContextV1;
pub use protocol::NduIterationReceiptV1;
pub use protocol::bind_solver_iteration_receipt_v1;
pub use recursive::RecursiveUtilityError;
pub use recursive::RecursiveUtilityPath;
pub use recursive::RecursiveUtilityReceipt;
pub use recursive::UtilityEvent;
pub use recursive::evaluate_recursive_utility;
