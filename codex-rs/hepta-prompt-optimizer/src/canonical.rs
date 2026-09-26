//! Sealed canonical prompt selection and optimization pipeline.
//!
//! Public callers can construct raw requests and evidence, but every stage result
//! is returned as a sealed verified handle. Downstream stages accept only those
//! handles and revalidate every digest and currentness fence at crate boundaries.

#[path = "canonical_raw.rs"]
mod raw;
#[path = "canonical_types.rs"]
mod types;
#[path = "canonical_selection.rs"]
mod selection;
#[path = "canonical_exercise.rs"]
mod exercise;
#[path = "canonical_codec.rs"]
mod codec;

pub use codec::*;
pub use exercise::exercise_v1;
pub use selection::select_portfolio_v1;
pub use types::*;

pub use raw::MAX_CANONICAL_INTERACTION_EDGES;
pub use raw::MAX_CANONICAL_PROMPT_FACTORS;
pub use raw::MAX_CANONICAL_SELECTED_FACTORS;
pub use raw::MAX_CANONICAL_TOKEN_BUDGET;
pub use raw::PromptCandidateBindingV1;
pub use raw::PromptCandidateSetReceiptV1;
pub use raw::PromptConfidenceIntervalV1;
pub use raw::PromptDecisionBoundaryV1;
pub use raw::PromptExerciseActionV1;
pub use raw::PromptExerciseDecisionV1 as RawPromptExerciseDecisionV1;
pub use raw::PromptOptimalityDisclosureV1;
pub use raw::PromptPortfolioReceiptV1;
pub use raw::PromptPortfolioRequestV1;
pub use raw::PromptPricingPolicyV1;
pub use raw::PromptPricingReceiptV1;
pub use raw::PromptSelectionMethodV1;
pub use raw::PricedPromptCandidateV1;
pub use raw::candidate_completeness_signing_payload_v1;

pub use raw::EnumeratedPromptCandidatesV1 as RawEnumeratedPromptCandidatesV1;
pub use raw::PricedPromptCandidatesV1 as RawPricedPromptCandidatesV1;
pub use raw::SelectedPromptPortfolioV1 as RawSelectedPromptPortfolioV1;

pub type EnumeratedPromptCandidatesV1 = VerifiedEnumeratedPromptCandidatesV1;
pub type PricedPromptCandidatesV1 = VerifiedPricedPromptCandidatesV1;
pub type SelectedPromptPortfolioV1 = VerifiedSelectedPromptPortfolioV1;
pub type PromptExerciseDecisionV1 = VerifiedPromptExerciseDecisionV1;

#[cfg(test)]
#[path = "canonical_facade_tests.rs"]
mod tests;
