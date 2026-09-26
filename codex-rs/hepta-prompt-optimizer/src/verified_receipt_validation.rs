fn validate_enumerated(
    value: &v1::EnumeratedPromptCandidatesV1,
) -> Result<(), VerifiedPromptError> {
    value
        .registry_snapshot
        .validate()
        .map_err(map_registry_error)?;
    if value.candidates.len() > MAX_CANONICAL_PROMPT_FACTORS
        || value.receipt.candidate_factor_ids.len() != value.candidates.len()
    {
        return Err(VerifiedPromptError::CandidateLimit);
    }
    if value.receipt.authority.grants_any() || value.registry_snapshot.authority.grants_any() {
        return Err(VerifiedPromptError::Authority);
    }
    for (name, digest) in [
        ("generation_vector", value.generation_vector_digest),
        ("candidates", value.candidates_digest),
        ("candidate_order", value.canonical_order_digest),
        ("candidate_receipt", value.receipt.receipt_digest),
        ("registry", value.receipt.registry_digest),
        ("objective", value.receipt.objective_digest),
        ("state", value.receipt.state_digest),
        ("selection_grammar", value.receipt.selection_grammar_digest),
    ] {
        ensure_digest(name, digest)?;
    }
    if value.registry_snapshot.registry_digest != value.receipt.registry_digest
        || value.registry_snapshot.generation_vector_digest != value.generation_vector_digest
        || value.registry_snapshot.model_tuple_digest != value.model_tuple.digest()
    {
        return Err(VerifiedPromptError::CandidateBinding(
            "registry/model snapshot".to_owned(),
        ));
    }
    let mut previous: Option<&StableId> = None;
    let mut factor_ids = Vec::with_capacity(value.candidates.len());
    for candidate in &value.candidates {
        if candidate.factor_id != candidate.realization.factor_id
            || candidate.binding_digest != candidate.realization.digest()
            || previous.is_some_and(|id| id >= &candidate.factor_id)
        {
            return Err(VerifiedPromptError::CandidateBinding(
                candidate.factor_id.to_string(),
            ));
        }
        previous = Some(&candidate.factor_id);
        factor_ids.push(candidate.factor_id.clone());
    }
    if factor_ids != value.receipt.candidate_factor_ids {
        return Err(VerifiedPromptError::CandidateOrder);
    }
    if digest_candidates(&value.candidates) != value.candidates_digest
        || digest_candidate_order(&value.candidates) != value.canonical_order_digest
    {
        return Err(VerifiedPromptError::ReceiptDigest("candidate set"));
    }
    let expected_receipt = digest_candidate_receipt(value);
    if expected_receipt != value.receipt.receipt_digest {
        return Err(VerifiedPromptError::ReceiptDigest("candidate receipt"));
    }
    Ok(())
}

fn validate_priced(value: &v1::PricedPromptCandidatesV1) -> Result<(), VerifiedPromptError> {
    validate_enumerated(&value.candidates)?;
    if value.authority.grants_any() || value.rows.len() != value.candidates.candidates.len() {
        return Err(VerifiedPromptError::Authority);
    }
    for (candidate, row) in value.candidates.candidates.iter().zip(&value.rows) {
        if candidate != &row.binding
            || row.pricing.factor_id != row.binding.factor_id
            || row.pricing.state_digest != value.candidates.receipt.state_digest
            || row.pricing.expected_utility_q32 != row.net_utility_q32
            || row.pricing.authority.grants_any()
        {
            return Err(VerifiedPromptError::CandidateBinding(
                row.binding.factor_id.to_string(),
            ));
        }
        let expected = digest_pricing_receipt(
            &row.binding.factor_id,
            row.pricing.state_digest,
            row.pricing.expected_utility_q32,
            row.pricing.downside_q32,
            row.pricing.token_cost,
            row.pricing.latency_cost_micros,
            row.pricing.interference_ppm,
            &row.pricing.confidence_interval,
            value.pricing_policy_digest,
            row.binding.binding_digest,
        );
        if expected != row.pricing.receipt_digest {
            return Err(VerifiedPromptError::ReceiptDigest("pricing receipt"));
        }
    }
    if digest_pricing_set(&value.rows, value.pricing_policy_digest) != value.pricing_set_digest {
        return Err(VerifiedPromptError::ReceiptDigest("pricing set"));
    }
    Ok(())
}

fn validate_selected(
    selected: &v1::SelectedPromptPortfolioV1,
    priced: &VerifiedPricedPromptCandidatesV2,
) -> Result<(), VerifiedPromptError> {
    validate_selected_shape(selected)?;
    if selected.objective_digest != priced.candidates.receipt.objective_digest
        || selected.state_digest != priced.candidates.receipt.state_digest
        || selected.model_tuple != priced.candidates.model_tuple
        || selected.model_tuple_digest != priced.candidates.model_tuple.digest()
        || selected.generation_vector_digest != priced.candidates.generation_vector_digest
        || selected.pricing_set_digest != priced.pricing_set_digest
        || selected.receipt.candidate_set_digest != priced.candidates.candidates_digest
    {
        return Err(VerifiedPromptError::PortfolioIntegrity("source binding"));
    }
    Ok(())
}

fn validate_selected_shape(
    selected: &v1::SelectedPromptPortfolioV1,
) -> Result<(), VerifiedPromptError> {
    if selected.receipt.authority.grants_any()
        || selected.selected.len() != selected.receipt.factor_ids.len()
        || selected.selected.len() > MAX_CANONICAL_SELECTED_FACTORS
    {
        return Err(VerifiedPromptError::Authority);
    }
    let factor_ids = selected
        .selected
        .iter()
        .map(|binding| binding.factor_id.clone())
        .collect::<Vec<_>>();
    if factor_ids.windows(2).any(|pair| pair[0] >= pair[1])
        || factor_ids != selected.receipt.factor_ids
    {
        return Err(VerifiedPromptError::PortfolioIntegrity("factor order"));
    }
    let total_tokens = selected.selected.iter().try_fold(0_u64, |total, binding| {
        if binding.factor_id != binding.realization.factor_id
            || binding.binding_digest != binding.realization.digest()
        {
            return Err(VerifiedPromptError::PortfolioIntegrity(
                "realization binding",
            ));
        }
        total
            .checked_add(u64::from(binding.realization.token_cost))
            .ok_or(VerifiedPromptError::Arithmetic)
    })?;
    if u32::try_from(total_tokens).ok() != Some(selected.receipt.total_token_upper_bound) {
        return Err(VerifiedPromptError::PortfolioIntegrity("token total"));
    }
    for (name, digest) in [
        ("candidate_set", selected.receipt.candidate_set_digest),
        ("interaction", selected.receipt.interaction_digest),
        ("pricing_set", selected.pricing_set_digest),
        ("graph_generation", selected.graph_generation_digest),
        ("portfolio_receipt", selected.receipt.receipt_digest),
    ] {
        ensure_digest(name, digest)?;
    }
    let expected_receipt = digest_portfolio_receipt_v2(
        &selected.receipt.portfolio_id,
        selected.receipt.candidate_set_digest,
        &selected.receipt.factor_ids,
        selected.receipt.interaction_digest,
        selected.receipt.expected_utility_q32,
        selected.receipt.total_token_upper_bound,
        selected.receipt.valid_until_unix_ms,
        selected.pricing_set_digest,
        selected.graph_generation_digest,
    );
    if expected_receipt != selected.receipt.receipt_digest {
        return Err(VerifiedPromptError::ReceiptDigest("portfolio receipt"));
    }
    Ok(())
}
