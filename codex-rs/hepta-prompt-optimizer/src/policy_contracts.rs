// ---------------------------------------------------------------------------
// Registered public V1 receipts.
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateSetReceiptV1 {
    pub set_id: StableId,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub registry_digest: Digest32,
    pub candidate_factor_ids: Vec<StableId>,
    pub selection_grammar_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptConfidenceIntervalV1 {
    pub lower_q32: FixedQ32,
    pub upper_q32: FixedQ32,
    pub confidence_ppm: u32,
    pub support_digest: Digest32,
    pub scope_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingReceiptV1 {
    pub factor_id: StableId,
    pub state_digest: Digest32,
    pub expected_utility_q32: FixedQ32,
    pub downside_q32: FixedQ32,
    pub token_cost: u32,
    pub latency_cost_micros: u64,
    pub interference_ppm: u32,
    pub confidence_interval: PromptConfidenceIntervalV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioReceiptV1 {
    pub portfolio_id: StableId,
    pub candidate_set_digest: Digest32,
    pub factor_ids: Vec<StableId>,
    pub interaction_digest: Digest32,
    pub expected_utility_q32: FixedQ32,
    pub total_token_upper_bound: u32,
    pub valid_until_unix_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum PromptDecisionBoundaryV1 {
    RequestAccepted,
    ObjectiveCompiled,
    BeforePlanning,
    BeforeCandidateGeneration,
    BeforeModelOrToolDispatch,
    AfterObservation,
    AfterFailureOrUncertaintySpike,
    BeforeIrreversibleMutation,
    BeforeVerification,
    BeforeFinalResponse,
    BeforeCompactOrHandoff,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptExerciseChoiceV1 {
    Exercise,
    Wait,
    NoChange,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseDecisionV1 {
    pub factor_or_portfolio_id: StableId,
    pub decision_boundary: PromptDecisionBoundaryV1,
    pub exercise_now_value_q32: FixedQ32,
    pub wait_value_q32: FixedQ32,
    pub decision: PromptExerciseChoiceV1,
    pub policy_digest: Digest32,
}

impl PromptCandidateSetReceiptV1 {
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

impl PromptPricingReceiptV1 {
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

impl PromptPortfolioReceiptV1 {
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

impl PromptExerciseDecisionV1 {
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

// ---------------------------------------------------------------------------
// Enumeration inputs and audit companion.
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptFactorSnapshotV1 {
    pub factor_id: StableId,
    pub realization_id: StableId,
    pub admitted: bool,
    pub legal: bool,
    /// `None` means the registered factor is objective-agnostic.
    pub objective_scope_digest: Option<Digest32>,
    /// `None` means the factor is compatible with any registered model profile.
    pub model_profile_digest: Option<Digest32>,
    pub realization_context_digest: Digest32,
    pub token_upper_bound: u32,
    pub support_reference_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistrySnapshotV1 {
    pub registry_digest: Digest32,
    pub source_evidence_digest: Digest32,
    pub factors: Vec<PromptFactorSnapshotV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptObjectiveContextV1 {
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub selection_grammar_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptModelProfileV1 {
    pub profile_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub system_template_digest: Digest32,
    pub tool_schema_digest: Digest32,
    pub context_profile_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptEnumerationDispositionV1 {
    Retained,
    OmittedByDeterministicCap,
    NotAdmitted,
    Illegal,
    ObjectiveScopeMismatch,
    ModelProfileMismatch,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptEnumerationCandidateAuditV1 {
    pub factor_id: StableId,
    pub disposition: PromptEnumerationDispositionV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateBindingV1 {
    pub factor_id: StableId,
    pub realization_id: StableId,
    pub model_profile_digest: Digest32,
    pub realization_context_digest: Digest32,
    pub token_upper_bound: u32,
    pub support_reference_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateSetAuditV1 {
    pub candidate_set_digest: Digest32,
    pub source_evidence_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub complete_eligible_set_digest: Digest32,
    pub eligible_before_truncation: u32,
    pub retained_count: u32,
    pub omitted_count: u32,
    pub bindings: Vec<PromptCandidateBindingV1>,
    pub candidate_decisions: Vec<PromptEnumerationCandidateAuditV1>,
    pub audit_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateSetBundleV1 {
    pub receipt: PromptCandidateSetReceiptV1,
    pub audit: PromptCandidateSetAuditV1,
}

// ---------------------------------------------------------------------------
// Pricing inputs and audit companion.
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCausalEstimateV1 {
    pub factor_id: StableId,
    pub candidate_set_digest: Digest32,
    pub registry_digest: Digest32,
    pub state_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub realization_context_digest: Digest32,
    pub incremental_recursive_utility_q32: FixedQ32,
    pub downside_q32: FixedQ32,
    pub confidence_interval: PromptConfidenceIntervalV1,
    pub causal_support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptFactorCostV1 {
    pub factor_id: StableId,
    pub token_cost: u32,
    pub latency_cost_micros: u64,
    pub interference_ppm: u32,
    pub token_utility_cost_q32: FixedQ32,
    pub latency_utility_cost_q32: FixedQ32,
    pub context_crowding_cost_q32: FixedQ32,
    pub instruction_interference_cost_q32: FixedQ32,
    pub privacy_cost_q32: FixedQ32,
    pub instability_cost_q32: FixedQ32,
    pub future_context_option_value_cost_q32: FixedQ32,
    pub resource_cost_q32: FixedQ32,
    pub cost_support_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptPricingUnavailableReasonV1 {
    MissingCausalEstimate,
    MissingCostModel,
    EvidenceBindingMismatch,
    InvalidConfidenceInterval,
    InvalidCost,
    RegisteredTokenBoundExceeded,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptUnavailablePricingV1 {
    pub factor_id: StableId,
    pub reason: PromptPricingUnavailableReasonV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingDecompositionV1 {
    pub causal_incremental_utility_q32: FixedQ32,
    pub token_utility_cost_q32: FixedQ32,
    pub latency_utility_cost_q32: FixedQ32,
    pub context_crowding_cost_q32: FixedQ32,
    pub instruction_interference_cost_q32: FixedQ32,
    pub privacy_cost_q32: FixedQ32,
    pub instability_cost_q32: FixedQ32,
    pub future_context_option_value_cost_q32: FixedQ32,
    pub resource_cost_q32: FixedQ32,
    pub total_utility_cost_q32: FixedQ32,
    pub net_expected_utility_q32: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingAuditEntryV1 {
    pub factor_id: StableId,
    pub model_profile_digest: Digest32,
    pub realization_context_digest: Digest32,
    pub causal_support_digest: Digest32,
    pub cost_support_digest: Digest32,
    pub decomposition: PromptPricingDecompositionV1,
    pub entry_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingBatchV1 {
    pub candidate_set_digest: Digest32,
    pub complete_eligible_set_digest: Digest32,
    pub omitted_count: u32,
    pub model_profile_digest: Digest32,
    pub receipts: Vec<PromptPricingReceiptV1>,
    pub audit_entries: Vec<PromptPricingAuditEntryV1>,
    pub unavailable: Vec<PromptUnavailablePricingV1>,
    pub batch_digest: Digest32,
}

// ---------------------------------------------------------------------------
// Interaction / hard-constraint model and portfolio audit companion.
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum PromptInteractionKindV1 {
    ExplicitZero,
    Complement,
    Substitute,
    Dominates,
    Redundant,
    Supersedes,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptInteractionEdgeV1 {
    pub left_factor_id: StableId,
    pub right_factor_id: StableId,
    pub kind: PromptInteractionKindV1,
    pub marginal_utility_q32: FixedQ32,
    pub support_reference_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptHardConstraintV1 {
    Conflict {
        left_factor_id: StableId,
        right_factor_id: StableId,
        support_reference_digest: Digest32,
    },
    Requires {
        factor_id: StableId,
        prerequisite_factor_id: StableId,
        support_reference_digest: Digest32,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptMissingInteractionPolicyV1 {
    /// Missing pair edges are explicitly interpreted as zero marginal utility.
    AssumeZero,
    /// Every unordered pair must be represented by an explicit edge.
    RejectMissing,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptInteractionGraphV1 {
    pub candidate_set_digest: Digest32,
    pub candidate_factor_ids: Vec<StableId>,
    pub missing_interaction_policy: PromptMissingInteractionPolicyV1,
    pub edges: Vec<PromptInteractionEdgeV1>,
    pub hard_constraints: Vec<PromptHardConstraintV1>,
    pub source_evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioBudgetV1 {
    pub portfolio_id: StableId,
    pub token_budget: u32,
    pub maximum_selected_factors: usize,
    pub valid_until_unix_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptPortfolioDispositionV1 {
    Selected,
    UnavailablePricing,
    NonPositivePackageUtility,
    OverTokenBudget,
    SelectionLimit,
    HardConflict,
    HeuristicExcluded,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioCandidateAuditV1 {
    pub factor_id: StableId,
    pub disposition: PromptPortfolioDispositionV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptSelectionMethodV1 {
    GreedyPrerequisiteClosureV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptOptimalityDisclosureV1 {
    HeuristicNoCertificate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioAuditV1 {
    pub candidate_set_digest: Digest32,
    pub complete_eligible_set_digest: Digest32,
    pub omitted_count: u32,
    pub priced_count: u32,
    pub unavailable_pricing_count: u32,
    pub interaction_digest: Digest32,
    pub constraint_digest: Digest32,
    pub pricing_batch_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub candidate_decisions: Vec<PromptPortfolioCandidateAuditV1>,
    pub selection_method: PromptSelectionMethodV1,
    pub optimality: PromptOptimalityDisclosureV1,
    pub requires_registered_exercise_boundary: bool,
    pub audit_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioDecisionV1 {
    pub receipt: PromptPortfolioReceiptV1,
    pub audit: PromptPortfolioAuditV1,
}

// ---------------------------------------------------------------------------
// Exercise boundary and audit companion.
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegisteredPromptBoundaryV1 {
    pub decision_boundary: PromptDecisionBoundaryV1,
    pub portfolio_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub registry_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub registered_state_digest: Digest32,
    pub policy_digest: Digest32,
    pub boundary_support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseStateV1 {
    pub state_digest: Digest32,
    pub registry_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub observed_at_unix_ms: u64,
    pub wait_value_q32: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseAuditV1 {
    pub portfolio_digest: Digest32,
    pub boundary_digest: Digest32,
    pub state_compatible: bool,
    pub registry_compatible: bool,
    pub model_profile_compatible: bool,
    pub before_expiry: bool,
    pub audit_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseDecisionBundleV1 {
    pub receipt: PromptExerciseDecisionV1,
    pub audit: PromptExerciseAuditV1,
}

// ---------------------------------------------------------------------------
// Errors.
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PolicyError {
    EnumerationInputLimitExceeded,
    FactorLimitExceeded,
    InteractionEdgeLimitExceeded,
    HardConstraintLimitExceeded,
    SelectedFactorLimitExceeded,
    TokenBudgetLimitExceeded,
    EmptyIdentifier(&'static str),
    EmptyDigest(&'static str),
    DuplicateFactor(String),
    DuplicateRealization(String),
    DuplicatePricing(String),
    DuplicateInteraction(String, String),
    DuplicateConstraint(&'static str, String, String),
    UnknownFactor(String),
    InvalidInteractionEndpoints,
    InvalidConstraintEndpoints,
    NonCanonicalFactorOrder,
    NonCanonicalInteractionOrder,
    NonCanonicalConstraintOrder,
    MissingPairInteraction(String, String),
    RequiresCycle(String),
    UnsatisfiableConstraintGraph(String),
    CandidateSetDigestMismatch,
    EvidenceBindingMismatch(String),
    PricingUnavailable(String, PromptPricingUnavailableReasonV1),
    InvalidConfidenceInterval(String),
    InvalidCost(String),
    RegisteredTokenBoundExceeded(String),
    InvalidPortfolioValidity,
    PortfolioExpired,
    PortfolioDigestMismatch,
    StateDrift,
    RegistryDrift,
    ModelProfileDrift,
    Arithmetic,
    DerivedIdentifier,
}

impl fmt::Display for PolicyError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PolicyError {}
