//! Sealed, authenticated canonical prompt-optimization pipeline.
//!
//! The V1 module remains available for source compatibility, but product code
//! should enter through this module. Every stage validates and seals its input;
//! downstream stages accept only the sealed output of the preceding stage.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::ops::Deref;

use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_kg::KnowledgeRelationKindV2;
use codex_hepta_kg::KnowledgeRelationQueryV2;
use codex_hepta_kg::query_relations;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::validate_candidate_set_completeness;
use codex_hepta_learning_ledger::verify_signed_independent_roles_v1;
use codex_hepta_prompt_registry::PromptRegistry;
use codex_hepta_prompt_registry::PromptRegistryV2Error;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::canonical as v1;

pub use v1::MAX_CANONICAL_INTERACTION_EDGES;
pub use v1::MAX_CANONICAL_PROMPT_FACTORS;
pub use v1::MAX_CANONICAL_SELECTED_FACTORS;
pub use v1::MAX_CANONICAL_TOKEN_BUDGET;
pub use v1::PromptDecisionBoundaryV1;
pub use v1::PromptEnumerationRequestV1;
pub use v1::PromptExerciseActionV1;
pub use v1::PromptExerciseRequestV1;
pub use v1::PromptOptimalityDisclosureV1;
pub use v1::PromptPortfolioRequestV1;
pub use v1::PromptPricingPolicyV1;
pub use v1::PromptSelectionMethodV1;

const MAX_LOCAL_SEARCH_EVALUATIONS: u32 = 50_000;
const MAX_LOCAL_SEARCH_ROUNDS: u32 = 128;
const MAX_EXACT_FACTORS: usize = 18;
const MAX_EXACT_NODES: u32 = 300_000;
const PPM_ONE: u64 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum VerifiedPromptError {
    EmptyDigest(&'static str),
    CandidateLimit,
    CandidateOrder,
    CandidateBinding(String),
    ReceiptDigest(&'static str),
    Authority,
    ObjectiveMismatch,
    ScopeMismatch,
    TrustEpochMismatch,
    Evidence(String),
    EvidenceIndependence(String),
    EvidenceExpired,
    MissingEvidence(String),
    DuplicateEvidence(String),
    InvalidPricing(String),
    Graph(String),
    GraphDrift,
    InteractionProjectionIncomplete(u32),
    RequiredFactorUnavailable(String),
    PrerequisiteCycle(String),
    UnsatisfiableGraph(String),
    SelectionLimit,
    TokenBudgetLimit,
    PortfolioExpired,
    PortfolioIntegrity(&'static str),
    Stale(PromptStaleReasonV2),
    Unavailable(String),
    Corrupt(String),
    Indeterminate(String),
    Quarantined(String),
    Arithmetic,
    Codec(String),
    Legacy(v1::CanonicalPromptError),
}

impl fmt::Display for VerifiedPromptError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for VerifiedPromptError {}

impl From<v1::CanonicalPromptError> for VerifiedPromptError {
    fn from(value: v1::CanonicalPromptError) -> Self {
        Self::Legacy(value)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptEvidenceContextV2 {
    pub scope_digest: Digest32,
    pub objective_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub selection_grammar_digest: Digest32,
    pub generator_code_digest: Digest32,
    pub hard_filter_digest: Digest32,
    pub truncation_digest: Digest32,
    pub pricing_policy_digest: Digest32,
}

impl PromptEvidenceContextV2 {
    pub fn validate(&self) -> Result<(), VerifiedPromptError> {
        for (name, digest) in [
            ("scope", self.scope_digest),
            ("objective", self.objective_digest),
            ("candidate_set", self.candidate_set_digest),
            ("registry_snapshot", self.registry_snapshot_digest),
            ("generation_vector", self.generation_vector_digest),
            ("model_tuple", self.model_tuple_digest),
            ("selection_grammar", self.selection_grammar_digest),
            ("generator_code", self.generator_code_digest),
            ("hard_filter", self.hard_filter_digest),
            ("truncation", self.truncation_digest),
            ("pricing_policy", self.pricing_policy_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-optimizer.evidence-context.v2".to_vec();
        for digest in [
            self.scope_digest,
            self.objective_digest,
            self.candidate_set_digest,
            self.registry_snapshot_digest,
            self.generation_vector_digest,
            self.model_tuple_digest,
            self.selection_grammar_digest,
            self.generator_code_digest,
            self.hard_filter_digest,
            self.truncation_digest,
            self.pricing_policy_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCompletenessEvidenceV2 {
    pub receipt: CandidateSetCompletenessReceiptV1,
    pub context: PromptEvidenceContextV2,
    pub evidence: SignedLearningEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingEvidenceV2 {
    pub factor_id: StableId,
    pub realization_id: StableId,
    pub realization_binding_digest: Digest32,
    pub context: PromptEvidenceContextV2,
    pub state_digest: Digest32,
    pub expected_incremental_utility_q32: FixedQ32,
    pub downside_q32: FixedQ32,
    pub confidence_lower_q32: FixedQ32,
    pub confidence_upper_q32: FixedQ32,
    pub support_count: u32,
    pub latency_cost_micros: u64,
    pub interference_ppm: u32,
    pub context_crowding_cost_q32: FixedQ32,
    pub privacy_cost_q32: FixedQ32,
    pub instability_cost_q32: FixedQ32,
    pub future_context_option_cost_q32: FixedQ32,
    pub support_audit_digest: Digest32,
    pub evidence: SignedLearningEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPairUtilityEvidenceV2 {
    pub left_factor_id: StableId,
    pub right_factor_id: StableId,
    pub context: PromptEvidenceContextV2,
    pub state_digest: Digest32,
    pub graph_generation_digest: Digest32,
    pub edge_validity_digest: Digest32,
    pub marginal_utility_q32: FixedQ32,
    pub confidence_lower_q32: FixedQ32,
    pub confidence_upper_q32: FixedQ32,
    pub support_audit_digest: Digest32,
    pub evidence: SignedLearningEvidenceV1,
}

#[must_use]
pub fn completeness_evidence_signing_payload_v2(
    evidence: &PromptCompletenessEvidenceV2,
) -> Vec<u8> {
    let mut bytes = b"hepta.prompt-optimizer.completeness-evidence.v2".to_vec();
    bytes.extend_from_slice(evidence.context.digest().as_array());
    match validate_candidate_set_completeness(&evidence.receipt) {
        Ok(digest) => bytes.extend_from_slice(digest.as_array()),
        Err(_) => bytes.extend_from_slice(Digest32::ZERO.as_array()),
    }
    bytes
}

#[must_use]
pub fn pricing_evidence_signing_payload_v2(evidence: &PromptPricingEvidenceV2) -> Vec<u8> {
    let mut bytes = b"hepta.prompt-optimizer.pricing-evidence.v2".to_vec();
    push_id(&mut bytes, &evidence.factor_id);
    push_id(&mut bytes, &evidence.realization_id);
    bytes.extend_from_slice(evidence.realization_binding_digest.as_array());
    bytes.extend_from_slice(evidence.context.digest().as_array());
    bytes.extend_from_slice(evidence.state_digest.as_array());
    for value in [
        evidence.expected_incremental_utility_q32,
        evidence.downside_q32,
        evidence.confidence_lower_q32,
        evidence.confidence_upper_q32,
        evidence.context_crowding_cost_q32,
        evidence.privacy_cost_q32,
        evidence.instability_cost_q32,
        evidence.future_context_option_cost_q32,
    ] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&evidence.support_count.to_be_bytes());
    bytes.extend_from_slice(&evidence.latency_cost_micros.to_be_bytes());
    bytes.extend_from_slice(&evidence.interference_ppm.to_be_bytes());
    bytes.extend_from_slice(evidence.support_audit_digest.as_array());
    bytes
}

#[must_use]
pub fn pair_evidence_signing_payload_v2(evidence: &PromptPairUtilityEvidenceV2) -> Vec<u8> {
    let mut bytes = b"hepta.prompt-optimizer.pair-evidence.v2".to_vec();
    push_id(&mut bytes, &evidence.left_factor_id);
    push_id(&mut bytes, &evidence.right_factor_id);
    bytes.extend_from_slice(evidence.context.digest().as_array());
    bytes.extend_from_slice(evidence.state_digest.as_array());
    bytes.extend_from_slice(evidence.graph_generation_digest.as_array());
    bytes.extend_from_slice(evidence.edge_validity_digest.as_array());
    for value in [
        evidence.marginal_utility_q32,
        evidence.confidence_lower_q32,
        evidence.confidence_upper_q32,
    ] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    bytes.extend_from_slice(evidence.support_audit_digest.as_array());
    bytes
}

include!("verified_stage.rs");
include!("verified_solver.rs");
include!("verified_validation.rs");

#[cfg(test)]
#[path = "verified_tests.rs"]
mod tests;
