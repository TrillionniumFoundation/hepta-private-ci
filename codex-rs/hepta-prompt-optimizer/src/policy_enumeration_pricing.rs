// ---------------------------------------------------------------------------
// Target operation 1: enumerate_factors.
// ---------------------------------------------------------------------------

/// Enumerate the registered candidate-set receipt required by the public V1 API.
///
/// Use [`enumerate_factors_audited`] when the caller also needs omitted-count,
/// completeness, realization binding and per-factor exclusion diagnostics.
pub fn enumerate_factors(
    registry_snapshot: &PromptRegistrySnapshotV1,
    objective: &PromptObjectiveContextV1,
    model_profile: &PromptModelProfileV1,
) -> Result<PromptCandidateSetReceiptV1, PolicyError> {
    Ok(enumerate_factors_audited(registry_snapshot, objective, model_profile)?.receipt)
}

pub fn enumerate_factors_audited(
    registry_snapshot: &PromptRegistrySnapshotV1,
    objective: &PromptObjectiveContextV1,
    model_profile: &PromptModelProfileV1,
) -> Result<PromptCandidateSetBundleV1, PolicyError> {
    validate_enumeration_inputs(registry_snapshot, objective, model_profile)?;

    let mut factors = registry_snapshot.factors.clone();
    factors.sort_by_key(|factor| factor.factor_id.clone());

    let mut factor_ids = BTreeSet::new();
    let mut realization_ids = BTreeSet::new();
    let mut eligible = Vec::new();
    let mut decisions = Vec::with_capacity(factors.len());

    for factor in factors {
        if !factor_ids.insert(factor.factor_id.clone()) {
            return Err(PolicyError::DuplicateFactor(factor.factor_id.to_string()));
        }
        if !realization_ids.insert(factor.realization_id.clone()) {
            return Err(PolicyError::DuplicateRealization(
                factor.realization_id.to_string(),
            ));
        }
        validate_factor_snapshot(&factor)?;

        let disposition = if !factor.admitted {
            PromptEnumerationDispositionV1::NotAdmitted
        } else if !factor.legal {
            PromptEnumerationDispositionV1::Illegal
        } else if factor
            .objective_scope_digest
            .is_some_and(|digest| digest != objective.objective_digest)
        {
            PromptEnumerationDispositionV1::ObjectiveScopeMismatch
        } else if factor
            .model_profile_digest
            .is_some_and(|digest| digest != model_profile.profile_digest)
        {
            PromptEnumerationDispositionV1::ModelProfileMismatch
        } else {
            eligible.push(factor.clone());
            PromptEnumerationDispositionV1::Retained
        };
        decisions.push(PromptEnumerationCandidateAuditV1 {
            factor_id: factor.factor_id,
            disposition,
        });
    }

    let complete_eligible_set_digest = digest_complete_eligible_set(&eligible);
    let eligible_before_truncation = u32::try_from(eligible.len()).map_err(|_| PolicyError::Arithmetic)?;
    let retained_len = eligible.len().min(MAX_POLICY_FACTORS);
    let omitted = eligible.len().saturating_sub(retained_len);
    let retained = &eligible[..retained_len];

    if omitted > 0 {
        let omitted_ids: BTreeSet<StableId> = eligible[retained_len..]
            .iter()
            .map(|factor| factor.factor_id.clone())
            .collect();
        for decision in &mut decisions {
            if omitted_ids.contains(&decision.factor_id) {
                decision.disposition = PromptEnumerationDispositionV1::OmittedByDeterministicCap;
            }
        }
    }

    let candidate_factor_ids = retained
        .iter()
        .map(|factor| factor.factor_id.clone())
        .collect::<Vec<_>>();
    let bindings = retained
        .iter()
        .map(|factor| PromptCandidateBindingV1 {
            factor_id: factor.factor_id.clone(),
            realization_id: factor.realization_id.clone(),
            model_profile_digest: model_profile.profile_digest,
            realization_context_digest: factor.realization_context_digest,
            token_upper_bound: factor.token_upper_bound,
            support_reference_digest: factor.support_reference_digest,
        })
        .collect::<Vec<_>>();

    let set_seed = digest_enumeration_seed(
        registry_snapshot.registry_digest,
        objective,
        model_profile,
        complete_eligible_set_digest,
    );
    let set_id = derived_id("prompt-candidates", set_seed)?;
    let receipt = PromptCandidateSetReceiptV1 {
        set_id,
        objective_digest: objective.objective_digest,
        state_digest: objective.state_digest,
        registry_digest: registry_snapshot.registry_digest,
        candidate_factor_ids,
        selection_grammar_digest: objective.selection_grammar_digest,
    };
    let candidate_set_digest = digest_candidate_set_receipt(&receipt);
    let model_tuple_digest = digest_model_profile(model_profile);
    let retained_count = u32::try_from(retained_len).map_err(|_| PolicyError::Arithmetic)?;
    let omitted_count = u32::try_from(omitted).map_err(|_| PolicyError::Arithmetic)?;
    let audit_digest = digest_candidate_set_audit(
        candidate_set_digest,
        registry_snapshot.source_evidence_digest,
        model_profile.profile_digest,
        model_tuple_digest,
        complete_eligible_set_digest,
        eligible_before_truncation,
        retained_count,
        omitted_count,
        &bindings,
        &decisions,
    );

    Ok(PromptCandidateSetBundleV1 {
        receipt,
        audit: PromptCandidateSetAuditV1 {
            candidate_set_digest,
            source_evidence_digest: registry_snapshot.source_evidence_digest,
            model_profile_digest: model_profile.profile_digest,
            model_tuple_digest,
            complete_eligible_set_digest,
            eligible_before_truncation,
            retained_count,
            omitted_count,
            bindings,
            candidate_decisions: decisions,
            audit_digest,
        },
    })
}

// ---------------------------------------------------------------------------
// Target operation 2: price_factors.
// ---------------------------------------------------------------------------

/// Price every retained factor and return registered V1 pricing receipts.
///
/// Any missing or invalid support fails closed rather than being treated as a
/// free/zero-cost factor.  The audited variant can preserve per-factor
/// unavailability without aborting the whole batch.
pub fn price_factors(
    candidates: &PromptCandidateSetReceiptV1,
    causal_estimates: &[PromptCausalEstimateV1],
    costs: &[PromptFactorCostV1],
) -> Result<Vec<PromptPricingReceiptV1>, PolicyError> {
    let candidate_set_digest = digest_candidate_set_receipt(candidates);
    let estimates = index_causal_estimates(causal_estimates)?;
    let costs = index_costs(costs)?;
    let mut receipts = Vec::with_capacity(candidates.candidate_factor_ids.len());
    for factor_id in &candidates.candidate_factor_ids {
        let estimate = estimates.get(factor_id).ok_or_else(|| {
            PolicyError::PricingUnavailable(
                factor_id.to_string(),
                PromptPricingUnavailableReasonV1::MissingCausalEstimate,
            )
        })?;
        let cost = costs.get(factor_id).ok_or_else(|| {
            PolicyError::PricingUnavailable(
                factor_id.to_string(),
                PromptPricingUnavailableReasonV1::MissingCostModel,
            )
        })?;
        let (receipt, _) = price_one_factor(
            candidates,
            candidate_set_digest,
            None,
            estimate,
            cost,
        )?;
        receipts.push(receipt);
    }
    Ok(receipts)
}

pub fn price_factors_audited(
    candidates: &PromptCandidateSetBundleV1,
    causal_estimates: &[PromptCausalEstimateV1],
    costs: &[PromptFactorCostV1],
) -> Result<PromptPricingBatchV1, PolicyError> {
    if candidates.audit.candidate_set_digest != digest_candidate_set_receipt(&candidates.receipt) {
        return Err(PolicyError::CandidateSetDigestMismatch);
    }
    let estimates = index_causal_estimates(causal_estimates)?;
    let costs = index_costs(costs)?;
    let bindings = candidates
        .audit
        .bindings
        .iter()
        .map(|binding| (binding.factor_id.clone(), binding))
        .collect::<BTreeMap<_, _>>();

    let mut receipts = Vec::new();
    let mut audit_entries = Vec::new();
    let mut unavailable = Vec::new();
    for factor_id in &candidates.receipt.candidate_factor_ids {
        let Some(estimate) = estimates.get(factor_id) else {
            unavailable.push(PromptUnavailablePricingV1 {
                factor_id: factor_id.clone(),
                reason: PromptPricingUnavailableReasonV1::MissingCausalEstimate,
            });
            continue;
        };
        let Some(cost) = costs.get(factor_id) else {
            unavailable.push(PromptUnavailablePricingV1 {
                factor_id: factor_id.clone(),
                reason: PromptPricingUnavailableReasonV1::MissingCostModel,
            });
            continue;
        };
        let Some(binding) = bindings.get(factor_id).copied() else {
            return Err(PolicyError::EvidenceBindingMismatch(factor_id.to_string()));
        };
        match price_one_factor(
            &candidates.receipt,
            candidates.audit.candidate_set_digest,
            Some(binding),
            estimate,
            cost,
        ) {
            Ok((receipt, audit)) => {
                receipts.push(receipt);
                audit_entries.push(audit);
            }
            Err(error) => {
                let reason = pricing_error_reason(&error);
                if let Some(reason) = reason {
                    unavailable.push(PromptUnavailablePricingV1 {
                        factor_id: factor_id.clone(),
                        reason,
                    });
                } else {
                    return Err(error);
                }
            }
        }
    }

    let batch_digest = digest_pricing_batch(
        candidates.audit.candidate_set_digest,
        candidates.audit.complete_eligible_set_digest,
        candidates.audit.omitted_count,
        candidates.audit.model_profile_digest,
        &receipts,
        &audit_entries,
        &unavailable,
    );
    Ok(PromptPricingBatchV1 {
        candidate_set_digest: candidates.audit.candidate_set_digest,
        complete_eligible_set_digest: candidates.audit.complete_eligible_set_digest,
        omitted_count: candidates.audit.omitted_count,
        model_profile_digest: candidates.audit.model_profile_digest,
        receipts,
        audit_entries,
        unavailable,
        batch_digest,
    })
}

// ---------------------------------------------------------------------------
// Enumeration helpers.
// ---------------------------------------------------------------------------

fn validate_enumeration_inputs(
    registry_snapshot: &PromptRegistrySnapshotV1,
    objective: &PromptObjectiveContextV1,
    model_profile: &PromptModelProfileV1,
) -> Result<(), PolicyError> {
    if registry_snapshot.factors.len() > MAX_POLICY_ENUMERATION_INPUT {
        return Err(PolicyError::EnumerationInputLimitExceeded);
    }
    for (digest, label) in [
        (registry_snapshot.registry_digest, "registry snapshot"),
        (registry_snapshot.source_evidence_digest, "registry source evidence"),
        (objective.objective_digest, "objective"),
        (objective.state_digest, "state"),
        (objective.selection_grammar_digest, "selection grammar"),
        (model_profile.profile_digest, "model profile"),
        (model_profile.tokenizer_digest, "tokenizer"),
        (model_profile.system_template_digest, "system template"),
        (model_profile.tool_schema_digest, "tool schema"),
        (model_profile.context_profile_digest, "context profile"),
    ] {
        validate_nonzero_digest(digest, label)?;
    }
    Ok(())
}

fn validate_factor_snapshot(factor: &PromptFactorSnapshotV1) -> Result<(), PolicyError> {
    validate_identifier(&factor.factor_id, "factor")?;
    validate_identifier(&factor.realization_id, "realization")?;
    validate_nonzero_digest(factor.realization_context_digest, "realization context")?;
    validate_nonzero_digest(factor.support_reference_digest, "factor support")?;
    if factor.token_upper_bound > MAX_POLICY_TOKEN_BUDGET {
        return Err(PolicyError::TokenBudgetLimitExceeded);
    }
    if factor.objective_scope_digest.is_some_and(Digest32::is_zero) {
        return Err(PolicyError::EmptyDigest("objective scope"));
    }
    if factor.model_profile_digest.is_some_and(Digest32::is_zero) {
        return Err(PolicyError::EmptyDigest("factor model profile"));
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Pricing helpers.
// ---------------------------------------------------------------------------

fn index_causal_estimates(
    causal_estimates: &[PromptCausalEstimateV1],
) -> Result<BTreeMap<StableId, &PromptCausalEstimateV1>, PolicyError> {
    let mut index = BTreeMap::new();
    for estimate in causal_estimates {
        if index.insert(estimate.factor_id.clone(), estimate).is_some() {
            return Err(PolicyError::DuplicatePricing(estimate.factor_id.to_string()));
        }
    }
    Ok(index)
}

fn index_costs(
    costs: &[PromptFactorCostV1],
) -> Result<BTreeMap<StableId, &PromptFactorCostV1>, PolicyError> {
    let mut index = BTreeMap::new();
    for cost in costs {
        if index.insert(cost.factor_id.clone(), cost).is_some() {
            return Err(PolicyError::DuplicatePricing(cost.factor_id.to_string()));
        }
    }
    Ok(index)
}

fn price_one_factor(
    candidates: &PromptCandidateSetReceiptV1,
    candidate_set_digest: Digest32,
    binding: Option<&PromptCandidateBindingV1>,
    estimate: &PromptCausalEstimateV1,
    cost: &PromptFactorCostV1,
) -> Result<(PromptPricingReceiptV1, PromptPricingAuditEntryV1), PolicyError> {
    if estimate.factor_id != cost.factor_id {
        return Err(PolicyError::EvidenceBindingMismatch(
            estimate.factor_id.to_string(),
        ));
    }
    if estimate.candidate_set_digest != candidate_set_digest
        || estimate.registry_digest != candidates.registry_digest
        || estimate.state_digest != candidates.state_digest
        || estimate.causal_support_digest.is_zero()
        || cost.cost_support_digest.is_zero()
    {
        return Err(PolicyError::EvidenceBindingMismatch(
            estimate.factor_id.to_string(),
        ));
    }
    if let Some(binding) = binding {
        if estimate.model_profile_digest != binding.model_profile_digest
            || estimate.realization_context_digest != binding.realization_context_digest
        {
            return Err(PolicyError::EvidenceBindingMismatch(
                estimate.factor_id.to_string(),
            ));
        }
        if cost.token_cost > binding.token_upper_bound {
            return Err(PolicyError::RegisteredTokenBoundExceeded(
                estimate.factor_id.to_string(),
            ));
        }
    }
    validate_confidence_interval(&estimate.factor_id, &estimate.confidence_interval)?;
    validate_cost(cost)?;

    let total_cost = sum_costs(cost)?;
    let net_expected_utility = estimate
        .incremental_recursive_utility_q32
        .checked_sub(total_cost)
        .map_err(|_| PolicyError::Arithmetic)?;
    let receipt = PromptPricingReceiptV1 {
        factor_id: estimate.factor_id.clone(),
        state_digest: estimate.state_digest,
        expected_utility_q32: net_expected_utility,
        downside_q32: estimate.downside_q32,
        token_cost: cost.token_cost,
        latency_cost_micros: cost.latency_cost_micros,
        interference_ppm: cost.interference_ppm,
        confidence_interval: estimate.confidence_interval.clone(),
    };
    let decomposition = PromptPricingDecompositionV1 {
        causal_incremental_utility_q32: estimate.incremental_recursive_utility_q32,
        token_utility_cost_q32: cost.token_utility_cost_q32,
        latency_utility_cost_q32: cost.latency_utility_cost_q32,
        context_crowding_cost_q32: cost.context_crowding_cost_q32,
        instruction_interference_cost_q32: cost.instruction_interference_cost_q32,
        privacy_cost_q32: cost.privacy_cost_q32,
        instability_cost_q32: cost.instability_cost_q32,
        future_context_option_value_cost_q32: cost.future_context_option_value_cost_q32,
        resource_cost_q32: cost.resource_cost_q32,
        total_utility_cost_q32: total_cost,
        net_expected_utility_q32: net_expected_utility,
    };
    let entry_digest = digest_pricing_entry(
        &receipt,
        estimate.model_profile_digest,
        estimate.realization_context_digest,
        estimate.causal_support_digest,
        cost.cost_support_digest,
        &decomposition,
    );
    Ok((
        receipt,
        PromptPricingAuditEntryV1 {
            factor_id: estimate.factor_id.clone(),
            model_profile_digest: estimate.model_profile_digest,
            realization_context_digest: estimate.realization_context_digest,
            causal_support_digest: estimate.causal_support_digest,
            cost_support_digest: cost.cost_support_digest,
            decomposition,
            entry_digest,
        },
    ))
}

fn pricing_error_reason(error: &PolicyError) -> Option<PromptPricingUnavailableReasonV1> {
    match error {
        PolicyError::EvidenceBindingMismatch(_) => {
            Some(PromptPricingUnavailableReasonV1::EvidenceBindingMismatch)
        }
        PolicyError::InvalidConfidenceInterval(_) => {
            Some(PromptPricingUnavailableReasonV1::InvalidConfidenceInterval)
        }
        PolicyError::InvalidCost(_) => Some(PromptPricingUnavailableReasonV1::InvalidCost),
        PolicyError::RegisteredTokenBoundExceeded(_) => {
            Some(PromptPricingUnavailableReasonV1::RegisteredTokenBoundExceeded)
        }
        _ => None,
    }
}

fn validate_confidence_interval(
    factor_id: &StableId,
    interval: &PromptConfidenceIntervalV1,
) -> Result<(), PolicyError> {
    if interval.lower_q32 > interval.upper_q32
        || interval.confidence_ppm > PPM_ONE
        || interval.support_digest.is_zero()
        || interval.scope_digest.is_zero()
    {
        return Err(PolicyError::InvalidConfidenceInterval(
            factor_id.to_string(),
        ));
    }
    Ok(())
}

fn validate_cost(cost: &PromptFactorCostV1) -> Result<(), PolicyError> {
    if cost.token_cost > MAX_POLICY_TOKEN_BUDGET
        || cost.interference_ppm > PPM_ONE
        || cost.cost_support_digest.is_zero()
        || [
            cost.token_utility_cost_q32,
            cost.latency_utility_cost_q32,
            cost.context_crowding_cost_q32,
            cost.instruction_interference_cost_q32,
            cost.privacy_cost_q32,
            cost.instability_cost_q32,
            cost.future_context_option_value_cost_q32,
            cost.resource_cost_q32,
        ]
        .into_iter()
        .any(|value| value < FixedQ32::ZERO)
    {
        return Err(PolicyError::InvalidCost(cost.factor_id.to_string()));
    }
    Ok(())
}

fn sum_costs(cost: &PromptFactorCostV1) -> Result<FixedQ32, PolicyError> {
    [
        cost.token_utility_cost_q32,
        cost.latency_utility_cost_q32,
        cost.context_crowding_cost_q32,
        cost.instruction_interference_cost_q32,
        cost.privacy_cost_q32,
        cost.instability_cost_q32,
        cost.future_context_option_value_cost_q32,
        cost.resource_cost_q32,
    ]
    .into_iter()
    .try_fold(FixedQ32::ZERO, |total, value| {
        total.checked_add(value).map_err(|_| PolicyError::Arithmetic)
    })
}
