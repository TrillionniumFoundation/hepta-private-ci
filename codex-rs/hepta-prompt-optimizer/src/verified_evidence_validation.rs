fn validate_evidence_context(
    context: &PromptEvidenceContextV2,
    candidates: &VerifiedEnumeratedPromptCandidatesV2,
    verifier: &LearningEvidenceVerifierV1,
    policy_digest: Digest32,
) -> Result<(), VerifiedPromptError> {
    context.validate()?;
    if context.objective_digest != candidates.receipt.objective_digest
        || context.candidate_set_digest != candidates.candidates_digest
        || context.registry_snapshot_digest != candidates.registry_snapshot.snapshot_digest
        || context.generation_vector_digest != candidates.generation_vector_digest
        || context.model_tuple_digest != candidates.model_tuple.digest()
        || context.selection_grammar_digest != candidates.receipt.selection_grammar_digest
        || context.pricing_policy_digest != policy_digest
    {
        return Err(VerifiedPromptError::CandidateBinding(
            "evidence context".to_owned(),
        ));
    }
    validate_verifier_context(verifier, context)
}

fn validate_verifier_context(
    verifier: &LearningEvidenceVerifierV1,
    context: &PromptEvidenceContextV2,
) -> Result<(), VerifiedPromptError> {
    if verifier.objective_digest() != context.objective_digest {
        return Err(VerifiedPromptError::ObjectiveMismatch);
    }
    if verifier.scope_digest() != context.scope_digest {
        return Err(VerifiedPromptError::ScopeMismatch);
    }
    if verifier.authority_epoch() == 0 {
        return Err(VerifiedPromptError::TrustEpochMismatch);
    }
    Ok(())
}

fn validate_completeness_binding(
    candidates: &VerifiedEnumeratedPromptCandidatesV2,
    context: &PromptEvidenceContextV2,
    completeness: &CandidateSetCompletenessReceiptV1,
) -> Result<Digest32, VerifiedPromptError> {
    context.validate()?;
    let validated = validate_candidate_set_completeness(completeness)
        .map_err(|error| VerifiedPromptError::Evidence(format!("{error:?}")))?;
    let count = u32::try_from(candidates.candidates.len())
        .map_err(|_| VerifiedPromptError::CandidateLimit)?;
    if completeness.set_id != candidates.receipt.set_id
        || completeness.state_digest != candidates.receipt.state_digest
        || completeness.generator_id.as_str() != "prompt.optimizer"
        || completeness.grammar_digest != candidates.receipt.selection_grammar_digest
        || completeness.generator_code_digest != context.generator_code_digest
        || completeness.hard_filter_digest != context.hard_filter_digest
        || completeness.truncation_digest != context.truncation_digest
        || completeness.candidates_digest != candidates.candidates_digest
        || completeness.canonical_order_digest != candidates.canonical_order_digest
        || completeness.candidate_count != count
        || completeness.omitted_count_bound < candidates.omitted_count
    {
        return Err(VerifiedPromptError::CandidateBinding(
            "completeness receipt".to_owned(),
        ));
    }
    Ok(validated)
}

fn validate_pricing_evidence_v2(
    candidates: &VerifiedEnumeratedPromptCandidatesV2,
    candidate: &v1::PromptCandidateBindingV1,
    context: &PromptEvidenceContextV2,
    evidence: &PromptPricingEvidenceV2,
    policy: &PromptPricingPolicyV1,
) -> Result<(), VerifiedPromptError> {
    if evidence.context != *context
        || evidence.factor_id != candidate.factor_id
        || evidence.realization_id != candidate.realization.realization_id
        || evidence.realization_binding_digest != candidate.binding_digest
        || evidence.state_digest != candidates.receipt.state_digest
        || evidence.support_audit_digest.is_zero()
        || evidence.support_count < policy.minimum_support_count
        || evidence.interference_ppm > policy.maximum_interference_ppm
        || evidence.downside_q32 < FixedQ32::ZERO
        || evidence.context_crowding_cost_q32 < FixedQ32::ZERO
        || evidence.privacy_cost_q32 < FixedQ32::ZERO
        || evidence.instability_cost_q32 < FixedQ32::ZERO
        || evidence.future_context_option_cost_q32 < FixedQ32::ZERO
        || evidence.confidence_lower_q32 > evidence.expected_incremental_utility_q32
        || evidence.expected_incremental_utility_q32 > evidence.confidence_upper_q32
    {
        return Err(VerifiedPromptError::InvalidPricing(
            evidence.factor_id.to_string(),
        ));
    }
    Ok(())
}

fn validate_selection_request(
    request: &PromptPortfolioRequestV1,
    now_unix_ms: u64,
) -> Result<(), VerifiedPromptError> {
    if request.maximum_selected_factors == 0
        || request.maximum_selected_factors > MAX_CANONICAL_SELECTED_FACTORS
    {
        return Err(VerifiedPromptError::SelectionLimit);
    }
    if request.token_budget > MAX_CANONICAL_TOKEN_BUDGET {
        return Err(VerifiedPromptError::TokenBudgetLimit);
    }
    if now_unix_ms == 0 || request.requested_valid_until_unix_ms <= now_unix_ms {
        return Err(VerifiedPromptError::PortfolioExpired);
    }
    Ok(())
}

fn edge_valid_until_ms(
    edge: &codex_hepta_kg::KnowledgeEdgeV2,
    now_unix_ms: u64,
) -> Result<u64, VerifiedPromptError> {
    let mut valid_until = u64::MAX;
    for support in &edge.supports {
        if support.tombstoned {
            return Err(VerifiedPromptError::Graph(
                "tombstoned relation support".to_owned(),
            ));
        }
        if let Some(valid_to) = support.valid_to_unix_seconds {
            if valid_to <= 0 {
                return Err(VerifiedPromptError::Graph(
                    "invalid relation validity".to_owned(),
                ));
            }
            let millis = u64::try_from(valid_to)
                .map_err(|_| VerifiedPromptError::Graph("relation validity overflow".to_owned()))?
                .checked_mul(1000)
                .ok_or(VerifiedPromptError::Arithmetic)?;
            valid_until = valid_until.min(millis);
        }
    }
    if valid_until <= now_unix_ms {
        return Err(VerifiedPromptError::EvidenceExpired);
    }
    Ok(valid_until)
}
