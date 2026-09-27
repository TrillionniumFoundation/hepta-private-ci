//! Sealed verification states for the canonical prompt optimizer.
//!
//! The public structs in `canonical` remain transport/compatibility values. This
//! module is the production admission surface: every raw value is recomputed,
//! every owner/evidence binding is checked, and downstream stages receive opaque
//! verified wrappers rather than caller-constructed receipts.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_prompt_registry::PromptRegistry;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::canonical::CanonicalPromptError;
use crate::canonical::EnumeratedPromptCandidatesV1;
use crate::canonical::PricedPromptCandidatesV1;
use crate::canonical::PromptEnumerationRequestV1;
use crate::canonical::PromptExerciseActionV1;
use crate::canonical::PromptExerciseDecisionV1;
use crate::canonical::PromptExerciseRequestV1;
use crate::canonical::PromptPairUtilityEvidenceV1;
use crate::canonical::PromptOptimalityDisclosureV1;
use crate::canonical::PromptPortfolioRequestV1;
use crate::canonical::PromptPricingEvidenceV1;
use crate::canonical::PromptPricingPolicyV1;
use crate::canonical::PromptSelectionMethodV1;
use crate::canonical::SelectedPromptPortfolioV1;
use crate::canonical::candidate_completeness_signing_payload_v1;
use crate::canonical::enumerate_factors_v1;
use crate::canonical::exercise_v1;
use crate::canonical::pair_utility_evidence_signing_payload_v1;
use crate::canonical::price_factors_v1;
use crate::canonical::pricing_evidence_signing_payload_v1;
use crate::canonical::select_portfolio_v1;
use crate::canonical::MAX_CANONICAL_PROMPT_FACTORS;
use crate::canonical::MAX_CANONICAL_SELECTED_FACTORS;
use crate::canonical::MAX_CANONICAL_TOKEN_BUDGET;

const EVIDENCE_SCOPE_DOMAIN: &[u8] = b"hepta.prompt-optimizer.evidence-scope.v2";
const EVIDENCE_LINEAGE_DOMAIN: &[u8] = b"hepta.prompt-optimizer.evidence-lineage.v2";
const MAX_EVIDENCE_ROWS: usize = MAX_CANONICAL_PROMPT_FACTORS;

include!("verified_types.rs");
include!("verified_pipeline.rs");
include!("verified_validation.rs");
include!("verified_digest.rs");
