fn validate_verifier_context(
    priced: &VerifiedPricedPromptCandidatesV2,
    verifier: &LearningEvidenceVerifierV1,
) -> Result<(), VerifiedPromptErrorV2> {
    if verifier.trust_digest() != priced.trust_digest
        || verifier.authority_epoch() != priced.authority_epoch
    {
        return Err(VerifiedPromptErrorV2::TrustRotated);
    }
    if verifier.objective_digest() != priced.value.candidates.receipt.objective_digest {
        return Err(VerifiedPromptErrorV2::ObjectiveMismatch);
    }
    if verifier.scope_digest() != priced.scope_digest {
        return Err(VerifiedPromptErrorV2::ScopeMismatch);
    }
    Ok(())
}

fn validate_enumerated(
    value: &EnumeratedPromptCandidatesV1,
) -> Result<(), VerifiedPromptErrorV2> {
    if value.candidates.len() > MAX_CANONICAL_PROMPT_FACTORS {
        return Err(VerifiedPromptErrorV2::BoundExceeded("candidate limit"));
    }
    if value.receipt.authority.grants_any() || value.registry_snapshot.authority.grants_any() {
        return Err(VerifiedPromptErrorV2::AuthorityEscalation);
    }
    for (label, digest) in [
        ("objective", value.receipt.objective_digest),
        ("state", value.receipt.state_digest),
        ("registry", value.receipt.registry_digest),
        ("generation vector", value.generation_vector_digest),
        ("candidate set", value.candidates_digest),
        ("candidate order", value.canonical_order_digest),
        ("candidate receipt", value.receipt.receipt_digest),
    ] {
        require_digest(label, digest)?;
    }
    if value.registry_snapshot.registry_digest != value.receipt.registry_digest
        || value.registry_snapshot.generation_vector_digest != value.generation_vector_digest
        || value.registry_snapshot.model_tuple_digest != value.model_tuple.digest()
    {
        return Err(VerifiedPromptErrorV2::IdentityMismatch(
            "registry snapshot/model/generation",
        ));
    }
    if value
        .candidates
        .windows(2)
        .any(|pair| pair[0].factor_id >= pair[1].factor_id)
    {
        return Err(VerifiedPromptErrorV2::NonCanonicalOrder(
            "candidate factor order",
        ));
    }
    let mut factors = BTreeSet::new();
    let mut realizations = BTreeSet::new();
    for candidate in &value.candidates {
        if candidate.factor_id != candidate.realization.factor_id
            || candidate.binding_digest != candidate.realization.digest()
        {
            return Err(VerifiedPromptErrorV2::IdentityMismatch(
                "candidate realization binding",
            ));
        }
        if !factors.insert(candidate.factor_id.clone()) {
            return Err(VerifiedPromptErrorV2::DuplicateIdentity(
                candidate.factor_id.to_string(),
            ));
        }
        if !realizations.insert(candidate.realization.realization_id.clone()) {
            return Err(VerifiedPromptErrorV2::DuplicateIdentity(
                candidate.realization.realization_id.to_string(),
            ));
        }
    }
    let factor_ids = value
        .candidates
        .iter()
        .map(|candidate| candidate.factor_id.clone())
        .collect::<Vec<_>>();
    if value.receipt.candidate_factor_ids != factor_ids {
        return Err(VerifiedPromptErrorV2::IdentityMismatch(
            "candidate receipt factor list",
        ));
    }
    let candidates_digest = digest_candidates(value);
    let order_digest = digest_candidate_order(value);
    if value.candidates_digest != candidates_digest {
        return Err(VerifiedPromptErrorV2::DigestMismatch("candidate set"));
    }
    if value.canonical_order_digest != order_digest {
        return Err(VerifiedPromptErrorV2::DigestMismatch(
            "candidate canonical order",
        ));
    }
    if value.receipt.receipt_digest
        != digest_candidate_receipt(value, candidates_digest, order_digest)
    {
        return Err(VerifiedPromptErrorV2::DigestMismatch(
            "candidate receipt",
        ));
    }
    Ok(())
}

fn validate_priced(value: &PricedPromptCandidatesV1) -> Result<(), VerifiedPromptErrorV2> {
    validate_enumerated(&value.candidates)?;
    if value.authority.grants_any() {
        return Err(VerifiedPromptErrorV2::AuthorityEscalation);
    }
    for (label, digest) in [
        ("candidate completeness", value.completeness_digest),
        ("pricing policy", value.pricing_policy_digest),
        ("pricing set", value.pricing_set_digest),
    ] {
        require_digest(label, digest)?;
    }
    if value.rows.len() != value.candidates.candidates.len() {
        return Err(VerifiedPromptErrorV2::Incomplete(
            "pricing rows do not cover candidates".to_owned(),
        ));
    }
    for (row, candidate) in value.rows.iter().zip(&value.candidates.candidates) {
        if &row.binding != candidate
            || row.binding.factor_id != row.pricing.factor_id
            || row.pricing.state_digest != value.candidates.receipt.state_digest
            || row.pricing.token_cost != row.binding.realization.token_cost
            || row.net_utility_q32 != row.pricing.expected_utility_q32
            || row.pricing.authority.grants_any()
            || row.pricing.confidence_interval.support_audit_digest.is_zero()
            || row.pricing.confidence_interval.lower_q32
                > row.pricing.confidence_interval.upper_q32
        {
            return Err(VerifiedPromptErrorV2::IdentityMismatch(
                "pricing row/binding",
            ));
        }
        let expected = digest_pricing_receipt(value, row);
        if row.pricing.receipt_digest != expected {
            return Err(VerifiedPromptErrorV2::DigestMismatch(
                "pricing receipt",
            ));
        }
    }
    if value.pricing_set_digest != digest_pricing_set(value) {
        return Err(VerifiedPromptErrorV2::DigestMismatch("pricing set"));
    }
    Ok(())
}

fn validate_selected(
    value: &SelectedPromptPortfolioV1,
    context: &PromptPortfolioVerificationContextV2,
) -> Result<(), VerifiedPromptErrorV2> {
    for (label, digest) in [
        ("candidate set", context.candidate_set_digest),
        ("pricing set", context.pricing_set_digest),
        ("registry snapshot", context.registry_snapshot_digest),
        ("generation vector", context.generation_vector_digest),
        ("model tuple", context.model_tuple_digest),
        ("graph generation", context.graph_generation_digest),
        ("objective", context.objective_digest),
        ("state", context.state_digest),
        ("scope", context.scope_digest),
        ("trust", context.trust_digest),
        ("evidence lineage", context.evidence_lineage_digest),
    ] {
        require_digest(label, digest)?;
    }
    if context.authority_epoch == 0 || context.valid_until_unix_ms == 0 {
        return Err(VerifiedPromptErrorV2::Corrupt(
            "invalid portfolio verification context".to_owned(),
        ));
    }
    if value.receipt.authority.grants_any() {
        return Err(VerifiedPromptErrorV2::AuthorityEscalation);
    }
    if value.selection_method != PromptSelectionMethodV1::GreedyPrerequisiteBundleV1
        || value.optimality != PromptOptimalityDisclosureV1::HeuristicNoCertificate
    {
        return Err(VerifiedPromptErrorV2::IdentityMismatch(
            "portfolio solver disclosure",
        ));
    }
    if value.receipt.factor_ids.len() > MAX_CANONICAL_SELECTED_FACTORS
        || value.receipt.total_token_upper_bound as u64 > MAX_CANONICAL_TOKEN_BUDGET
    {
        return Err(VerifiedPromptErrorV2::BoundExceeded("portfolio bounds"));
    }
    if value.receipt.candidate_set_digest != context.candidate_set_digest
        || value.pricing_set_digest != context.pricing_set_digest
        || value.graph_generation_digest != context.graph_generation_digest
        || value.generation_vector_digest != context.generation_vector_digest
        || value.model_tuple_digest != context.model_tuple_digest
        || value.model_tuple.digest() != context.model_tuple_digest
        || value.objective_digest != context.objective_digest
        || value.state_digest != context.state_digest
        || value.receipt.valid_until_unix_ms < context.valid_until_unix_ms
    {
        return Err(VerifiedPromptErrorV2::IdentityMismatch(
            "portfolio verification context",
        ));
    if value
        .selected
        .windows(2)
        .any(|pair| pair[0].factor_id >= pair[1].factor_id)
    {
        return Err(VerifiedPromptErrorV2::NonCanonicalOrder(
            "selected factor order",
        ));
    }
    let selected_ids = value
        .selected
        .iter()
        .map(|candidate| candidate.factor_id.clone())
        .collect::<Vec<_>>();
    if selected_ids != value.receipt.factor_ids {
        return Err(VerifiedPromptErrorV2::IdentityMismatch(
            "selected factors/receipt",
        ));
    }
    let mut token_total = 0_u64;
    let mut seen = BTreeSet::new();
    for selected in &value.selected {
        if selected.factor_id != selected.realization.factor_id
            || selected.binding_digest != selected.realization.digest()
            || !seen.insert(selected.factor_id.clone())
        {
            return Err(VerifiedPromptErrorV2::IdentityMismatch(
                "selected realization binding",
            ));
        }
        token_total = token_total
            .checked_adj;
    }
    if u32::try_from(token_total).map_err(|_| VerifiedPromptErrorV2::Arithmetic)?
        != value.receipt.total_token_upper_bound
    {
        return Err(VerifiedPromptErrorV2::IdentityMismatch(
            "portfolio token total",
        ));
    }
    if value.receipt.receipt_digest != digest_portfolio_receipt(value) {
        return Err(VerifiedPromptErrorV2::DigestMismatch(
            "portfolio receipt",
        ));
    }
    Ok(())
}

