//! Recomputable DTO integrity checks; never a constructor for verified phases.
use super::*;

pub(in crate::canonical) fn validate_candidates(
    raw: &RawEnumeratedPromptCandidatesV1,
) -> Result<(), CanonicalPromptError> {
    raw.registry_snapshot
        .validate()
        .map_err(|_| CanonicalPromptError::Integrity("registry snapshot"))?;
    raw.model_tuple
        .validate()
        .map_err(|_| CanonicalPromptError::Integrity("model tuple"))?;
    if raw.candidates.len() > MAX_CANONICAL_PROMPT_FACTORS
        || raw.receipt.authority.grants_any()
        || raw.registry_snapshot.authority.grants_any()
        || raw.generation_vector_digest != raw.registry_snapshot.generation_vector_digest
        || raw.model_tuple.digest() != raw.registry_snapshot.model_tuple_digest
        || raw.receipt.registry_digest != raw.registry_snapshot.registry_digest
        || raw.receipt.objective_digest.is_zero()
        || raw.receipt.state_digest.is_zero()
        || raw.receipt.selection_grammar_digest.is_zero()
    {
        return Err(CanonicalPromptError::Integrity("candidate context"));
    }
    let ids = raw
        .candidates
        .iter()
        .map(|c| c.factor_id.clone())
        .collect::<Vec<_>>();
    if ids != raw.receipt.candidate_factor_ids || ids.windows(2).any(|pair| pair[0] >= pair[1]) {
        return Err(CanonicalPromptError::Integrity(
            "candidate identities or order",
        ));
    }
    let mut candidates = b"hepta.prompt-optimizer.candidates.v1".to_vec();
    candidates.extend_from_slice(&(raw.candidates.len() as u64).to_be_bytes());
    let mut order = b"hepta.prompt-optimizer.candidate-order.v1".to_vec();
    let mut realizations = BTreeSet::new();
    for candidate in &raw.candidates {
        let binding = &candidate.realization;
        if candidate.factor_id != binding.factor_id
            || candidate.binding_digest != binding.digest()
            || !realizations.insert(binding.realization_id.clone())
            || binding.token_cost == 0
            || binding.model_id != raw.model_tuple.model_id
            || binding.model_version != raw.model_tuple.model_version
            || binding.model_digest != raw.model_tuple.model_digest
            || binding.tokenizer_digest != raw.model_tuple.tokenizer_digest
            || binding.template_digest != raw.model_tuple.template_digest
            || binding.tool_schema_digest != raw.model_tuple.tool_schema_digest
            || binding.context_profile_digest != raw.model_tuple.context_profile_digest
            || binding.locale_id != raw.model_tuple.locale_id
        {
            return Err(CanonicalPromptError::Integrity("realization binding"));
        }
        for out in [&mut candidates, &mut order] {
            push_bytes(out, candidate.factor_id.as_str().as_bytes());
            push_bytes(out, binding.realization_id.as_str().as_bytes());
        }
        push_digest(&mut candidates, candidate.binding_digest);
    }
    if Digest32::of_bytes(&candidates) != raw.candidates_digest
        || Digest32::of_bytes(&order) != raw.canonical_order_digest
    {
        return Err(CanonicalPromptError::Integrity("candidate content digest"));
    }
    let mut receipt = b"hepta.prompt-optimizer.candidate-set-receipt.v1".to_vec();
    push_bytes(&mut receipt, raw.receipt.set_id.as_str().as_bytes());
    for digest in [
        raw.receipt.objective_digest,
        raw.receipt.state_digest,
        raw.receipt.registry_digest,
        raw.registry_snapshot.snapshot_digest,
        raw.model_tuple.digest(),
        raw.receipt.selection_grammar_digest,
        raw.candidates_digest,
        raw.canonical_order_digest,
    ] {
        push_digest(&mut receipt, digest);
    }
    receipt.extend_from_slice(&(ids.len() as u64).to_be_bytes());
    for id in ids {
        push_bytes(&mut receipt, id.as_str().as_bytes());
    }
    receipt.extend_from_slice(&raw.omitted_count.to_be_bytes());
    if Digest32::of_bytes(&receipt) != raw.receipt.receipt_digest {
        return Err(CanonicalPromptError::Integrity("candidate receipt digest"));
    }
    Ok(())
}

pub(in crate::canonical) fn validate_selection(
    priced: &PricedPromptCandidatesV1,
    raw: &RawSelectedPromptPortfolioV1,
    interactions: &PromptInteractionAdmissionV1,
) -> Result<(), CanonicalPromptError> {
    validate_candidates(&priced.inner.candidates)?;
    if raw.selected.len() > MAX_CANONICAL_SELECTED_FACTORS
        || raw.receipt.authority.grants_any()
        || raw.receipt.candidate_set_digest != priced.candidates.candidates_digest
        || raw.pricing_set_digest != priced.pricing_set_digest
        || raw.objective_digest != priced.candidates.receipt.objective_digest
        || raw.state_digest != priced.candidates.receipt.state_digest
        || raw.model_tuple != priced.candidates.model_tuple
        || raw.model_tuple_digest != raw.model_tuple.digest()
        || raw.generation_vector_digest != priced.candidates.generation_vector_digest
        || raw.graph_generation_digest.is_zero()
        || raw.receipt.interaction_digest.is_zero()
        || raw.selection_method != PromptSelectionMethodV1::GreedyPrerequisiteBundleV1
        || raw.optimality != PromptOptimalityDisclosureV1::HeuristicNoCertificate
    {
        return Err(CanonicalPromptError::Integrity("portfolio context"));
    }
    let ids = raw
        .selected
        .iter()
        .map(|binding| binding.factor_id.clone())
        .collect::<Vec<_>>();
    if ids != raw.receipt.factor_ids || ids.windows(2).any(|pair| pair[0] >= pair[1]) {
        return Err(CanonicalPromptError::Integrity(
            "portfolio identities or order",
        ));
    }
    let mut tokens = 0_u64;
    let mut utility = FixedQ32::ZERO;
    for selected in &raw.selected {
        let row = priced
            .rows
            .iter()
            .find(|row| row.binding.factor_id == selected.factor_id)
            .ok_or(CanonicalPromptError::Integrity("unknown selected factor"))?;
        if row.binding != *selected
            || row.pricing.factor_id != selected.factor_id
            || row.pricing.token_cost != selected.realization.token_cost
            || row.pricing.expected_utility_q32 != row.net_utility_q32
            || row.pricing.state_digest != raw.state_digest
            || row.pricing.authority.grants_any()
        {
            return Err(CanonicalPromptError::Integrity("selected pricing binding"));
        }
        tokens = tokens
            .checked_add(u64::from(row.pricing.token_cost))
            .ok_or(CanonicalPromptError::Integrity("token overflow"))?;
        utility = utility
            .checked_add(row.net_utility_q32)
            .map_err(|_| CanonicalPromptError::Integrity("utility overflow"))?;
    }
    for left_index in 0..ids.len() {
        for right_index in left_index + 1..ids.len() {
            let left = &ids[left_index];
            let right = &ids[right_index];
            match interactions
                .pairs
                .iter()
                .find(|pair| &pair.left_factor_id == left && &pair.right_factor_id == right)
            {
                Some(pair) => {
                    utility = utility
                        .checked_add(pair.marginal_utility_q32)
                        .map_err(|_| CanonicalPromptError::Integrity("pair utility overflow"))?;
                }
                None if interactions.missing_pairs
                    == PromptMissingPairPolicyV1::RequireExplicit =>
                {
                    return Err(CanonicalPromptError::MissingPairSupport(
                        left.to_string(),
                        right.to_string(),
                    ));
                }
                None => {}
            }
        }
    }
    if tokens != u64::from(raw.receipt.total_token_upper_bound)
        || tokens > MAX_CANONICAL_TOKEN_BUDGET
        || utility != raw.receipt.expected_utility_q32
        || utility < FixedQ32::ZERO
    {
        return Err(CanonicalPromptError::Integrity("portfolio accounting"));
    }
    let mut receipt = b"hepta.prompt-optimizer.portfolio-receipt.v1".to_vec();
    push_bytes(&mut receipt, raw.receipt.portfolio_id.as_str().as_bytes());
    for digest in [
        raw.receipt.candidate_set_digest,
        raw.receipt.interaction_digest,
        raw.pricing_set_digest,
        raw.graph_generation_digest,
    ] {
        push_digest(&mut receipt, digest);
    }
    receipt.extend_from_slice(&(ids.len() as u64).to_be_bytes());
    for id in ids {
        push_bytes(&mut receipt, id.as_str().as_bytes());
    }
    receipt.extend_from_slice(&raw.receipt.expected_utility_q32.raw().to_be_bytes());
    receipt.extend_from_slice(&raw.receipt.total_token_upper_bound.to_be_bytes());
    receipt.extend_from_slice(&raw.receipt.valid_until_unix_ms.to_be_bytes());
    receipt.extend_from_slice(&[0, 0]);
    if Digest32::of_bytes(&receipt) != raw.receipt.receipt_digest {
        return Err(CanonicalPromptError::Integrity("portfolio receipt digest"));
    }
    Ok(())
}
