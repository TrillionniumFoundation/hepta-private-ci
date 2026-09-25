// ---------------------------------------------------------------------------
// Target operation 3: select_portfolio.
// ---------------------------------------------------------------------------

/// Select a bounded portfolio from registered prices.
///
/// This is deliberately a bounded heuristic.  It evaluates transitive
/// prerequisite closure as one package, so a negative standalone prerequisite
/// can still be selected when the dependent bundle has positive marginal
/// utility.  Missing interaction edges follow the graph's explicit policy.
pub fn select_portfolio(
    prices: &[PromptPricingReceiptV1],
    interactions: &PromptInteractionGraphV1,
    budget: &PromptPortfolioBudgetV1,
) -> Result<PromptPortfolioReceiptV1, PolicyError> {
    let pricing = PromptPricingBatchV1 {
        candidate_set_digest: interactions.candidate_set_digest,
        complete_eligible_set_digest: Digest32::ZERO,
        omitted_count: 0,
        model_profile_digest: Digest32::ZERO,
        receipts: prices.to_vec(),
        audit_entries: Vec::new(),
        unavailable: Vec::new(),
        batch_digest: digest_public_prices(interactions.candidate_set_digest, prices),
    };
    Ok(select_portfolio_audited(&pricing, interactions, budget)?.receipt)
}

pub fn select_portfolio_audited(
    pricing: &PromptPricingBatchV1,
    interactions: &PromptInteractionGraphV1,
    budget: &PromptPortfolioBudgetV1,
) -> Result<PromptPortfolioDecisionV1, PolicyError> {
    validate_portfolio_inputs(pricing, interactions, budget)?;
    let price_map = index_prices(&pricing.receipts, &interactions.candidate_factor_ids)?;
    let constraint_index = validate_constraint_graph(
        &interactions.candidate_factor_ids,
        &interactions.hard_constraints,
    )?;
    let interaction_index = validate_interaction_graph(interactions)?;
    let interaction_digest = digest_interaction_graph(interactions);
    let constraint_digest = digest_constraints(&interactions.hard_constraints);

    let mut selected = BTreeSet::new();
    let mut selected_order = Vec::new();
    let mut used_tokens = 0_u32;
    let mut total_utility = FixedQ32::ZERO;
    let mut steps = 0_usize;

    while selected.len() < budget.maximum_selected_factors && steps < MAX_POLICY_MARGINAL_STEPS {
        steps = steps.checked_add(1).ok_or(PolicyError::Arithmetic)?;
        let mut best: Option<PackageEvaluation> = None;
        for root in &interactions.candidate_factor_ids {
            if selected.contains(root) || !price_map.contains_key(root) {
                continue;
            }
            let evaluation = evaluate_package(
                root,
                &selected,
                &price_map,
                &constraint_index,
                &interaction_index,
                interactions.missing_interaction_policy,
                budget,
                used_tokens,
            )?;
            let Some(evaluation) = evaluation else {
                continue;
            };
            if evaluation.marginal_utility <= FixedQ32::ZERO {
                continue;
            }
            let replace = best.as_ref().is_none_or(|current| {
                evaluation.marginal_utility > current.marginal_utility
                    || (evaluation.marginal_utility == current.marginal_utility
                        && (evaluation.token_cost < current.token_cost
                            || (evaluation.token_cost == current.token_cost
                                && evaluation.root_factor_id < current.root_factor_id)))
            });
            if replace {
                best = Some(evaluation);
            }
        }

        let Some(best) = best else {
            break;
        };
        used_tokens = used_tokens
            .checked_add(best.token_cost)
            .ok_or(PolicyError::Arithmetic)?;
        total_utility = total_utility
            .checked_add(best.marginal_utility)
            .map_err(|_| PolicyError::Arithmetic)?;
        for factor_id in best.ordered_package {
            if selected.insert(factor_id.clone()) {
                selected_order.push(factor_id);
            }
        }
    }

    let receipt = PromptPortfolioReceiptV1 {
        portfolio_id: budget.portfolio_id.clone(),
        candidate_set_digest: interactions.candidate_set_digest,
        factor_ids: selected_order,
        interaction_digest,
        expected_utility_q32: total_utility,
        total_token_upper_bound: used_tokens,
        valid_until_unix_ms: budget.valid_until_unix_ms,
    };

    let candidate_decisions = portfolio_candidate_audit(
        &selected,
        &price_map,
        &constraint_index,
        &interaction_index,
        interactions,
        budget,
        used_tokens,
    )?;
    let priced_count = u32::try_from(pricing.receipts.len()).map_err(|_| PolicyError::Arithmetic)?;
    let unavailable_pricing_count = u32::try_from(pricing.unavailable.len())
        .map_err(|_| PolicyError::Arithmetic)?;
    let audit_digest = digest_portfolio_audit(
        &receipt,
        pricing.complete_eligible_set_digest,
        pricing.omitted_count,
        priced_count,
        unavailable_pricing_count,
        constraint_digest,
        pricing.batch_digest,
        pricing.model_profile_digest,
        &candidate_decisions,
    );
    let audit = PromptPortfolioAuditV1 {
        candidate_set_digest: interactions.candidate_set_digest,
        complete_eligible_set_digest: pricing.complete_eligible_set_digest,
        omitted_count: pricing.omitted_count,
        priced_count,
        unavailable_pricing_count,
        interaction_digest,
        constraint_digest,
        pricing_batch_digest: pricing.batch_digest,
        model_profile_digest: pricing.model_profile_digest,
        candidate_decisions,
        selection_method: PromptSelectionMethodV1::GreedyPrerequisiteClosureV1,
        optimality: PromptOptimalityDisclosureV1::HeuristicNoCertificate,
        requires_registered_exercise_boundary: true,
        audit_digest,
    };
    Ok(PromptPortfolioDecisionV1 { receipt, audit })
}
