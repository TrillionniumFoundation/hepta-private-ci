// ---------------------------------------------------------------------------
// Shared validation and semantic digests.
// ---------------------------------------------------------------------------

fn validate_identifier(value: &StableId, label: &'static str) -> Result<(), PolicyError> {
    if value.as_str().is_empty() {
        return Err(PolicyError::EmptyIdentifier(label));
    }
    Ok(())
}

fn validate_nonzero_digest(value: Digest32, label: &'static str) -> Result<(), PolicyError> {
    if value.is_zero() {
        return Err(PolicyError::EmptyDigest(label));
    }
    Ok(())
}

fn derived_id(prefix: &str, digest: Digest32) -> Result<StableId, PolicyError> {
    StableId::new(format!("{prefix}:{digest}")).map_err(|_| PolicyError::DerivedIdentifier)
}

pub fn digest_candidate_set_receipt(receipt: &PromptCandidateSetReceiptV1) -> Digest32 {
    let mut digest = SemanticDigest::new(b"hepta.prompt-candidate-set-receipt.v1");
    digest.id(&receipt.set_id);
    digest.digest(receipt.objective_digest);
    digest.digest(receipt.state_digest);
    digest.digest(receipt.registry_digest);
    digest.ids(&receipt.candidate_factor_ids);
    digest.digest(receipt.selection_grammar_digest);
    digest.finish()
}

pub fn digest_pricing_receipt(receipt: &PromptPricingReceiptV1) -> Digest32 {
    let mut digest = SemanticDigest::new(b"hepta.prompt-pricing-receipt.v1");
    digest.id(&receipt.factor_id);
    digest.digest(receipt.state_digest);
    digest.fixed(receipt.expected_utility_q32);
    digest.fixed(receipt.downside_q32);
    digest.u32(receipt.token_cost);
    digest.u64(receipt.latency_cost_micros);
    digest.u32(receipt.interference_ppm);
    digest.fixed(receipt.confidence_interval.lower_q32);
    digest.fixed(receipt.confidence_interval.upper_q32);
    digest.u32(receipt.confidence_interval.confidence_ppm);
    digest.digest(receipt.confidence_interval.support_digest);
    digest.digest(receipt.confidence_interval.scope_digest);
    digest.finish()
}

pub fn digest_portfolio_receipt(receipt: &PromptPortfolioReceiptV1) -> Digest32 {
    let mut digest = SemanticDigest::new(b"hepta.prompt-portfolio-receipt.v1");
    digest.id(&receipt.portfolio_id);
    digest.digest(receipt.candidate_set_digest);
    digest.ids(&receipt.factor_ids);
    digest.digest(receipt.interaction_digest);
    digest.fixed(receipt.expected_utility_q32);
    digest.u32(receipt.total_token_upper_bound);
    digest.u64(receipt.valid_until_unix_ms);
    digest.finish()
}

pub fn digest_exercise_decision(receipt: &PromptExerciseDecisionV1) -> Digest32 {
    let mut digest = SemanticDigest::new(b"hepta.prompt-exercise-decision.v1");
    digest.id(&receipt.factor_or_portfolio_id);
    digest.u8(boundary_code(receipt.decision_boundary));
    digest.fixed(receipt.exercise_now_value_q32);
    digest.fixed(receipt.wait_value_q32);
    digest.u8(match receipt.decision {
        PromptExerciseChoiceV1::Exercise => 0,
        PromptExerciseChoiceV1::Wait => 1,
        PromptExerciseChoiceV1::NoChange => 2,
    });
    digest.digest(receipt.policy_digest);
    digest.finish()
}

fn digest_complete_eligible_set(factors: &[PromptFactorSnapshotV1]) -> Digest32 {
    let mut digest = SemanticDigest::new(b"hepta.prompt-complete-eligible-set.v1");
    for factor in factors {
        digest.id(&factor.factor_id);
        digest.id(&factor.realization_id);
        digest.digest(factor.realization_context_digest);
        digest.u32(factor.token_upper_bound);
        digest.digest(factor.support_reference_digest);
    }
    digest.finish()
}

fn digest_enumeration_seed(
    registry_digest: Digest32,
    objective: &PromptObjectiveContextV1,
    model_profile: &PromptModelProfileV1,
    complete_eligible_set_digest: Digest32,
) -> Digest32 {
    let mut digest = SemanticDigest::new(b"hepta.prompt-enumeration-seed.v1");
    digest.digest(registry_digest);
    digest.digest(objective.objective_digest);
    digest.digest(objective.state_digest);
    digest.digest(objective.selection_grammar_digest);
    digest.digest(model_profile.profile_digest);
    digest.digest(complete_eligible_set_digest);
    digest.finish()
}

fn digest_model_profile(profile: &PromptModelProfileV1) -> Digest32 {
    let mut digest = SemanticDigest::new(b"hepta.prompt-model-profile.v1");
    digest.digest(profile.profile_digest);
    digest.digest(profile.tokenizer_digest);
    digest.digest(profile.system_template_digest);
    digest.digest(profile.tool_schema_digest);
    digest.digest(profile.context_profile_digest);
    digest.finish()
}

#[allow(clippy::too_many_arguments)]
fn digest_candidate_set_audit(
    candidate_set_digest: Digest32,
    source_evidence_digest: Digest32,
    model_profile_digest: Digest32,
    model_tuple_digest: Digest32,
    complete_eligible_set_digest: Digest32,
    eligible_before_truncation: u32,
    retained_count: u32,
    omitted_count: u32,
    bindings: &[PromptCandidateBindingV1],
    decisions: &[PromptEnumerationCandidateAuditV1],
) -> Digest32 {
    let mut digest = SemanticDigest::new(b"hepta.prompt-candidate-set-audit.v1");
    digest.digest(candidate_set_digest);
    digest.digest(source_evidence_digest);
    digest.digest(model_profile_digest);
    digest.digest(model_tuple_digest);
    digest.digest(complete_eligible_set_digest);
    digest.u32(eligible_before_truncation);
    digest.u32(retained_count);
    digest.u32(omitted_count);
    for binding in bindings {
        digest.id(&binding.factor_id);
        digest.id(&binding.realization_id);
        digest.digest(binding.model_profile_digest);
        digest.digest(binding.realization_context_digest);
        digest.u32(binding.token_upper_bound);
        digest.digest(binding.support_reference_digest);
    }
    for decision in decisions {
        digest.id(&decision.factor_id);
        digest.u8(enumeration_disposition_code(decision.disposition));
    }
    digest.finish()
}

fn digest_pricing_entry(
    receipt: &PromptPricingReceiptV1,
    model_profile_digest: Digest32,
    realization_context_digest: Digest32,
    causal_support_digest: Digest32,
    cost_support_digest: Digest32,
    decomposition: &PromptPricingDecompositionV1,
) -> Digest32 {
    let mut digest = SemanticDigest::new(b"hepta.prompt-pricing-audit-entry.v1");
    digest.digest(digest_pricing_receipt(receipt));
    digest.digest(model_profile_digest);
    digest.digest(realization_context_digest);
    digest.digest(causal_support_digest);
    digest.digest(cost_support_digest);
    for value in [
        decomposition.causal_incremental_utility_q32,
        decomposition.token_utility_cost_q32,
        decomposition.latency_utility_cost_q32,
        decomposition.context_crowding_cost_q32,
        decomposition.instruction_interference_cost_q32,
        decomposition.privacy_cost_q32,
        decomposition.instability_cost_q32,
        decomposition.future_context_option_value_cost_q32,
        decomposition.resource_cost_q32,
        decomposition.total_utility_cost_q32,
        decomposition.net_expected_utility_q32,
    ] {
        digest.fixed(value);
    }
    digest.finish()
}

fn digest_pricing_batch(
    candidate_set_digest: Digest32,
    complete_eligible_set_digest: Digest32,
    omitted_count: u32,
    model_profile_digest: Digest32,
    receipts: &[PromptPricingReceiptV1],
    audit_entries: &[PromptPricingAuditEntryV1],
    unavailable: &[PromptUnavailablePricingV1],
) -> Digest32 {
    let mut digest = SemanticDigest::new(b"hepta.prompt-pricing-batch.v1");
    digest.digest(candidate_set_digest);
    digest.digest(complete_eligible_set_digest);
    digest.u32(omitted_count);
    digest.digest(model_profile_digest);
    for receipt in receipts {
        digest.digest(digest_pricing_receipt(receipt));
    }
    for audit in audit_entries {
        digest.id(&audit.factor_id);
        digest.digest(audit.entry_digest);
    }
    for unavailable in unavailable {
        digest.id(&unavailable.factor_id);
        digest.u8(pricing_unavailable_code(unavailable.reason));
    }
    digest.finish()
}

fn digest_public_prices(
    candidate_set_digest: Digest32,
    prices: &[PromptPricingReceiptV1],
) -> Digest32 {
    let mut digest = SemanticDigest::new(b"hepta.prompt-public-prices.v1");
    digest.digest(candidate_set_digest);
    for price in prices {
        digest.digest(digest_pricing_receipt(price));
    }
    digest.finish()
}

fn digest_interaction_graph(graph: &PromptInteractionGraphV1) -> Digest32 {
    let mut digest = SemanticDigest::new(b"hepta.prompt-interaction-graph.v1");
    digest.digest(graph.candidate_set_digest);
    digest.ids(&graph.candidate_factor_ids);
    digest.u8(match graph.missing_interaction_policy {
        PromptMissingInteractionPolicyV1::AssumeZero => 0,
        PromptMissingInteractionPolicyV1::RejectMissing => 1,
    });
    for edge in &graph.edges {
        digest.id(&edge.left_factor_id);
        digest.id(&edge.right_factor_id);
        digest.u8(interaction_kind_code(edge.kind));
        digest.fixed(edge.marginal_utility_q32);
        digest.digest(edge.support_reference_digest);
    }
    digest.digest(digest_constraints(&graph.hard_constraints));
    digest.digest(graph.source_evidence_digest);
    digest.finish()
}

fn digest_constraints(constraints: &[PromptHardConstraintV1]) -> Digest32 {
    let mut digest = SemanticDigest::new(b"hepta.prompt-hard-constraints.v1");
    for constraint in constraints {
        let (kind, left, right, support) = constraint_parts(constraint);
        digest.u8(kind);
        digest.id(left);
        digest.id(right);
        digest.digest(support);
    }
    digest.finish()
}

#[allow(clippy::too_many_arguments)]
fn digest_portfolio_audit(
    receipt: &PromptPortfolioReceiptV1,
    complete_eligible_set_digest: Digest32,
    omitted_count: u32,
    priced_count: u32,
    unavailable_pricing_count: u32,
    constraint_digest: Digest32,
    pricing_batch_digest: Digest32,
    model_profile_digest: Digest32,
    decisions: &[PromptPortfolioCandidateAuditV1],
) -> Digest32 {
    let mut digest = SemanticDigest::new(b"hepta.prompt-portfolio-audit.v1");
    digest.digest(digest_portfolio_receipt(receipt));
    digest.digest(complete_eligible_set_digest);
    digest.u32(omitted_count);
    digest.u32(priced_count);
    digest.u32(unavailable_pricing_count);
    digest.digest(constraint_digest);
    digest.digest(pricing_batch_digest);
    digest.digest(model_profile_digest);
    for decision in decisions {
        digest.id(&decision.factor_id);
        digest.u8(portfolio_disposition_code(decision.disposition));
    }
    digest.u8(0); // GreedyPrerequisiteClosureV1.
    digest.u8(0); // HeuristicNoCertificate.
    digest.bool(true);
    digest.finish()
}

fn digest_registered_boundary(boundary: &RegisteredPromptBoundaryV1) -> Digest32 {
    let mut digest = SemanticDigest::new(b"hepta.prompt-registered-boundary.v1");
    digest.u8(boundary_code(boundary.decision_boundary));
    digest.digest(boundary.portfolio_digest);
    digest.digest(boundary.candidate_set_digest);
    digest.digest(boundary.registry_digest);
    digest.digest(boundary.model_profile_digest);
    digest.digest(boundary.registered_state_digest);
    digest.digest(boundary.policy_digest);
    digest.digest(boundary.boundary_support_digest);
    digest.finish()
}

fn digest_exercise_audit(
    receipt: &PromptExerciseDecisionV1,
    portfolio_digest: Digest32,
    boundary_digest: Digest32,
    state: &PromptExerciseStateV1,
) -> Digest32 {
    let mut digest = SemanticDigest::new(b"hepta.prompt-exercise-audit.v1");
    digest.digest(digest_exercise_decision(receipt));
    digest.digest(portfolio_digest);
    digest.digest(boundary_digest);
    digest.digest(state.state_digest);
    digest.digest(state.registry_digest);
    digest.digest(state.model_profile_digest);
    digest.u64(state.observed_at_unix_ms);
    digest.fixed(state.wait_value_q32);
    digest.bool(true);
    digest.bool(true);
    digest.bool(true);
    digest.bool(true);
    digest.finish()
}

fn enumeration_disposition_code(value: PromptEnumerationDispositionV1) -> u8 {
    match value {
        PromptEnumerationDispositionV1::Retained => 0,
        PromptEnumerationDispositionV1::OmittedByDeterministicCap => 1,
        PromptEnumerationDispositionV1::NotAdmitted => 2,
        PromptEnumerationDispositionV1::Illegal => 3,
        PromptEnumerationDispositionV1::ObjectiveScopeMismatch => 4,
        PromptEnumerationDispositionV1::ModelProfileMismatch => 5,
    }
}

fn pricing_unavailable_code(value: PromptPricingUnavailableReasonV1) -> u8 {
    match value {
        PromptPricingUnavailableReasonV1::MissingCausalEstimate => 0,
        PromptPricingUnavailableReasonV1::MissingCostModel => 1,
        PromptPricingUnavailableReasonV1::EvidenceBindingMismatch => 2,
        PromptPricingUnavailableReasonV1::InvalidConfidenceInterval => 3,
        PromptPricingUnavailableReasonV1::InvalidCost => 4,
        PromptPricingUnavailableReasonV1::RegisteredTokenBoundExceeded => 5,
    }
}

fn portfolio_disposition_code(value: PromptPortfolioDispositionV1) -> u8 {
    match value {
        PromptPortfolioDispositionV1::Selected => 0,
        PromptPortfolioDispositionV1::UnavailablePricing => 1,
        PromptPortfolioDispositionV1::NonPositivePackageUtility => 2,
        PromptPortfolioDispositionV1::OverTokenBudget => 3,
        PromptPortfolioDispositionV1::SelectionLimit => 4,
        PromptPortfolioDispositionV1::HardConflict => 5,
        PromptPortfolioDispositionV1::HeuristicExcluded => 6,
    }
}

fn interaction_kind_code(value: PromptInteractionKindV1) -> u8 {
    match value {
        PromptInteractionKindV1::ExplicitZero => 0,
        PromptInteractionKindV1::Complement => 1,
        PromptInteractionKindV1::Substitute => 2,
        PromptInteractionKindV1::Dominates => 3,
        PromptInteractionKindV1::Redundant => 4,
        PromptInteractionKindV1::Supersedes => 5,
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

struct SemanticDigest {
    bytes: Vec<u8>,
}

impl SemanticDigest {
    fn new(domain: &[u8]) -> Self {
        let mut value = Self { bytes: Vec::new() };
        value.bytes(domain);
        value
    }

    fn finish(self) -> Digest32 {
        Digest32::of_bytes(&self.bytes)
    }

    fn bytes(&mut self, value: &[u8]) {
        self.u64(u64::try_from(value.len()).unwrap_or(u64::MAX));
        self.bytes.extend_from_slice(value);
    }

    fn id(&mut self, value: &StableId) {
        self.bytes(value.as_str().as_bytes());
    }

    fn ids(&mut self, values: &[StableId]) {
        self.u64(u64::try_from(values.len()).unwrap_or(u64::MAX));
        for value in values {
            self.id(value);
        }
    }

    fn digest(&mut self, value: Digest32) {
        self.bytes.extend_from_slice(value.as_array());
    }

    fn fixed(&mut self, value: FixedQ32) {
        self.bytes.extend_from_slice(&value.raw().to_be_bytes());
    }

    fn u64(&mut self, value: u64) {
        self.bytes.extend_from_slice(&value.to_be_bytes());
    }

    fn u32(&mut self, value: u32) {
        self.bytes.extend_from_slice(&value.to_be_bytes());
    }

    fn u8(&mut self, value: u8) {
        self.bytes.push(value);
    }

    fn bool(&mut self, value: bool) {
        self.u8(u8::from(value));
    }
}
