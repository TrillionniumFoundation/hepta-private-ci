//! Canonical prompt-selection policy with sealed verified type-state.
//!
//! Public V1 receipt structures remain available as raw wire values. The active
//! operations return private-field verified wrappers and no product boundary
//! accepts a caller-constructed intermediate value.

#[path = "canonical_raw.rs"]
mod raw;
#[path = "canonical_digest.rs"]
mod digest;
#[path = "canonical_verified.rs"]
mod verified;
#[path = "canonical_solver.rs"]
mod solver;
#[path = "canonical_runtime.rs"]
mod runtime;
#[path = "canonical_codec.rs"]
mod codec;

pub use codec::*;

pub use raw::MAX_CANONICAL_INTERACTION_EDGES;
pub use raw::MAX_CANONICAL_PROMPT_FACTORS;
pub use raw::MAX_CANONICAL_SELECTED_FACTORS;
pub use raw::MAX_CANONICAL_TOKEN_BUDGET;
pub use raw::PromptCandidateBindingV1;
pub use raw::PromptCandidateSetReceiptV1;
pub use raw::PromptConfidenceIntervalV1;
pub use raw::PromptDecisionBoundaryV1;
pub use raw::PromptExerciseActionV1;
pub use raw::PromptOptimalityDisclosureV1;
pub use raw::PromptPortfolioReceiptV1;
pub use raw::PromptPricingPolicyV1;
pub use raw::PromptPricingReceiptV1;
pub use raw::PromptSelectionMethodV1;
pub use raw::PricedPromptCandidateV1;

pub use raw::CanonicalPromptError as RawCanonicalPromptError;
pub use raw::EnumeratedPromptCandidatesV1 as RawEnumeratedPromptCandidatesV1;
pub use raw::PricedPromptCandidatesV1 as RawPricedPromptCandidatesV1;
pub use raw::PromptEnumerationRequestV1 as RawPromptEnumerationRequestV1;
pub use raw::PromptExerciseDecisionV1 as RawPromptExerciseDecisionV1;
pub use raw::PromptExerciseRequestV1 as RawPromptExerciseRequestV1;
pub use raw::PromptPairUtilityEvidenceV1 as RawPromptPairUtilityEvidenceV1;
pub use raw::PromptPortfolioRequestV1 as RawPromptPortfolioRequestV1;
pub use raw::PromptPricingEvidenceV1 as RawPromptPricingEvidenceV1;
pub use raw::SelectedPromptPortfolioV1 as RawSelectedPromptPortfolioV1;

pub use runtime::CanonicalPromptPlanInputsV1;
pub use runtime::CanonicalPromptPlanV1;
pub use runtime::PromptExerciseRequestV1;
pub use runtime::build_canonical_prompt_plan_v1;
pub use runtime::exercise_v1;

pub use solver::PromptCandidateDecisionAuditV1;
pub use solver::PromptCandidateDispositionV1;
pub use solver::PromptExerciseAuditV1;
pub use solver::PromptExercisePolicyV1;
pub use solver::PromptExerciseRejectionReasonV1;
pub use solver::PromptOptimalityAuditV1;
pub use solver::PromptPairUtilityEvidenceV1;
pub use solver::PromptPortfolioAuditV1;
pub use solver::PromptPortfolioRequestV1;
pub use solver::PromptSelectionTerminationV1;
pub use solver::SelectedPromptPortfolioV1;
pub use solver::VerifiedPromptExerciseDecisionV1;
pub use solver::VerifiedPromptExerciseDecisionV1 as PromptExerciseDecisionV1;
pub use solver::pair_utility_evidence_signing_payload_v1;
pub use solver::select_portfolio_v1;

pub use verified::CanonicalPromptError;
pub use verified::EnumeratedPromptCandidatesV1;
pub use verified::PricedPromptCandidatesV1;
pub use verified::PromptEnumerationRequestV1;
pub use verified::PromptPricingEvidenceV1;
pub use verified::PromptPricingUnavailableReasonV1;
pub use verified::PromptUnavailablePricingV1;
pub use verified::enumerate_factors_v1;
pub use verified::price_factors_v1;
pub use verified::pricing_evidence_signing_payload_v1;

#[cfg(test)]
#[path = "canonical_codec_tests.rs"]
mod codec_tests;

#[cfg(test)]
#[path = "canonical_verified_security_tests.rs"]
mod verified_tests;
