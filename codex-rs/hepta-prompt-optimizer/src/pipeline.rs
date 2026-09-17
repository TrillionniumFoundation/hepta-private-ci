//! Registered prompt-optimization contracts and the deterministic V1 policy pipeline.
//!
//! The four public contract structs in this module mirror the canonical
//! `PROTOCOL_SCHEMAS.json` field shapes. Richer source/provenance/decision data
//! is carried in digest-bound native audit sidecars instead of adding
//! unregistered fields to a V1 wire contract.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{AuthorityPosture, Digest32, FixedQ32, StableId};

pub const MAX_SOURCE_FACTORS_V1: usize = 4_096;
pub const MAX_FACTORS_V1: usize = 128;
pub const MAX_INTERACTION_EDGES_V1: usize = 512;
pub const MAX_CONSTRAINT_EDGES_V1: usize = 512;
pub const MAX_SELECTED_FACTORS_V1: usize = 16;
pub const MAX_SELECTION_STEPS_V1: usize = 128;
pub const MAX_TOKEN_BUDGET_V1: u32 = 1_000_000;
pub const MAX_CONFIDENCE_PPM: u32 = 1_000_000;
pub const MAX_INTERFERENCE_PPM: u32 = 1_000_000;

// -----------------------------------------------------------------------------
// Canonical registered V1 contract shapes.
// -----------------------------------------------------------------------------

/// Canonical `PromptCandidateSetReceiptV1` semantic fields.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateSetReceiptV1 {
    pub set_id: StableId,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub registry_digest: Digest32,
    pub candidate_factor_ids: Vec<StableId>,
    pub selection_grammar_digest: Digest32,
}

impl PromptCandidateSetReceiptV1 {
    pub fn semantic_digest(&self) -> Digest32 {
        digest_candidate_contract(self)
    }

    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// Bounded object used by the canonical `confidenceInterval` field.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PromptConfidenceIntervalV1 {
    pub lower_q32: FixedQ32,
    pub upper_q32: FixedQ32,
    pub confidence_ppm: u32,
}

/// Canonical per-factor `PromptPricingReceiptV1` semantic fields.
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

impl PromptPricingReceiptV1 {
    pub fn semantic_digest(&self) -> Digest32 {
        digest_pricing_contract(self)
    }

    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// Canonical `PromptPortfolioReceiptV1` semantic fields.
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

impl PromptPortfolioReceiptV1 {
    pub fn semantic_digest(&self) -> Digest32 {
        digest_portfolio_contract(self)
    }

    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// Registered decision-boundary enum used by `PromptExerciseDecisionV1`.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
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
pub enum PromptExerciseActionV1 {
    Exercise,
    Wait,
}

/// Canonical `PromptExerciseDecisionV1` semantic fields.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseDecisionV1 {
    pub factor_or_portfolio_id: StableId,
    pub decision_boundary: PromptDecisionBoundaryV1,
    pub exercise_now_value_q32: FixedQ32,
    pub wait_value_q32: FixedQ32,
    pub decision: PromptExerciseActionV1,
    pub policy_digest: Digest32,
}

impl PromptExerciseDecisionV1 {
    pub fn semantic_digest(&self) -> Digest32 {
        digest_exercise_contract(self)
    }

    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

// -----------------------------------------------------------------------------
// Native bounded inputs and audit sidecars.
// -----------------------------------------------------------------------------

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistryFactorV1 {
    pub candidate_id: StableId,
    pub factor_id: StableId,
    pub realization_id: StableId,
    pub admitted: bool,
    pub legal: bool,
    pub objective_scope_digest: Digest32,
    pub model_compatibility_digest: Digest32,
    pub token_upper_bound: u32,
    pub registry_entry_digest: Digest32,
    pub support_reference_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistrySnapshotV1 {
    pub state_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub registry_owner_digest: Digest32,
    pub completeness_digest: Digest32,
    pub factors: Vec<PromptRegistryFactorV1>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PromptObjectiveProfileV1 {
    pub objective_digest: Digest32,
    pub scope_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PromptModelProfileV1 {
    pub model_profile_digest: Digest32,
    pub compatibility_digest: Digest32,
    pub selection_grammar_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptEnumerationDispositionV1 {
    Included,
    NotAdmitted,
    Illegal,
    ObjectiveScopeMismatch,
    ModelIncompatible,
    Truncated,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptEnumerationDecisionV1 {
    pub candidate_id: StableId,
    pub factor_id: StableId,
    pub disposition: PromptEnumerationDispositionV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateBindingV1 {
    pub candidate_id: StableId,
    pub factor_id: StableId,
    pub realization_id: StableId,
    pub token_upper_bound: u32,
    pub registry_entry_digest: Digest32,
    pub support_reference_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateSetAuditV1 {
    pub candidate_set_digest: Digest32,
    pub registry_owner_digest: Digest32,
    pub registry_completeness_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub model_compatibility_digest: Digest32,
    pub source_factor_count: u32,
    pub eligible_factor_count: u32,
    pub omitted_count: u32,
    pub candidates: Vec<PromptCandidateBindingV1>,
    pub decisions: Vec<PromptEnumerationDecisionV1>,
    pub audit_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateEnumerationV1 {
    pub receipt: PromptCandidateSetReceiptV1,
    pub audit: PromptCandidateSetAuditV1,
}

impl PromptCandidateEnumerationV1 {
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CausalSupportStatusV1 {
    Supported,
    Unsupported,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCausalEstimateV1 {
    pub factor_id: StableId,
    pub causal_incremental_utility: FixedQ32,
    pub downside_q32: FixedQ32,
    pub confidence_lower_q32: FixedQ32,
    pub confidence_upper_q32: FixedQ32,
    pub confidence_ppm: u32,
    pub support_status: CausalSupportStatusV1,
    pub estimator_digest: Digest32,
    pub support_reference_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCausalEstimateSetV1 {
    pub state_digest: Digest32,
    pub selection_grammar_digest: Digest32,
    pub ledger_snapshot_digest: Digest32,
    pub ledger_owner_digest: Digest32,
    pub estimates: Vec<PromptCausalEstimateV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCostBreakdownV1 {
    pub factor_id: StableId,
    pub token_units: u32,
    pub latency_cost_micros: u64,
    pub interference_ppm: u32,
    pub token_utility_cost: FixedQ32,
    pub latency_utility_cost: FixedQ32,
    pub interference_utility_cost: FixedQ32,
    pub resource_utility_cost: FixedQ32,
    pub privacy_utility_cost: FixedQ32,
    pub instability_utility_cost: FixedQ32,
    pub future_context_option_value_cost: FixedQ32,
    pub support_reference_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCostModelV1 {
    pub state_digest: Digest32,
    pub selection_grammar_digest: Digest32,
    pub cost_model_digest: Digest32,
    pub costs: Vec<PromptCostBreakdownV1>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptPriceAvailabilityV1 {
    Available,
    UnsupportedCausalEvidence,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingAuditEntryV1 {
    pub factor_id: StableId,
    pub availability: PromptPriceAvailabilityV1,
    pub causal_incremental_utility: FixedQ32,
    pub total_utility_cost: FixedQ32,
    pub net_utility: FixedQ32,
    pub token_utility_cost: FixedQ32,
    pub latency_utility_cost: FixedQ32,
    pub interference_utility_cost: FixedQ32,
    pub resource_utility_cost: FixedQ32,
    pub privacy_utility_cost: FixedQ32,
    pub instability_utility_cost: FixedQ32,
    pub future_context_option_value_cost: FixedQ32,
    pub causal_support_reference_digest: Digest32,
    pub cost_support_reference_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingBatchV1 {
    pub candidate_set: PromptCandidateSetReceiptV1,
    pub candidate_audit: PromptCandidateSetAuditV1,
    pub receipts: Vec<PromptPricingReceiptV1>,
    pub audit: Vec<PromptPricingAuditEntryV1>,
    pub ledger_snapshot_digest: Digest32,
    pub ledger_owner_digest: Digest32,
    pub cost_model_digest: Digest32,
    pub batch_digest: Digest32,
}

impl PromptPricingBatchV1 {
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPairInteractionV1 {
    pub left_factor_id: StableId,
    pub right_factor_id: StableId,
    pub marginal_utility: FixedQ32,
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
pub enum UnknownInteractionPolicyV1 {
    MissingAsZero,
    RejectMissing,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptInteractionSetV1 {
    pub graph_snapshot_digest: Digest32,
    pub graph_owner_digest: Digest32,
    pub unknown_interaction_policy: UnknownInteractionPolicyV1,
    pub interactions: Vec<PromptPairInteractionV1>,
    pub hard_constraints: Vec<PromptHardConstraintV1>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PromptPortfolioBudgetV1 {
    pub token_budget: u32,
    pub maximum_selected_factors: usize,
    pub valid_until_unix_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptSelectionMethodV1 {
    PrerequisiteClosureGreedyDensityV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptOptimalityDisclosureV1 {
    HeuristicNoCertificate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptPortfolioDispositionV1 {
    Selected,
    UnavailablePricing,
    NonPositiveMarginal,
    OverBudget,
    SelectionLimit,
    Conflict,
    HeuristicNotSelected,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioCandidateDecisionV1 {
    pub factor_id: StableId,
    pub disposition: PromptPortfolioDispositionV1,
    pub prerequisite_closure: Vec<StableId>,
    pub confidence_ppm: u32,
    pub token_cost: u32,
    pub standalone_net_utility: FixedQ32,
    pub causal_support_reference_digest: Digest32,
    pub cost_support_reference_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioAuditV1 {
    pub pricing_batch_digest: Digest32,
    pub state_digest: Digest32,
    pub objective_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub registry_completeness_digest: Digest32,
    pub source_factor_count: u32,
    pub eligible_factor_count: u32,
    pub omitted_count: u32,
    pub model_profile_digest: Digest32,
    pub model_compatibility_digest: Digest32,
    pub graph_owner_digest: Digest32,
    pub decisions: Vec<PromptPortfolioCandidateDecisionV1>,
    pub total_net_utility: FixedQ32,
    pub unspent_token_budget: u32,
    pub selection_steps: u32,
    pub selection_method: PromptSelectionMethodV1,
    pub optimality: PromptOptimalityDisclosureV1,
    pub unknown_interaction_policy: UnknownInteractionPolicyV1,
    pub audit_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioDecisionV1 {
    pub receipt: PromptPortfolioReceiptV1,
    pub audit: PromptPortfolioAuditV1,
}

impl PromptPortfolioDecisionV1 {
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegisteredPromptBoundaryV1 {
    pub decision_boundary: PromptDecisionBoundaryV1,
    pub boundary_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub model_compatibility_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PromptExerciseStateV1 {
    pub state_digest: Digest32,
    pub objective_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub model_compatibility_digest: Digest32,
    pub exercise_now_value_q32: FixedQ32,
    pub wait_value_q32: FixedQ32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptExerciseDispositionV1 {
    Exercise,
    WaitForHigherValue,
    NoIntervention,
    InvalidatedStateDrift,
    InvalidatedRegistryDrift,
    InvalidatedModelDrift,
    InvalidatedObjectiveDrift,
    InvalidatedBoundaryCompatibility,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseAuditV1 {
    pub disposition: PromptExerciseDispositionV1,
    pub boundary_digest: Digest32,
    pub portfolio_digest: Digest32,
    pub portfolio_audit_digest: Digest32,
    pub state_digest: Digest32,
    pub audit_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseOutcomeV1 {
    pub receipt: PromptExerciseDecisionV1,
    pub audit: PromptExerciseAuditV1,
}

impl PromptExerciseOutcomeV1 {
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PipelineError {
    EmptyDigest(&'static str),
    EmptyIdentifier(&'static str),
    SourceFactorLimitExceeded,
    CandidateLimitExceeded,
    InteractionEdgeLimitExceeded,
    ConstraintEdgeLimitExceeded,
    SelectedFactorLimitExceeded,
    TokenBudgetLimitExceeded,
    DuplicateCandidate(String),
    DuplicateFactor(String),
    DuplicateRealization(String),
    DuplicateEvidence(String),
    DuplicateCost(String),
    MissingCausalEstimate(String),
    MissingCost(String),
    ExtraCausalEstimate(String),
    ExtraCost(String),
    UnknownRelationEndpoint(String),
    InvalidRelationEndpoints,
    DuplicateRelation(&'static str, String, String),
    ConfidenceOutOfRange(String),
    InvalidConfidenceInterval(String),
    InterferenceOutOfRange(String),
    StateMismatch(&'static str),
    SelectionGrammarMismatch(&'static str),
    TokenBoundExceeded(String),
    AuthorityEscalation(&'static str),
    IntegrityMismatch(&'static str),
    RequiresCycle(String),
    UnsatisfiableConstraintGraph(String),
    MissingPairInteraction(String, String),
    InvalidExpiry,
    Arithmetic,
    IdentifierDerivation,
}

impl fmt::Display for PipelineError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PipelineError {}

// -----------------------------------------------------------------------------
// Public policy operations.
// -----------------------------------------------------------------------------

/// Exact registered-contract surface for candidate enumeration.
pub fn enumerate_factors(
    registry_snapshot: PromptRegistrySnapshotV1,
    objective: PromptObjectiveProfileV1,
    model_profile: PromptModelProfileV1,
) -> Result<PromptCandidateSetReceiptV1, PipelineError> {
    Ok(enumerate_factors_with_audit(registry_snapshot, objective, model_profile)?.receipt)
}

/// Audited enumeration used by the complete native pipeline.
pub fn enumerate_factors_with_audit(
    registry_snapshot: PromptRegistrySnapshotV1,
    objective: PromptObjectiveProfileV1,
    model_profile: PromptModelProfileV1,
) -> Result<PromptCandidateEnumerationV1, PipelineError> {
    if registry_snapshot.factors.len() > MAX_SOURCE_FACTORS_V1 {
        return Err(PipelineError::SourceFactorLimitExceeded);
    }
    for (digest, label) in [
        (registry_snapshot.state_digest, "state"),
        (
            registry_snapshot.registry_snapshot_digest,
            "registry snapshot",
        ),
        (registry_snapshot.registry_owner_digest, "registry owner"),
        (
            registry_snapshot.completeness_digest,
            "registry completeness",
        ),
        (objective.objective_digest, "objective"),
        (objective.scope_digest, "objective scope"),
        (model_profile.model_profile_digest, "model profile"),
        (model_profile.compatibility_digest, "model compatibility"),
        (model_profile.selection_grammar_digest, "selection grammar"),
    ] {
        require_digest(digest, label)?;
    }

    let source_factor_count = u32::try_from(registry_snapshot.factors.len())
        .map_err(|_| PipelineError::SourceFactorLimitExceeded)?;
    let mut factors = registry_snapshot.factors;
    factors.sort_by(|left, right| {
        left.factor_id
            .cmp(&right.factor_id)
            .then_with(|| left.realization_id.cmp(&right.realization_id))
            .then_with(|| left.candidate_id.cmp(&right.candidate_id))
    });

    let mut candidate_ids = BTreeSet::new();
    let mut factor_ids = BTreeSet::new();
    let mut realization_ids = BTreeSet::new();
    let mut candidate_factor_ids = Vec::new();
    let mut bindings = Vec::new();
    let mut decisions = Vec::with_capacity(factors.len());
    let mut eligible_count = 0usize;

    for factor in factors {
        require_id(&factor.candidate_id, "candidate")?;
        require_id(&factor.factor_id, "factor")?;
        require_id(&factor.realization_id, "realization")?;
        for (digest, label) in [
            (factor.objective_scope_digest, "factor objective scope"),
            (
                factor.model_compatibility_digest,
                "factor model compatibility",
            ),
            (factor.registry_entry_digest, "registry entry"),
            (factor.support_reference_digest, "factor support"),
        ] {
            require_digest(digest, label)?;
        }
        if !candidate_ids.insert(factor.candidate_id.clone()) {
            return Err(PipelineError::DuplicateCandidate(
                factor.candidate_id.to_string(),
            ));
        }
        if !factor_ids.insert(factor.factor_id.clone()) {
            return Err(PipelineError::DuplicateFactor(factor.factor_id.to_string()));
        }
        if !realization_ids.insert(factor.realization_id.clone()) {
            return Err(PipelineError::DuplicateRealization(
                factor.realization_id.to_string(),
            ));
        }

        let disposition = if !factor.admitted {
            PromptEnumerationDispositionV1::NotAdmitted
        } else if !factor.legal {
            PromptEnumerationDispositionV1::Illegal
        } else if factor.objective_scope_digest != objective.scope_digest {
            PromptEnumerationDispositionV1::ObjectiveScopeMismatch
        } else if factor.model_compatibility_digest != model_profile.compatibility_digest {
            PromptEnumerationDispositionV1::ModelIncompatible
        } else {
            eligible_count = eligible_count.saturating_add(1);
            if candidate_factor_ids.len() >= MAX_FACTORS_V1 {
                PromptEnumerationDispositionV1::Truncated
            } else {
                candidate_factor_ids.push(factor.factor_id.clone());
                bindings.push(PromptCandidateBindingV1 {
                    candidate_id: factor.candidate_id.clone(),
                    factor_id: factor.factor_id.clone(),
                    realization_id: factor.realization_id.clone(),
                    token_upper_bound: factor.token_upper_bound,
                    registry_entry_digest: factor.registry_entry_digest,
                    support_reference_digest: factor.support_reference_digest,
                });
                PromptEnumerationDispositionV1::Included
            }
        };
        decisions.push(PromptEnumerationDecisionV1 {
            candidate_id: factor.candidate_id,
            factor_id: factor.factor_id,
            disposition,
        });
    }

    let eligible_factor_count =
        u32::try_from(eligible_count).map_err(|_| PipelineError::CandidateLimitExceeded)?;
    let omitted_count = eligible_count.saturating_sub(candidate_factor_ids.len());
    let omitted_count =
        u32::try_from(omitted_count).map_err(|_| PipelineError::CandidateLimitExceeded)?;

    let set_id = derived_id_from_parts(
        "candidate-set",
        &[
            objective.objective_digest,
            registry_snapshot.state_digest,
            registry_snapshot.registry_snapshot_digest,
            model_profile.selection_grammar_digest,
        ],
    )?;
    let receipt = PromptCandidateSetReceiptV1 {
        set_id,
        objective_digest: objective.objective_digest,
        state_digest: registry_snapshot.state_digest,
        registry_digest: registry_snapshot.registry_snapshot_digest,
        candidate_factor_ids,
        selection_grammar_digest: model_profile.selection_grammar_digest,
    };
    let candidate_set_digest = receipt.semantic_digest();
    let audit_digest = digest_candidate_audit(
        candidate_set_digest,
        registry_snapshot.registry_owner_digest,
        registry_snapshot.completeness_digest,
        model_profile.model_profile_digest,
        model_profile.compatibility_digest,
        source_factor_count,
        eligible_factor_count,
        omitted_count,
        &bindings,
        &decisions,
    );
    Ok(PromptCandidateEnumerationV1 {
        receipt,
        audit: PromptCandidateSetAuditV1 {
            candidate_set_digest,
            registry_owner_digest: registry_snapshot.registry_owner_digest,
            registry_completeness_digest: registry_snapshot.completeness_digest,
            model_profile_digest: model_profile.model_profile_digest,
            model_compatibility_digest: model_profile.compatibility_digest,
            source_factor_count,
            eligible_factor_count,
            omitted_count,
            candidates: bindings,
            decisions,
            audit_digest,
        },
    })
}

/// Exact registered-contract surface for factor pricing.
///
/// The canonical `PromptPricingReceiptV1` schema is one factor per receipt, so
/// the plural operation returns a bounded vector of exact registered receipts.
/// Use [`price_factors_with_audit`] when the downstream portfolio selector also
/// needs provenance, availability, and cost-decomposition sidecars.
pub fn price_factors(
    candidates: PromptCandidateEnumerationV1,
    causal_estimates: PromptCausalEstimateSetV1,
    costs: PromptCostModelV1,
) -> Result<Vec<PromptPricingReceiptV1>, PipelineError> {
    Ok(price_factors_with_audit(candidates, causal_estimates, costs)?.receipts)
}

/// Audited pricing used by the complete native pipeline.
pub fn price_factors_with_audit(
    candidates: PromptCandidateEnumerationV1,
    causal_estimates: PromptCausalEstimateSetV1,
    costs: PromptCostModelV1,
) -> Result<PromptPricingBatchV1, PipelineError> {
    if candidates.authority().grants_any() {
        return Err(PipelineError::AuthorityEscalation("candidate enumeration"));
    }
    validate_candidate_audit_binding(&candidates.receipt, &candidates.audit)?;
    if candidates.receipt.candidate_factor_ids.len() > MAX_FACTORS_V1 {
        return Err(PipelineError::CandidateLimitExceeded);
    }
    for (digest, label) in [
        (candidates.receipt.semantic_digest(), "candidate set"),
        (candidates.audit.audit_digest, "candidate audit"),
        (causal_estimates.ledger_snapshot_digest, "ledger snapshot"),
        (causal_estimates.ledger_owner_digest, "ledger owner"),
        (costs.cost_model_digest, "cost model"),
    ] {
        require_digest(digest, label)?;
    }
    if candidates.receipt.state_digest != causal_estimates.state_digest {
        return Err(PipelineError::StateMismatch("causal estimates"));
    }
    if candidates.receipt.state_digest != costs.state_digest {
        return Err(PipelineError::StateMismatch("cost model"));
    }
    if candidates.receipt.selection_grammar_digest != causal_estimates.selection_grammar_digest {
        return Err(PipelineError::SelectionGrammarMismatch("causal estimates"));
    }
    if candidates.receipt.selection_grammar_digest != costs.selection_grammar_digest {
        return Err(PipelineError::SelectionGrammarMismatch("cost model"));
    }

    let estimates = unique_estimates(causal_estimates.estimates)?;
    let costs_by_factor = unique_costs(costs.costs)?;
    let allowed = candidates
        .receipt
        .candidate_factor_ids
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    reject_extra_keys(&allowed, estimates.keys(), true)?;
    reject_extra_keys(&allowed, costs_by_factor.keys(), false)?;

    let token_bounds = candidates
        .audit
        .candidates
        .iter()
        .map(|binding| (binding.factor_id.clone(), binding.token_upper_bound))
        .collect::<BTreeMap<_, _>>();
    let mut receipts = Vec::with_capacity(allowed.len());
    let mut audit = Vec::with_capacity(allowed.len());

    for factor_id in &candidates.receipt.candidate_factor_ids {
        let estimate = estimates
            .get(factor_id)
            .ok_or_else(|| PipelineError::MissingCausalEstimate(factor_id.to_string()))?;
        let cost = costs_by_factor
            .get(factor_id)
            .ok_or_else(|| PipelineError::MissingCost(factor_id.to_string()))?;
        validate_estimate(estimate)?;
        validate_cost(cost)?;
        let token_upper_bound = token_bounds
            .get(factor_id)
            .copied()
            .ok_or_else(|| PipelineError::MissingCost(factor_id.to_string()))?;
        if cost.token_units > token_upper_bound {
            return Err(PipelineError::TokenBoundExceeded(factor_id.to_string()));
        }
        let total_utility_cost = checked_sum(&[
            cost.token_utility_cost,
            cost.latency_utility_cost,
            cost.interference_utility_cost,
            cost.resource_utility_cost,
            cost.privacy_utility_cost,
            cost.instability_utility_cost,
            cost.future_context_option_value_cost,
        ])?;
        let availability = match estimate.support_status {
            CausalSupportStatusV1::Supported => PromptPriceAvailabilityV1::Available,
            CausalSupportStatusV1::Unsupported => {
                PromptPriceAvailabilityV1::UnsupportedCausalEvidence
            }
        };
        let net_utility = if availability == PromptPriceAvailabilityV1::Available {
            estimate
                .causal_incremental_utility
                .checked_sub(total_utility_cost)
                .map_err(|_| PipelineError::Arithmetic)?
        } else {
            FixedQ32::ZERO
        };
        receipts.push(PromptPricingReceiptV1 {
            factor_id: factor_id.clone(),
            state_digest: candidates.receipt.state_digest,
            expected_utility_q32: net_utility,
            downside_q32: estimate.downside_q32,
            token_cost: cost.token_units,
            latency_cost_micros: cost.latency_cost_micros,
            interference_ppm: cost.interference_ppm,
            confidence_interval: PromptConfidenceIntervalV1 {
                lower_q32: estimate.confidence_lower_q32,
                upper_q32: estimate.confidence_upper_q32,
                confidence_ppm: estimate.confidence_ppm,
            },
        });
        audit.push(PromptPricingAuditEntryV1 {
            factor_id: factor_id.clone(),
            availability,
            causal_incremental_utility: estimate.causal_incremental_utility,
            total_utility_cost,
            net_utility,
            token_utility_cost: cost.token_utility_cost,
            latency_utility_cost: cost.latency_utility_cost,
            interference_utility_cost: cost.interference_utility_cost,
            resource_utility_cost: cost.resource_utility_cost,
            privacy_utility_cost: cost.privacy_utility_cost,
            instability_utility_cost: cost.instability_utility_cost,
            future_context_option_value_cost: cost.future_context_option_value_cost,
            causal_support_reference_digest: estimate.support_reference_digest,
            cost_support_reference_digest: cost.support_reference_digest,
        });
    }

    let batch_digest = digest_pricing_batch(
        candidates.receipt.semantic_digest(),
        candidates.audit.audit_digest,
        causal_estimates.ledger_snapshot_digest,
        causal_estimates.ledger_owner_digest,
        costs.cost_model_digest,
        &receipts,
        &audit,
    );
    Ok(PromptPricingBatchV1 {
        candidate_set: candidates.receipt,
        candidate_audit: candidates.audit,
        receipts,
        audit,
        ledger_snapshot_digest: causal_estimates.ledger_snapshot_digest,
        ledger_owner_digest: causal_estimates.ledger_owner_digest,
        cost_model_digest: costs.cost_model_digest,
        batch_digest,
    })
}

/// Exact registered-contract surface for portfolio selection.
pub fn select_portfolio(
    prices: PromptPricingBatchV1,
    interactions: PromptInteractionSetV1,
    budget: PromptPortfolioBudgetV1,
) -> Result<PromptPortfolioReceiptV1, PipelineError> {
    Ok(select_portfolio_with_audit(prices, interactions, budget)?.receipt)
}

/// Audited portfolio selection with prerequisite closures treated as atomic
/// evaluation packages and an explicit sparse interaction policy.
pub fn select_portfolio_with_audit(
    prices: PromptPricingBatchV1,
    interactions: PromptInteractionSetV1,
    budget: PromptPortfolioBudgetV1,
) -> Result<PromptPortfolioDecisionV1, PipelineError> {
    if prices.authority().grants_any() {
        return Err(PipelineError::AuthorityEscalation("pricing batch"));
    }
    let expected_batch_digest = digest_pricing_batch(
        prices.candidate_set.semantic_digest(),
        prices.candidate_audit.audit_digest,
        prices.ledger_snapshot_digest,
        prices.ledger_owner_digest,
        prices.cost_model_digest,
        &prices.receipts,
        &prices.audit,
    );
    if prices.batch_digest != expected_batch_digest {
        return Err(PipelineError::IntegrityMismatch("pricing batch digest"));
    }
    validate_candidate_audit_binding(&prices.candidate_set, &prices.candidate_audit)?;
    if prices.receipts.len() > MAX_FACTORS_V1 {
        return Err(PipelineError::CandidateLimitExceeded);
    }
    if interactions.interactions.len() > MAX_INTERACTION_EDGES_V1 {
        return Err(PipelineError::InteractionEdgeLimitExceeded);
    }
    if interactions.hard_constraints.len() > MAX_CONSTRAINT_EDGES_V1 {
        return Err(PipelineError::ConstraintEdgeLimitExceeded);
    }
    if budget.maximum_selected_factors > MAX_SELECTED_FACTORS_V1 {
        return Err(PipelineError::SelectedFactorLimitExceeded);
    }
    if budget.token_budget > MAX_TOKEN_BUDGET_V1 {
        return Err(PipelineError::TokenBudgetLimitExceeded);
    }
    if budget.valid_until_unix_ms == 0 {
        return Err(PipelineError::InvalidExpiry);
    }
    for (digest, label) in [
        (prices.batch_digest, "pricing batch"),
        (interactions.graph_snapshot_digest, "interaction graph"),
        (interactions.graph_owner_digest, "graph owner"),
    ] {
        require_digest(digest, label)?;
    }

    let receipt_map = unique_price_receipts(&prices.receipts)?;
    let audit_map = unique_price_audit(&prices.audit)?;
    if receipt_map.len() != audit_map.len() {
        return Err(PipelineError::CandidateLimitExceeded);
    }
    if receipt_map.len() != prices.candidate_set.candidate_factor_ids.len() {
        return Err(PipelineError::IntegrityMismatch("pricing factor count"));
    }
    for factor_id in &prices.candidate_set.candidate_factor_ids {
        let receipt = receipt_map
            .get(factor_id)
            .ok_or_else(|| PipelineError::MissingCausalEstimate(factor_id.to_string()))?;
        if receipt.state_digest != prices.candidate_set.state_digest {
            return Err(PipelineError::StateMismatch("pricing receipt"));
        }
        if !audit_map.contains_key(factor_id) {
            return Err(PipelineError::MissingCausalEstimate(factor_id.to_string()));
        }
    }
    let relations = RelationIndex::build(&receipt_map, &interactions)?;
    relations.validate_satisfiable(&receipt_map)?;

    let mut selected = BTreeSet::new();
    let mut ordered_selected = Vec::new();
    let mut remaining = budget.token_budget;
    let mut total_net_utility = FixedQ32::ZERO;
    let mut selection_steps = 0usize;

    while ordered_selected.len() < budget.maximum_selected_factors
        && selection_steps < MAX_SELECTION_STEPS_V1
    {
        let mut best: Option<PackageChoice> = None;
        for receipt in &prices.receipts {
            let audit_entry = audit_map.get(&receipt.factor_id).ok_or_else(|| {
                PipelineError::MissingCausalEstimate(receipt.factor_id.to_string())
            })?;
            if audit_entry.availability != PromptPriceAvailabilityV1::Available
                || selected.contains(&receipt.factor_id)
            {
                continue;
            }
            let package = relations.prerequisite_closure(&receipt.factor_id, &selected)?;
            if package.is_empty()
                || ordered_selected.len().saturating_add(package.len())
                    > budget.maximum_selected_factors
            {
                continue;
            }
            let package_cost = package_token_cost(&package, &receipt_map)?;
            if package_cost > remaining || relations.conflicts_with(&package, &selected) {
                continue;
            }
            let marginal = package_marginal_utility(
                &package,
                &selected,
                &receipt_map,
                &audit_map,
                &relations,
                interactions.unknown_interaction_policy,
            )?;
            if marginal <= FixedQ32::ZERO {
                continue;
            }
            let choice = PackageChoice {
                root_factor_id: receipt.factor_id.clone(),
                package,
                token_cost: package_cost,
                marginal,
            };
            if best
                .as_ref()
                .is_none_or(|current| choice_better(&choice, current))
            {
                best = Some(choice);
            }
        }
        let Some(best) = best else {
            break;
        };
        for factor_id in best.package {
            if selected.insert(factor_id.clone()) {
                ordered_selected.push(factor_id);
            }
        }
        remaining = remaining
            .checked_sub(best.token_cost)
            .ok_or(PipelineError::Arithmetic)?;
        total_net_utility = total_net_utility
            .checked_add(best.marginal)
            .map_err(|_| PipelineError::Arithmetic)?;
        selection_steps = selection_steps.saturating_add(1);
    }

    let interaction_digest = digest_relations(&interactions);
    let total_token_upper_bound = budget
        .token_budget
        .checked_sub(remaining)
        .ok_or(PipelineError::Arithmetic)?;
    let candidate_set_digest = prices.candidate_set.semantic_digest();
    let portfolio_id = derived_id_from_parts(
        "portfolio",
        &[
            candidate_set_digest,
            interaction_digest,
            prices.batch_digest,
        ],
    )?;
    let receipt = PromptPortfolioReceiptV1 {
        portfolio_id,
        candidate_set_digest,
        factor_ids: ordered_selected,
        interaction_digest,
        expected_utility_q32: total_net_utility,
        total_token_upper_bound,
        valid_until_unix_ms: budget.valid_until_unix_ms,
    };

    let decisions = classify_portfolio_decisions(
        &prices.receipts,
        &selected,
        remaining,
        budget
            .maximum_selected_factors
            .saturating_sub(selected.len()),
        &receipt_map,
        &audit_map,
        &relations,
        interactions.unknown_interaction_policy,
    )?;
    let selection_steps = u32::try_from(selection_steps).map_err(|_| PipelineError::Arithmetic)?;
    let mut audit = PromptPortfolioAuditV1 {
        pricing_batch_digest: prices.batch_digest,
        state_digest: prices.candidate_set.state_digest,
        objective_digest: prices.candidate_set.objective_digest,
        registry_snapshot_digest: prices.candidate_set.registry_digest,
        registry_completeness_digest: prices.candidate_audit.registry_completeness_digest,
        source_factor_count: prices.candidate_audit.source_factor_count,
        eligible_factor_count: prices.candidate_audit.eligible_factor_count,
        omitted_count: prices.candidate_audit.omitted_count,
        model_profile_digest: prices.candidate_audit.model_profile_digest,
        model_compatibility_digest: prices.candidate_audit.model_compatibility_digest,
        graph_owner_digest: interactions.graph_owner_digest,
        decisions,
        total_net_utility,
        unspent_token_budget: remaining,
        selection_steps,
        selection_method: PromptSelectionMethodV1::PrerequisiteClosureGreedyDensityV1,
        optimality: PromptOptimalityDisclosureV1::HeuristicNoCertificate,
        unknown_interaction_policy: interactions.unknown_interaction_policy,
        audit_digest: Digest32::ZERO,
    };
    audit.audit_digest = digest_portfolio_audit_record(&receipt, &audit);
    Ok(PromptPortfolioDecisionV1 { receipt, audit })
}

/// Exact registered-contract surface for exercise/timing.
pub fn exercise(
    portfolio: PromptPortfolioDecisionV1,
    registered_boundary: RegisteredPromptBoundaryV1,
    state: PromptExerciseStateV1,
) -> Result<PromptExerciseDecisionV1, PipelineError> {
    Ok(exercise_with_audit(portfolio, registered_boundary, state)?.receipt)
}

/// Exercise with explicit drift/no-intervention/wait audit semantics.
pub fn exercise_with_audit(
    portfolio: PromptPortfolioDecisionV1,
    registered_boundary: RegisteredPromptBoundaryV1,
    state: PromptExerciseStateV1,
) -> Result<PromptExerciseOutcomeV1, PipelineError> {
    if portfolio.authority().grants_any() {
        return Err(PipelineError::AuthorityEscalation("portfolio decision"));
    }
    let expected_portfolio_audit_digest =
        digest_portfolio_audit_record(&portfolio.receipt, &portfolio.audit);
    if portfolio.audit.audit_digest != expected_portfolio_audit_digest {
        return Err(PipelineError::IntegrityMismatch("portfolio audit digest"));
    }
    for (digest, label) in [
        (portfolio.receipt.semantic_digest(), "portfolio receipt"),
        (portfolio.audit.audit_digest, "portfolio audit"),
        (registered_boundary.boundary_digest, "registered boundary"),
        (state.state_digest, "exercise state"),
    ] {
        require_digest(digest, label)?;
    }

    let disposition = if state.state_digest != portfolio.audit.state_digest {
        PromptExerciseDispositionV1::InvalidatedStateDrift
    } else if registered_boundary.registry_snapshot_digest
        != portfolio.audit.registry_snapshot_digest
        || state.registry_snapshot_digest != portfolio.audit.registry_snapshot_digest
    {
        PromptExerciseDispositionV1::InvalidatedRegistryDrift
    } else if registered_boundary.model_profile_digest != portfolio.audit.model_profile_digest
        || state.model_profile_digest != portfolio.audit.model_profile_digest
    {
        PromptExerciseDispositionV1::InvalidatedModelDrift
    } else if state.objective_digest != portfolio.audit.objective_digest {
        PromptExerciseDispositionV1::InvalidatedObjectiveDrift
    } else if registered_boundary.model_compatibility_digest
        != portfolio.audit.model_compatibility_digest
        || state.model_compatibility_digest != portfolio.audit.model_compatibility_digest
    {
        PromptExerciseDispositionV1::InvalidatedBoundaryCompatibility
    } else if portfolio.receipt.factor_ids.is_empty() {
        PromptExerciseDispositionV1::NoIntervention
    } else if state.exercise_now_value_q32 < state.wait_value_q32 {
        PromptExerciseDispositionV1::WaitForHigherValue
    } else {
        PromptExerciseDispositionV1::Exercise
    };

    let decision = if disposition == PromptExerciseDispositionV1::Exercise {
        PromptExerciseActionV1::Exercise
    } else {
        PromptExerciseActionV1::Wait
    };
    let receipt = PromptExerciseDecisionV1 {
        factor_or_portfolio_id: portfolio.receipt.portfolio_id.clone(),
        decision_boundary: registered_boundary.decision_boundary,
        exercise_now_value_q32: state.exercise_now_value_q32,
        wait_value_q32: state.wait_value_q32,
        decision,
        policy_digest: portfolio.audit.audit_digest,
    };
    let audit_digest = digest_exercise_audit(
        &receipt,
        disposition,
        registered_boundary.boundary_digest,
        portfolio.receipt.semantic_digest(),
        portfolio.audit.audit_digest,
        state.state_digest,
    );
    Ok(PromptExerciseOutcomeV1 {
        receipt,
        audit: PromptExerciseAuditV1 {
            disposition,
            boundary_digest: registered_boundary.boundary_digest,
            portfolio_digest: portfolio.receipt.semantic_digest(),
            portfolio_audit_digest: portfolio.audit.audit_digest,
            state_digest: state.state_digest,
            audit_digest,
        },
    })
}

// -----------------------------------------------------------------------------
// Selection relations and validation.
// -----------------------------------------------------------------------------

#[derive(Clone)]
struct RelationIndex {
    interactions: BTreeMap<(StableId, StableId), FixedQ32>,
    requires: BTreeMap<StableId, Vec<StableId>>,
    conflicts: BTreeSet<(StableId, StableId)>,
}

impl RelationIndex {
    fn build(
        prices: &BTreeMap<StableId, PromptPricingReceiptV1>,
        input: &PromptInteractionSetV1,
    ) -> Result<Self, PipelineError> {
        let mut interactions = BTreeMap::new();
        for edge in &input.interactions {
            let key = canonical_pair(&edge.left_factor_id, &edge.right_factor_id)?;
            ensure_endpoint(prices, &key.0)?;
            ensure_endpoint(prices, &key.1)?;
            require_digest(edge.support_reference_digest, "interaction support")?;
            if interactions
                .insert(key.clone(), edge.marginal_utility)
                .is_some()
            {
                return Err(PipelineError::DuplicateRelation(
                    "interaction",
                    key.0.to_string(),
                    key.1.to_string(),
                ));
            }
        }

        let mut requires: BTreeMap<StableId, Vec<StableId>> = BTreeMap::new();
        let mut conflicts = BTreeSet::new();
        let mut constraint_keys = BTreeSet::new();
        for constraint in &input.hard_constraints {
            match constraint {
                PromptHardConstraintV1::Conflict {
                    left_factor_id,
                    right_factor_id,
                    support_reference_digest,
                } => {
                    let key = canonical_pair(left_factor_id, right_factor_id)?;
                    ensure_endpoint(prices, &key.0)?;
                    ensure_endpoint(prices, &key.1)?;
                    require_digest(*support_reference_digest, "constraint support")?;
                    if !constraint_keys.insert((0u8, key.0.clone(), key.1.clone())) {
                        return Err(PipelineError::DuplicateRelation(
                            "conflict",
                            key.0.to_string(),
                            key.1.to_string(),
                        ));
                    }
                    conflicts.insert(key);
                }
                PromptHardConstraintV1::Requires {
                    factor_id,
                    prerequisite_factor_id,
                    support_reference_digest,
                } => {
                    if factor_id == prerequisite_factor_id {
                        return Err(PipelineError::InvalidRelationEndpoints);
                    }
                    ensure_endpoint(prices, factor_id)?;
                    ensure_endpoint(prices, prerequisite_factor_id)?;
                    require_digest(*support_reference_digest, "constraint support")?;
                    if !constraint_keys.insert((
                        1u8,
                        factor_id.clone(),
                        prerequisite_factor_id.clone(),
                    )) {
                        return Err(PipelineError::DuplicateRelation(
                            "requires",
                            factor_id.to_string(),
                            prerequisite_factor_id.to_string(),
                        ));
                    }
                    requires
                        .entry(factor_id.clone())
                        .or_default()
                        .push(prerequisite_factor_id.clone());
                }
            }
        }
        for prerequisites in requires.values_mut() {
            prerequisites.sort();
        }
        Ok(Self {
            interactions,
            requires,
            conflicts,
        })
    }

    fn validate_satisfiable(
        &self,
        prices: &BTreeMap<StableId, PromptPricingReceiptV1>,
    ) -> Result<(), PipelineError> {
        for factor_id in prices.keys() {
            let mut visiting = BTreeSet::new();
            let mut visited = BTreeSet::new();
            self.detect_cycle(factor_id, &mut visiting, &mut visited)?;
            let closure = self.prerequisite_closure(factor_id, &BTreeSet::new())?;
            if self.package_has_internal_conflict(&closure) {
                return Err(PipelineError::UnsatisfiableConstraintGraph(
                    factor_id.to_string(),
                ));
            }
        }
        Ok(())
    }

    fn detect_cycle(
        &self,
        node: &StableId,
        visiting: &mut BTreeSet<StableId>,
        visited: &mut BTreeSet<StableId>,
    ) -> Result<(), PipelineError> {
        if visited.contains(node) {
            return Ok(());
        }
        if !visiting.insert(node.clone()) {
            return Err(PipelineError::RequiresCycle(node.to_string()));
        }
        if let Some(prerequisites) = self.requires.get(node) {
            for prerequisite in prerequisites {
                self.detect_cycle(prerequisite, visiting, visited)?;
            }
        }
        visiting.remove(node);
        visited.insert(node.clone());
        Ok(())
    }

    fn prerequisite_closure(
        &self,
        root: &StableId,
        already_selected: &BTreeSet<StableId>,
    ) -> Result<Vec<StableId>, PipelineError> {
        let mut visiting = BTreeSet::new();
        let mut emitted = BTreeSet::new();
        let mut ordered = Vec::new();
        self.emit_closure(
            root,
            already_selected,
            &mut visiting,
            &mut emitted,
            &mut ordered,
        )?;
        Ok(ordered)
    }

    fn emit_closure(
        &self,
        node: &StableId,
        already_selected: &BTreeSet<StableId>,
        visiting: &mut BTreeSet<StableId>,
        emitted: &mut BTreeSet<StableId>,
        ordered: &mut Vec<StableId>,
    ) -> Result<(), PipelineError> {
        if already_selected.contains(node) || emitted.contains(node) {
            return Ok(());
        }
        if !visiting.insert(node.clone()) {
            return Err(PipelineError::RequiresCycle(node.to_string()));
        }
        if let Some(prerequisites) = self.requires.get(node) {
            for prerequisite in prerequisites {
                self.emit_closure(prerequisite, already_selected, visiting, emitted, ordered)?;
            }
        }
        visiting.remove(node);
        if emitted.insert(node.clone()) {
            ordered.push(node.clone());
        }
        Ok(())
    }

    fn conflicts_with(&self, package: &[StableId], selected: &BTreeSet<StableId>) -> bool {
        if self.package_has_internal_conflict(package) {
            return true;
        }
        package.iter().any(|factor_id| {
            selected
                .iter()
                .any(|peer| self.conflicts.contains(&ordered_pair(factor_id, peer)))
        })
    }

    fn package_has_internal_conflict(&self, package: &[StableId]) -> bool {
        for (index, left) in package.iter().enumerate() {
            for right in package.iter().skip(index + 1) {
                if self.conflicts.contains(&ordered_pair(left, right)) {
                    return true;
                }
            }
        }
        false
    }

    fn interaction(
        &self,
        left: &StableId,
        right: &StableId,
        policy: UnknownInteractionPolicyV1,
    ) -> Result<FixedQ32, PipelineError> {
        if left == right {
            return Ok(FixedQ32::ZERO);
        }
        let key = ordered_pair(left, right);
        if let Some(value) = self.interactions.get(&key) {
            return Ok(*value);
        }
        match policy {
            UnknownInteractionPolicyV1::MissingAsZero => Ok(FixedQ32::ZERO),
            UnknownInteractionPolicyV1::RejectMissing => Err(
                PipelineError::MissingPairInteraction(key.0.to_string(), key.1.to_string()),
            ),
        }
    }
}

#[derive(Clone)]
struct PackageChoice {
    root_factor_id: StableId,
    package: Vec<StableId>,
    token_cost: u32,
    marginal: FixedQ32,
}

fn choice_better(left: &PackageChoice, right: &PackageChoice) -> bool {
    let left_density = i128::from(left.marginal.raw()) * i128::from(right.token_cost.max(1));
    let right_density = i128::from(right.marginal.raw()) * i128::from(left.token_cost.max(1));
    left_density > right_density
        || (left_density == right_density
            && (left.marginal > right.marginal
                || (left.marginal == right.marginal
                    && (left.token_cost < right.token_cost
                        || (left.token_cost == right.token_cost
                            && left.root_factor_id < right.root_factor_id)))))
}

fn package_token_cost(
    package: &[StableId],
    prices: &BTreeMap<StableId, PromptPricingReceiptV1>,
) -> Result<u32, PipelineError> {
    package.iter().try_fold(0u32, |total, factor_id| {
        let price = prices
            .get(factor_id)
            .ok_or_else(|| PipelineError::UnknownRelationEndpoint(factor_id.to_string()))?;
        total
            .checked_add(price.token_cost)
            .ok_or(PipelineError::Arithmetic)
    })
}

fn package_marginal_utility(
    package: &[StableId],
    selected: &BTreeSet<StableId>,
    prices: &BTreeMap<StableId, PromptPricingReceiptV1>,
    audit: &BTreeMap<StableId, PromptPricingAuditEntryV1>,
    relations: &RelationIndex,
    policy: UnknownInteractionPolicyV1,
) -> Result<FixedQ32, PipelineError> {
    let mut marginal = FixedQ32::ZERO;
    for factor_id in package {
        let price = prices
            .get(factor_id)
            .ok_or_else(|| PipelineError::UnknownRelationEndpoint(factor_id.to_string()))?;
        let audit_entry = audit
            .get(factor_id)
            .ok_or_else(|| PipelineError::MissingCausalEstimate(factor_id.to_string()))?;
        if audit_entry.availability != PromptPriceAvailabilityV1::Available {
            return Ok(FixedQ32::ZERO);
        }
        marginal = marginal
            .checked_add(price.expected_utility_q32)
            .map_err(|_| PipelineError::Arithmetic)?;
    }
    for factor_id in package {
        for peer in selected {
            marginal = marginal
                .checked_add(relations.interaction(factor_id, peer, policy)?)
                .map_err(|_| PipelineError::Arithmetic)?;
        }
    }
    for (index, left) in package.iter().enumerate() {
        for right in package.iter().skip(index + 1) {
            marginal = marginal
                .checked_add(relations.interaction(left, right, policy)?)
                .map_err(|_| PipelineError::Arithmetic)?;
        }
    }
    Ok(marginal)
}

#[allow(clippy::too_many_arguments)]
fn classify_portfolio_decisions(
    prices: &[PromptPricingReceiptV1],
    selected: &BTreeSet<StableId>,
    remaining_budget: u32,
    remaining_slots: usize,
    price_map: &BTreeMap<StableId, PromptPricingReceiptV1>,
    audit_map: &BTreeMap<StableId, PromptPricingAuditEntryV1>,
    relations: &RelationIndex,
    policy: UnknownInteractionPolicyV1,
) -> Result<Vec<PromptPortfolioCandidateDecisionV1>, PipelineError> {
    let mut decisions = Vec::with_capacity(prices.len());
    for price in prices {
        let full_closure = relations.prerequisite_closure(&price.factor_id, &BTreeSet::new())?;
        let remaining_closure = relations.prerequisite_closure(&price.factor_id, selected)?;
        let audit = audit_map
            .get(&price.factor_id)
            .ok_or_else(|| PipelineError::MissingCausalEstimate(price.factor_id.to_string()))?;
        let disposition = if selected.contains(&price.factor_id) {
            PromptPortfolioDispositionV1::Selected
        } else if audit.availability != PromptPriceAvailabilityV1::Available {
            PromptPortfolioDispositionV1::UnavailablePricing
        } else if remaining_closure.len() > remaining_slots {
            PromptPortfolioDispositionV1::SelectionLimit
        } else if relations.conflicts_with(&remaining_closure, selected) {
            PromptPortfolioDispositionV1::Conflict
        } else if package_token_cost(&remaining_closure, price_map)? > remaining_budget {
            PromptPortfolioDispositionV1::OverBudget
        } else if package_marginal_utility(
            &remaining_closure,
            selected,
            price_map,
            audit_map,
            relations,
            policy,
        )? <= FixedQ32::ZERO
        {
            PromptPortfolioDispositionV1::NonPositiveMarginal
        } else {
            PromptPortfolioDispositionV1::HeuristicNotSelected
        };
        decisions.push(PromptPortfolioCandidateDecisionV1 {
            factor_id: price.factor_id.clone(),
            disposition,
            prerequisite_closure: full_closure,
            confidence_ppm: price.confidence_interval.confidence_ppm,
            token_cost: price.token_cost,
            standalone_net_utility: price.expected_utility_q32,
            causal_support_reference_digest: audit.causal_support_reference_digest,
            cost_support_reference_digest: audit.cost_support_reference_digest,
        });
    }
    Ok(decisions)
}

// -----------------------------------------------------------------------------
// Input validation helpers.
// -----------------------------------------------------------------------------

fn validate_candidate_audit_binding(
    receipt: &PromptCandidateSetReceiptV1,
    audit: &PromptCandidateSetAuditV1,
) -> Result<(), PipelineError> {
    let candidate_set_digest = receipt.semantic_digest();
    if audit.candidate_set_digest != candidate_set_digest {
        return Err(PipelineError::IntegrityMismatch(
            "candidate set audit binding",
        ));
    }
    let expected_audit_digest = digest_candidate_audit(
        candidate_set_digest,
        audit.registry_owner_digest,
        audit.registry_completeness_digest,
        audit.model_profile_digest,
        audit.model_compatibility_digest,
        audit.source_factor_count,
        audit.eligible_factor_count,
        audit.omitted_count,
        &audit.candidates,
        &audit.decisions,
    );
    if audit.audit_digest != expected_audit_digest {
        return Err(PipelineError::IntegrityMismatch("candidate audit digest"));
    }
    let included_count = u32::try_from(receipt.candidate_factor_ids.len())
        .map_err(|_| PipelineError::CandidateLimitExceeded)?;
    if audit.source_factor_count < audit.eligible_factor_count
        || audit.eligible_factor_count < included_count
        || audit.omitted_count != audit.eligible_factor_count - included_count
    {
        return Err(PipelineError::IntegrityMismatch(
            "candidate completeness counts",
        ));
    }
    let decision_count = u32::try_from(audit.decisions.len())
        .map_err(|_| PipelineError::SourceFactorLimitExceeded)?;
    if decision_count != audit.source_factor_count
        || audit.candidates.len() != receipt.candidate_factor_ids.len()
    {
        return Err(PipelineError::IntegrityMismatch(
            "candidate audit cardinality",
        ));
    }
    let binding_factor_ids = audit
        .candidates
        .iter()
        .map(|binding| binding.factor_id.clone())
        .collect::<Vec<_>>();
    if binding_factor_ids.as_slice() != receipt.candidate_factor_ids.as_slice() {
        return Err(PipelineError::IntegrityMismatch("candidate binding order"));
    }
    let included_decisions = audit
        .decisions
        .iter()
        .filter(|decision| decision.disposition == PromptEnumerationDispositionV1::Included)
        .map(|decision| decision.factor_id.clone())
        .collect::<Vec<_>>();
    if included_decisions.as_slice() != receipt.candidate_factor_ids.as_slice() {
        return Err(PipelineError::IntegrityMismatch(
            "candidate inclusion decisions",
        ));
    }
    Ok(())
}

fn validate_estimate(estimate: &PromptCausalEstimateV1) -> Result<(), PipelineError> {
    require_id(&estimate.factor_id, "causal factor")?;
    require_digest(estimate.estimator_digest, "causal estimator")?;
    require_digest(estimate.support_reference_digest, "causal support")?;
    if estimate.confidence_ppm > MAX_CONFIDENCE_PPM {
        return Err(PipelineError::ConfidenceOutOfRange(
            estimate.factor_id.to_string(),
        ));
    }
    if estimate.confidence_lower_q32 > estimate.confidence_upper_q32 {
        return Err(PipelineError::InvalidConfidenceInterval(
            estimate.factor_id.to_string(),
        ));
    }
    Ok(())
}

fn validate_cost(cost: &PromptCostBreakdownV1) -> Result<(), PipelineError> {
    require_id(&cost.factor_id, "cost factor")?;
    require_digest(cost.support_reference_digest, "cost support")?;
    if cost.interference_ppm > MAX_INTERFERENCE_PPM {
        return Err(PipelineError::InterferenceOutOfRange(
            cost.factor_id.to_string(),
        ));
    }
    Ok(())
}

fn unique_estimates(
    values: Vec<PromptCausalEstimateV1>,
) -> Result<BTreeMap<StableId, PromptCausalEstimateV1>, PipelineError> {
    let mut map = BTreeMap::new();
    for value in values {
        let key = value.factor_id.clone();
        if map.insert(key.clone(), value).is_some() {
            return Err(PipelineError::DuplicateEvidence(key.to_string()));
        }
    }
    Ok(map)
}

fn unique_costs(
    values: Vec<PromptCostBreakdownV1>,
) -> Result<BTreeMap<StableId, PromptCostBreakdownV1>, PipelineError> {
    let mut map = BTreeMap::new();
    for value in values {
        let key = value.factor_id.clone();
        if map.insert(key.clone(), value).is_some() {
            return Err(PipelineError::DuplicateCost(key.to_string()));
        }
    }
    Ok(map)
}

fn reject_extra_keys<'a>(
    allowed: &BTreeSet<StableId>,
    keys: impl Iterator<Item = &'a StableId>,
    evidence: bool,
) -> Result<(), PipelineError> {
    for key in keys {
        if !allowed.contains(key) {
            return if evidence {
                Err(PipelineError::ExtraCausalEstimate(key.to_string()))
            } else {
                Err(PipelineError::ExtraCost(key.to_string()))
            };
        }
    }
    Ok(())
}

fn unique_price_receipts(
    values: &[PromptPricingReceiptV1],
) -> Result<BTreeMap<StableId, PromptPricingReceiptV1>, PipelineError> {
    let mut map = BTreeMap::new();
    for value in values {
        let key = value.factor_id.clone();
        if map.insert(key.clone(), value.clone()).is_some() {
            return Err(PipelineError::DuplicateFactor(key.to_string()));
        }
    }
    Ok(map)
}

fn unique_price_audit(
    values: &[PromptPricingAuditEntryV1],
) -> Result<BTreeMap<StableId, PromptPricingAuditEntryV1>, PipelineError> {
    let mut map = BTreeMap::new();
    for value in values {
        let key = value.factor_id.clone();
        if map.insert(key.clone(), value.clone()).is_some() {
            return Err(PipelineError::DuplicateEvidence(key.to_string()));
        }
    }
    Ok(map)
}

fn ensure_endpoint(
    prices: &BTreeMap<StableId, PromptPricingReceiptV1>,
    value: &StableId,
) -> Result<(), PipelineError> {
    if prices.contains_key(value) {
        Ok(())
    } else {
        Err(PipelineError::UnknownRelationEndpoint(value.to_string()))
    }
}

fn canonical_pair(
    left: &StableId,
    right: &StableId,
) -> Result<(StableId, StableId), PipelineError> {
    if left == right {
        return Err(PipelineError::InvalidRelationEndpoints);
    }
    Ok(ordered_pair(left, right))
}

fn ordered_pair(left: &StableId, right: &StableId) -> (StableId, StableId) {
    if left < right {
        (left.clone(), right.clone())
    } else {
        (right.clone(), left.clone())
    }
}

fn checked_sum(values: &[FixedQ32]) -> Result<FixedQ32, PipelineError> {
    values.iter().try_fold(FixedQ32::ZERO, |total, value| {
        total
            .checked_add(*value)
            .map_err(|_| PipelineError::Arithmetic)
    })
}

fn require_digest(value: Digest32, label: &'static str) -> Result<(), PipelineError> {
    if value.is_zero() {
        Err(PipelineError::EmptyDigest(label))
    } else {
        Ok(())
    }
}

fn require_id(value: &StableId, label: &'static str) -> Result<(), PipelineError> {
    if value.as_str().is_empty() {
        Err(PipelineError::EmptyIdentifier(label))
    } else {
        Ok(())
    }
}

fn derived_id_from_parts(prefix: &str, digests: &[Digest32]) -> Result<StableId, PipelineError> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(prefix.as_bytes());
    for digest in digests {
        bytes.extend_from_slice(digest.as_array());
    }
    let digest = Digest32::of_bytes(&bytes).to_string();
    StableId::new(format!("{prefix}:{}", &digest[..24]))
        .map_err(|_| PipelineError::IdentifierDerivation)
}

// -----------------------------------------------------------------------------
// Deterministic semantic digests.
// -----------------------------------------------------------------------------

fn digest_candidate_contract(value: &PromptCandidateSetReceiptV1) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-candidate-set-receipt-v1");
    push_id(&mut bytes, &value.set_id);
    bytes.extend_from_slice(value.objective_digest.as_array());
    bytes.extend_from_slice(value.state_digest.as_array());
    bytes.extend_from_slice(value.registry_digest.as_array());
    push_len(&mut bytes, value.candidate_factor_ids.len());
    for factor_id in &value.candidate_factor_ids {
        push_id(&mut bytes, factor_id);
    }
    bytes.extend_from_slice(value.selection_grammar_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_pricing_contract(value: &PromptPricingReceiptV1) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-pricing-receipt-v1");
    push_id(&mut bytes, &value.factor_id);
    bytes.extend_from_slice(value.state_digest.as_array());
    bytes.extend_from_slice(&value.expected_utility_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&value.downside_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&value.token_cost.to_be_bytes());
    bytes.extend_from_slice(&value.latency_cost_micros.to_be_bytes());
    bytes.extend_from_slice(&value.interference_ppm.to_be_bytes());
    bytes.extend_from_slice(&value.confidence_interval.lower_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&value.confidence_interval.upper_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&value.confidence_interval.confidence_ppm.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn digest_portfolio_contract(value: &PromptPortfolioReceiptV1) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-portfolio-receipt-v1");
    push_id(&mut bytes, &value.portfolio_id);
    bytes.extend_from_slice(value.candidate_set_digest.as_array());
    push_len(&mut bytes, value.factor_ids.len());
    for factor_id in &value.factor_ids {
        push_id(&mut bytes, factor_id);
    }
    bytes.extend_from_slice(value.interaction_digest.as_array());
    bytes.extend_from_slice(&value.expected_utility_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&value.total_token_upper_bound.to_be_bytes());
    bytes.extend_from_slice(&value.valid_until_unix_ms.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn digest_exercise_contract(value: &PromptExerciseDecisionV1) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-exercise-decision-v1");
    push_id(&mut bytes, &value.factor_or_portfolio_id);
    bytes.push(boundary_code(value.decision_boundary));
    bytes.extend_from_slice(&value.exercise_now_value_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&value.wait_value_q32.raw().to_be_bytes());
    bytes.push(exercise_action_code(value.decision));
    bytes.extend_from_slice(value.policy_digest.as_array());
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn digest_candidate_audit(
    candidate_set_digest: Digest32,
    registry_owner_digest: Digest32,
    registry_completeness_digest: Digest32,
    model_profile_digest: Digest32,
    model_compatibility_digest: Digest32,
    source_factor_count: u32,
    eligible_factor_count: u32,
    omitted_count: u32,
    bindings: &[PromptCandidateBindingV1],
    decisions: &[PromptEnumerationDecisionV1],
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-candidate-set-audit-v1");
    for digest in [
        candidate_set_digest,
        registry_owner_digest,
        registry_completeness_digest,
        model_profile_digest,
        model_compatibility_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&source_factor_count.to_be_bytes());
    bytes.extend_from_slice(&eligible_factor_count.to_be_bytes());
    bytes.extend_from_slice(&omitted_count.to_be_bytes());
    push_len(&mut bytes, bindings.len());
    for binding in bindings {
        push_id(&mut bytes, &binding.candidate_id);
        push_id(&mut bytes, &binding.factor_id);
        push_id(&mut bytes, &binding.realization_id);
        bytes.extend_from_slice(&binding.token_upper_bound.to_be_bytes());
        bytes.extend_from_slice(binding.registry_entry_digest.as_array());
        bytes.extend_from_slice(binding.support_reference_digest.as_array());
    }
    push_len(&mut bytes, decisions.len());
    for decision in decisions {
        push_id(&mut bytes, &decision.candidate_id);
        push_id(&mut bytes, &decision.factor_id);
        bytes.push(enumeration_code(decision.disposition));
    }
    Digest32::of_bytes(&bytes)
}

fn digest_pricing_batch(
    candidate_set_digest: Digest32,
    candidate_audit_digest: Digest32,
    ledger_snapshot_digest: Digest32,
    ledger_owner_digest: Digest32,
    cost_model_digest: Digest32,
    receipts: &[PromptPricingReceiptV1],
    audit: &[PromptPricingAuditEntryV1],
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-pricing-batch-v1");
    for digest in [
        candidate_set_digest,
        candidate_audit_digest,
        ledger_snapshot_digest,
        ledger_owner_digest,
        cost_model_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_len(&mut bytes, receipts.len());
    for receipt in receipts {
        bytes.extend_from_slice(receipt.semantic_digest().as_array());
    }
    push_len(&mut bytes, audit.len());
    for entry in audit {
        push_id(&mut bytes, &entry.factor_id);
        bytes.push(price_availability_code(entry.availability));
        bytes.extend_from_slice(&entry.causal_incremental_utility.raw().to_be_bytes());
        bytes.extend_from_slice(&entry.total_utility_cost.raw().to_be_bytes());
        bytes.extend_from_slice(&entry.net_utility.raw().to_be_bytes());
        for component in [
            entry.token_utility_cost,
            entry.latency_utility_cost,
            entry.interference_utility_cost,
            entry.resource_utility_cost,
            entry.privacy_utility_cost,
            entry.instability_utility_cost,
            entry.future_context_option_value_cost,
        ] {
            bytes.extend_from_slice(&component.raw().to_be_bytes());
        }
        bytes.extend_from_slice(entry.causal_support_reference_digest.as_array());
        bytes.extend_from_slice(entry.cost_support_reference_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_relations(input: &PromptInteractionSetV1) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-relations-v1");
    bytes.extend_from_slice(input.graph_snapshot_digest.as_array());
    bytes.extend_from_slice(input.graph_owner_digest.as_array());
    bytes.push(interaction_policy_code(input.unknown_interaction_policy));
    push_len(&mut bytes, input.interactions.len());
    for edge in &input.interactions {
        push_id(&mut bytes, &edge.left_factor_id);
        push_id(&mut bytes, &edge.right_factor_id);
        bytes.extend_from_slice(&edge.marginal_utility.raw().to_be_bytes());
        bytes.extend_from_slice(edge.support_reference_digest.as_array());
    }
    push_len(&mut bytes, input.hard_constraints.len());
    for constraint in &input.hard_constraints {
        match constraint {
            PromptHardConstraintV1::Conflict {
                left_factor_id,
                right_factor_id,
                support_reference_digest,
            } => {
                bytes.push(0);
                push_id(&mut bytes, left_factor_id);
                push_id(&mut bytes, right_factor_id);
                bytes.extend_from_slice(support_reference_digest.as_array());
            }
            PromptHardConstraintV1::Requires {
                factor_id,
                prerequisite_factor_id,
                support_reference_digest,
            } => {
                bytes.push(1);
                push_id(&mut bytes, factor_id);
                push_id(&mut bytes, prerequisite_factor_id);
                bytes.extend_from_slice(support_reference_digest.as_array());
            }
        }
    }
    Digest32::of_bytes(&bytes)
}

fn digest_portfolio_audit_record(
    receipt: &PromptPortfolioReceiptV1,
    audit: &PromptPortfolioAuditV1,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-portfolio-audit-v1");
    bytes.extend_from_slice(receipt.semantic_digest().as_array());
    for digest in [
        audit.pricing_batch_digest,
        audit.state_digest,
        audit.objective_digest,
        audit.registry_snapshot_digest,
        audit.registry_completeness_digest,
        audit.model_profile_digest,
        audit.model_compatibility_digest,
        audit.graph_owner_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&audit.source_factor_count.to_be_bytes());
    bytes.extend_from_slice(&audit.eligible_factor_count.to_be_bytes());
    bytes.extend_from_slice(&audit.omitted_count.to_be_bytes());
    push_len(&mut bytes, audit.decisions.len());
    for decision in &audit.decisions {
        push_id(&mut bytes, &decision.factor_id);
        bytes.push(portfolio_disposition_code(decision.disposition));
        push_len(&mut bytes, decision.prerequisite_closure.len());
        for factor_id in &decision.prerequisite_closure {
            push_id(&mut bytes, factor_id);
        }
        bytes.extend_from_slice(&decision.confidence_ppm.to_be_bytes());
        bytes.extend_from_slice(&decision.token_cost.to_be_bytes());
        bytes.extend_from_slice(&decision.standalone_net_utility.raw().to_be_bytes());
        bytes.extend_from_slice(decision.causal_support_reference_digest.as_array());
        bytes.extend_from_slice(decision.cost_support_reference_digest.as_array());
    }
    bytes.extend_from_slice(&audit.total_net_utility.raw().to_be_bytes());
    bytes.extend_from_slice(&audit.unspent_token_budget.to_be_bytes());
    bytes.extend_from_slice(&audit.selection_steps.to_be_bytes());
    bytes.push(selection_method_code(audit.selection_method));
    bytes.push(optimality_code(audit.optimality));
    bytes.push(interaction_policy_code(audit.unknown_interaction_policy));
    Digest32::of_bytes(&bytes)
}

fn digest_exercise_audit(
    receipt: &PromptExerciseDecisionV1,
    disposition: PromptExerciseDispositionV1,
    boundary_digest: Digest32,
    portfolio_digest: Digest32,
    portfolio_audit_digest: Digest32,
    state_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-exercise-audit-v1");
    bytes.extend_from_slice(receipt.semantic_digest().as_array());
    bytes.push(exercise_disposition_code(disposition));
    for digest in [
        boundary_digest,
        portfolio_digest,
        portfolio_audit_digest,
        state_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn push_len(bytes: &mut Vec<u8>, len: usize) {
    let value = u64::try_from(len).unwrap_or(u64::MAX);
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn enumeration_code(value: PromptEnumerationDispositionV1) -> u8 {
    match value {
        PromptEnumerationDispositionV1::Included => 0,
        PromptEnumerationDispositionV1::NotAdmitted => 1,
        PromptEnumerationDispositionV1::Illegal => 2,
        PromptEnumerationDispositionV1::ObjectiveScopeMismatch => 3,
        PromptEnumerationDispositionV1::ModelIncompatible => 4,
        PromptEnumerationDispositionV1::Truncated => 5,
    }
}

fn price_availability_code(value: PromptPriceAvailabilityV1) -> u8 {
    match value {
        PromptPriceAvailabilityV1::Available => 0,
        PromptPriceAvailabilityV1::UnsupportedCausalEvidence => 1,
    }
}

fn interaction_policy_code(value: UnknownInteractionPolicyV1) -> u8 {
    match value {
        UnknownInteractionPolicyV1::MissingAsZero => 0,
        UnknownInteractionPolicyV1::RejectMissing => 1,
    }
}

fn portfolio_disposition_code(value: PromptPortfolioDispositionV1) -> u8 {
    match value {
        PromptPortfolioDispositionV1::Selected => 0,
        PromptPortfolioDispositionV1::UnavailablePricing => 1,
        PromptPortfolioDispositionV1::NonPositiveMarginal => 2,
        PromptPortfolioDispositionV1::OverBudget => 3,
        PromptPortfolioDispositionV1::SelectionLimit => 4,
        PromptPortfolioDispositionV1::Conflict => 5,
        PromptPortfolioDispositionV1::HeuristicNotSelected => 6,
    }
}

fn selection_method_code(value: PromptSelectionMethodV1) -> u8 {
    match value {
        PromptSelectionMethodV1::PrerequisiteClosureGreedyDensityV1 => 0,
    }
}

fn optimality_code(value: PromptOptimalityDisclosureV1) -> u8 {
    match value {
        PromptOptimalityDisclosureV1::HeuristicNoCertificate => 0,
    }
}

fn boundary_code(value: PromptDecisionBoundaryV1) -> u8 {
    match value {
        PromptDecisionBoundaryV1::RequestAccepted => 0,
        PromptDecisionBoundaryV1::ObjectiveCompiled => 1,
        PromptDecisionBoundaryV1::BeforePlanning => 2,
        PromptDecisionBoundaryV1::BeforeCandidateGeneration => 3,
        PromptDecisionBoundaryV1::BeforeModelOrToolDispatch => 4,
        PromptDecisionBoundaryV1::AfterObservation => 5,
        PromptDecisionBoundaryV1::AfterFailureOrUncertaintySpike => 6,
        PromptDecisionBoundaryV1::BeforeIrreversibleMutation => 7,
        PromptDecisionBoundaryV1::BeforeVerification => 8,
        PromptDecisionBoundaryV1::BeforeFinalResponse => 9,
        PromptDecisionBoundaryV1::BeforeCompactOrHandoff => 10,
    }
}

fn exercise_action_code(value: PromptExerciseActionV1) -> u8 {
    match value {
        PromptExerciseActionV1::Exercise => 0,
        PromptExerciseActionV1::Wait => 1,
    }
}

fn exercise_disposition_code(value: PromptExerciseDispositionV1) -> u8 {
    match value {
        PromptExerciseDispositionV1::Exercise => 0,
        PromptExerciseDispositionV1::WaitForHigherValue => 1,
        PromptExerciseDispositionV1::NoIntervention => 2,
        PromptExerciseDispositionV1::InvalidatedStateDrift => 3,
        PromptExerciseDispositionV1::InvalidatedRegistryDrift => 4,
        PromptExerciseDispositionV1::InvalidatedModelDrift => 5,
        PromptExerciseDispositionV1::InvalidatedObjectiveDrift => 6,
        PromptExerciseDispositionV1::InvalidatedBoundaryCompatibility => 7,
    }
}

#[cfg(test)]
#[path = "pipeline_tests.rs"]
mod tests;
