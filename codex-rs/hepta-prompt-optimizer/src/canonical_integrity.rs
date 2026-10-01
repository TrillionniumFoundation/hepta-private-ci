//! Process-local provenance and semantic binding for canonical decisions.
//!
//! These seals authenticate the immutable outputs of evidence verification and
//! selection in this process. They grant no execution or admission authority.
//! Reconstructing public receipt fields, even with recomputed content hashes,
//! cannot create a verified pricing result or selected portfolio.

use super::*;

pub(super) fn validate_candidates(
    candidates: &EnumeratedPromptCandidatesV1,
) -> Result<(), CanonicalPromptError> {
    let receipt = &candidates.receipt;
    candidates
        .registry_snapshot
        .validate()
        .map_err(|_| CanonicalPromptError::CandidateIntegrity)?;
    candidates
        .model_tuple
        .validate()
        .map_err(|_| CanonicalPromptError::CandidateIntegrity)?;
    if candidates.candidates.len() > MAX_CANONICAL_PROMPT_FACTORS
        || receipt.authority.grants_any()
        || receipt.objective_digest.is_zero()
        || receipt.state_digest.is_zero()
        || receipt.selection_grammar_digest.is_zero()
        || candidates.generation_vector_digest.is_zero()
        || candidates.registry_snapshot.generation_vector_digest
            != candidates.generation_vector_digest
        || candidates.registry_snapshot.model_tuple_digest != candidates.model_tuple.digest()
        || receipt.registry_digest != candidates.registry_snapshot.registry_digest
        || receipt.candidate_factor_ids
            != candidates
                .candidates
                .iter()
                .map(|candidate| candidate.factor_id.clone())
                .collect::<Vec<_>>()
        || candidates.candidates_digest != digest_candidates(&candidates.candidates)
        || candidates.canonical_order_digest != digest_candidate_order(&candidates.candidates)
        || candidates.verified_enumeration_digest.is_zero()
        || candidates.verified_enumeration_digest != enumeration_digest(candidates)
        || receipt.receipt_digest
            != digest_candidate_receipt(
                &receipt.set_id,
                receipt.objective_digest,
                receipt.state_digest,
                receipt.registry_digest,
                candidates.registry_snapshot.snapshot_digest,
                candidates.model_tuple.digest(),
                receipt.selection_grammar_digest,
                &receipt.candidate_factor_ids,
                candidates.candidates_digest,
                candidates.canonical_order_digest,
                candidates.omitted_count,
            )
    {
        return Err(CanonicalPromptError::CandidateIntegrity);
    }
    validate_bindings(&candidates.candidates, &candidates.model_tuple)
        .map_err(|_| CanonicalPromptError::CandidateIntegrity)
}

pub(super) fn enumeration_digest(candidates: &EnumeratedPromptCandidatesV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.verified-enumeration.v1".to_vec();
    for digest in [
        candidates.receipt.receipt_digest,
        candidates.registry_snapshot.snapshot_digest,
        candidates.generation_vector_digest,
        candidates.model_tuple.digest(),
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn validate_bindings(
    bindings: &[PromptCandidateBindingV1],
    tuple: &PromptModelTupleV2,
) -> Result<(), CanonicalPromptError> {
    let mut realizations = BTreeSet::new();
    if bindings
        .windows(2)
        .any(|pair| pair[0].factor_id >= pair[1].factor_id)
    {
        return Err(CanonicalPromptError::CandidateIntegrity);
    }
    for binding in bindings {
        let realization = &binding.realization;
        realization
            .validate()
            .map_err(|_| CanonicalPromptError::CandidateIntegrity)?;
        if binding.factor_id != realization.factor_id
            || binding.binding_digest != realization.digest()
            || !realizations.insert(&realization.realization_id)
            || realization.model_id != tuple.model_id
            || realization.model_version != tuple.model_version
            || realization.model_digest != tuple.model_digest
            || realization.tokenizer_digest != tuple.tokenizer_digest
            || realization.template_digest != tuple.template_digest
            || realization.tool_schema_digest != tuple.tool_schema_digest
            || realization.context_profile_digest != tuple.context_profile_digest
            || realization.locale_id != tuple.locale_id
        {
            return Err(CanonicalPromptError::CandidateIntegrity);
        }
    }
    Ok(())
}

impl PricedPromptCandidatesV1 {
    /// Verify that public fields still match the result of signed pricing.
    pub fn validate(&self) -> Result<(), CanonicalPromptError> {
        validate_candidates(&self.candidates)?;
        if self.authority.grants_any()
            || self.completeness_digest.is_zero()
            || self.pricing_policy_digest.is_zero()
            || self.verified_trust_digest.is_zero()
            || self.verified_at_unix_ms == 0
            || self.verified_valid_until_unix_ms <= self.verified_at_unix_ms
            || self.rows.len() != self.candidates.candidates.len()
            || self.pricing_set_digest != digest_pricing_set(&self.rows, self.pricing_policy_digest)
            || self.verified_pricing_digest.is_zero()
            || self.verified_pricing_digest != priced_digest(self)
        {
            return Err(CanonicalPromptError::PricingIntegrity);
        }
        for (row, candidate) in self.rows.iter().zip(&self.candidates.candidates) {
            let pricing = &row.pricing;
            if &row.binding != candidate
                || pricing.authority.grants_any()
                || pricing.factor_id != candidate.factor_id
                || pricing.state_digest != self.candidates.receipt.state_digest
                || pricing.token_cost != candidate.realization.token_cost
                || pricing.expected_utility_q32 != row.net_utility_q32
                || pricing.downside_q32 < FixedQ32::ZERO
                || pricing.confidence_interval.lower_q32 > pricing.confidence_interval.upper_q32
                || pricing.confidence_interval.support_count == 0
                || pricing.confidence_interval.support_audit_digest.is_zero()
                || pricing.receipt_digest
                    != digest_pricing_receipt(
                        &pricing.factor_id,
                        pricing.state_digest,
                        pricing.expected_utility_q32,
                        pricing.downside_q32,
                        pricing.token_cost,
                        pricing.latency_cost_micros,
                        pricing.interference_ppm,
                        &pricing.confidence_interval,
                        self.pricing_policy_digest,
                        candidate.binding_digest,
                    )
            {
                return Err(CanonicalPromptError::PricingIntegrity);
            }
        }
        Ok(())
    }
}

pub(super) fn priced_digest(priced: &PricedPromptCandidatesV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.verified-pricing.v1".to_vec();
    for digest in [
        priced.candidates.receipt.receipt_digest,
        priced.candidates.generation_vector_digest,
        priced.completeness_digest,
        priced.pricing_policy_digest,
        priced.pricing_set_digest,
        priced.verified_trust_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_len(&mut bytes, priced.rows.len());
    bytes.extend_from_slice(&priced.verified_at_unix_ms.to_be_bytes());
    bytes.extend_from_slice(&priced.verified_valid_until_unix_ms.to_be_bytes());
    for row in &priced.rows {
        bytes.extend_from_slice(row.binding.binding_digest.as_array());
        bytes.extend_from_slice(row.pricing.receipt_digest.as_array());
        bytes.extend_from_slice(&row.net_utility_q32.raw().to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

impl SelectedPromptPortfolioV1 {
    /// Verify selection provenance, exact bindings, budget and receipt fields.
    pub fn validate(&self) -> Result<(), CanonicalPromptError> {
        let receipt = &self.receipt;
        if self.selected.len() > MAX_CANONICAL_SELECTED_FACTORS {
            return Err(CanonicalPromptError::PortfolioIntegrity);
        }
        self.model_tuple
            .validate()
            .map_err(|_| CanonicalPromptError::PortfolioIntegrity)?;
        validate_bindings(&self.selected, &self.model_tuple)
            .map_err(|_| CanonicalPromptError::PortfolioIntegrity)?;
        let tokens = self.selected.iter().try_fold(0_u64, |total, selected| {
            total
                .checked_add(u64::from(selected.realization.token_cost))
                .ok_or(CanonicalPromptError::PortfolioIntegrity)
        })?;
        if receipt.authority.grants_any()
            || receipt.candidate_set_digest.is_zero()
            || receipt.interaction_digest.is_zero()
            || receipt.valid_until_unix_ms == 0
            || self.selected_at_unix_ms == 0
            || receipt.valid_until_unix_ms <= self.selected_at_unix_ms
            || tokens > MAX_CANONICAL_TOKEN_BUDGET
            || tokens != u64::from(receipt.total_token_upper_bound)
            || self.objective_digest.is_zero()
            || self.state_digest.is_zero()
            || self.generation_vector_digest.is_zero()
            || self.pricing_set_digest.is_zero()
            || self.graph_generation_digest.is_zero()
            || self.model_tuple_digest != self.model_tuple.digest()
            || receipt.factor_ids
                != self
                    .selected
                    .iter()
                    .map(|candidate| candidate.factor_id.clone())
                    .collect::<Vec<_>>()
            || self.selected.iter().any(|selected| {
                selected
                    .realization
                    .expires_unix_ms
                    .is_some_and(|expiry| receipt.valid_until_unix_ms > expiry)
            })
            || receipt.receipt_digest
                != digest_portfolio_receipt(
                    &receipt.portfolio_id,
                    receipt.candidate_set_digest,
                    &receipt.factor_ids,
                    receipt.interaction_digest,
                    receipt.expected_utility_q32,
                    receipt.total_token_upper_bound,
                    receipt.valid_until_unix_ms,
                    self.pricing_set_digest,
                    self.graph_generation_digest,
                )
            || self.verified_portfolio_digest.is_zero()
            || self.verified_portfolio_digest != portfolio_digest(self)
        {
            return Err(CanonicalPromptError::PortfolioIntegrity);
        }
        Ok(())
    }
}

pub(super) fn portfolio_digest(portfolio: &SelectedPromptPortfolioV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.verified-portfolio.v1".to_vec();
    for digest in [
        portfolio.receipt.receipt_digest,
        portfolio.objective_digest,
        portfolio.state_digest,
        portfolio.model_tuple_digest,
        portfolio.generation_vector_digest,
        portfolio.pricing_set_digest,
        portfolio.graph_generation_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_len(&mut bytes, portfolio.selected.len());
    bytes.extend_from_slice(&portfolio.selected_at_unix_ms.to_be_bytes());
    for selected in &portfolio.selected {
        bytes.extend_from_slice(selected.binding_digest.as_array());
    }
    match portfolio.selection_method {
        PromptSelectionMethodV1::GreedyPrerequisiteBundleV1 => bytes.push(0),
    }
    match portfolio.optimality {
        PromptOptimalityDisclosureV1::HeuristicNoCertificate => bytes.push(0),
    }
    Digest32::of_bytes(&bytes)
}
