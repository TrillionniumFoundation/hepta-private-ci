// ---------------------------------------------------------------------------
// Portfolio helpers.
// ---------------------------------------------------------------------------

#[derive(Clone, Debug)]
struct ConstraintIndex {
    requires: BTreeMap<StableId, Vec<StableId>>,
    conflicts: BTreeSet<(StableId, StableId)>,
}

#[derive(Clone, Debug)]
struct InteractionIndex {
    edges: BTreeMap<(StableId, StableId), FixedQ32>,
}

#[derive(Clone, Debug)]
struct PackageEvaluation {
    root_factor_id: StableId,
    ordered_package: Vec<StableId>,
    token_cost: u32,
    marginal_utility: FixedQ32,
}

fn validate_portfolio_inputs(
    pricing: &PromptPricingBatchV1,
    interactions: &PromptInteractionGraphV1,
    budget: &PromptPortfolioBudgetV1,
) -> Result<(), PolicyError> {
    if interactions.candidate_factor_ids.len() > MAX_POLICY_FACTORS {
        return Err(PolicyError::FactorLimitExceeded);
    }
    if interactions.edges.len() > MAX_POLICY_INTERACTION_EDGES {
        return Err(PolicyError::InteractionEdgeLimitExceeded);
    }
    if interactions.hard_constraints.len() > MAX_POLICY_HARD_CONSTRAINTS {
        return Err(PolicyError::HardConstraintLimitExceeded);
    }
    if budget.maximum_selected_factors == 0
        || budget.maximum_selected_factors > MAX_POLICY_SELECTED_FACTORS
    {
        return Err(PolicyError::SelectedFactorLimitExceeded);
    }
    if budget.token_budget > MAX_POLICY_TOKEN_BUDGET {
        return Err(PolicyError::TokenBudgetLimitExceeded);
    }
    if budget.valid_until_unix_ms == 0 {
        return Err(PolicyError::InvalidPortfolioValidity);
    }
    validate_identifier(&budget.portfolio_id, "portfolio")?;
    validate_nonzero_digest(interactions.candidate_set_digest, "candidate set")?;
    validate_nonzero_digest(interactions.source_evidence_digest, "interaction source evidence")?;
    if pricing.candidate_set_digest != interactions.candidate_set_digest {
        return Err(PolicyError::CandidateSetDigestMismatch);
    }
    validate_factor_id_list(&interactions.candidate_factor_ids)?;
    Ok(())
}

fn validate_factor_id_list(factor_ids: &[StableId]) -> Result<(), PolicyError> {
    if factor_ids
        .windows(2)
        .any(|pair| pair[0] >= pair[1])
    {
        return Err(PolicyError::NonCanonicalFactorOrder);
    }
    let mut seen = BTreeSet::new();
    for factor_id in factor_ids {
        validate_identifier(factor_id, "factor")?;
        if !seen.insert(factor_id.clone()) {
            return Err(PolicyError::DuplicateFactor(factor_id.to_string()));
        }
    }
    Ok(())
}

fn index_prices<'a>(
    prices: &'a [PromptPricingReceiptV1],
    factor_ids: &[StableId],
) -> Result<BTreeMap<StableId, &'a PromptPricingReceiptV1>, PolicyError> {
    let known: BTreeSet<StableId> = factor_ids.iter().cloned().collect();
    let mut index = BTreeMap::new();
    for price in prices {
        if !known.contains(&price.factor_id) {
            return Err(PolicyError::UnknownFactor(price.factor_id.to_string()));
        }
        if index.insert(price.factor_id.clone(), price).is_some() {
            return Err(PolicyError::DuplicatePricing(price.factor_id.to_string()));
        }
    }
    Ok(index)
}

fn validate_interaction_graph(
    graph: &PromptInteractionGraphV1,
) -> Result<InteractionIndex, PolicyError> {
    let known = graph.candidate_factor_ids.iter().cloned().collect::<BTreeSet<_>>();
    let mut edges = BTreeMap::new();
    let mut previous: Option<(StableId, StableId)> = None;
    for edge in &graph.edges {
        if edge.left_factor_id >= edge.right_factor_id {
            return Err(PolicyError::InvalidInteractionEndpoints);
        }
        if !known.contains(&edge.left_factor_id) || !known.contains(&edge.right_factor_id) {
            return Err(PolicyError::UnknownFactor(if !known.contains(&edge.left_factor_id) {
                edge.left_factor_id.to_string()
            } else {
                edge.right_factor_id.to_string()
            }));
        }
        if edge.support_reference_digest.is_zero() {
            return Err(PolicyError::EmptyDigest("interaction support"));
        }
        let key = (edge.left_factor_id.clone(), edge.right_factor_id.clone());
        if previous.as_ref().is_some_and(|value| value >= &key) {
            return Err(PolicyError::NonCanonicalInteractionOrder);
        }
        previous = Some(key.clone());
        if edges.insert(key.clone(), edge.marginal_utility_q32).is_some() {
            return Err(PolicyError::DuplicateInteraction(
                key.0.to_string(),
                key.1.to_string(),
            ));
        }
    }

    if graph.missing_interaction_policy == PromptMissingInteractionPolicyV1::RejectMissing {
        for (left_index, left) in graph.candidate_factor_ids.iter().enumerate() {
            for right in graph.candidate_factor_ids.iter().skip(left_index + 1) {
                if !edges.contains_key(&(left.clone(), right.clone())) {
                    return Err(PolicyError::MissingPairInteraction(
                        left.to_string(),
                        right.to_string(),
                    ));
                }
            }
        }
    }
    Ok(InteractionIndex { edges })
}

fn validate_constraint_graph(
    factor_ids: &[StableId],
    constraints: &[PromptHardConstraintV1],
) -> Result<ConstraintIndex, PolicyError> {
    let known = factor_ids.iter().cloned().collect::<BTreeSet<_>>();
    let mut requires: BTreeMap<StableId, Vec<StableId>> = BTreeMap::new();
    let mut conflicts = BTreeSet::new();
    let mut keys = BTreeSet::new();
    let mut previous: Option<(u8, StableId, StableId)> = None;

    for constraint in constraints {
        let (kind, left, right, support) = constraint_parts(constraint);
        if left == right || (kind == 0 && left > right) {
            return Err(PolicyError::InvalidConstraintEndpoints);
        }
        if !known.contains(left) || !known.contains(right) {
            return Err(PolicyError::UnknownFactor(if !known.contains(left) {
                left.to_string()
            } else {
                right.to_string()
            }));
        }
        if support.is_zero() {
            return Err(PolicyError::EmptyDigest("hard constraint support"));
        }
        let key = (kind, left.clone(), right.clone());
        if previous.as_ref().is_some_and(|value| value >= &key) {
            return Err(PolicyError::NonCanonicalConstraintOrder);
        }
        previous = Some(key.clone());
        if !keys.insert(key.clone()) {
            return Err(PolicyError::DuplicateConstraint(
                if kind == 0 { "conflict" } else { "requires" },
                left.to_string(),
                right.to_string(),
            ));
        }
        if kind == 0 {
            conflicts.insert((left.clone(), right.clone()));
        } else {
            requires.entry(left.clone()).or_default().push(right.clone());
        }
    }

    for dependencies in requires.values_mut() {
        dependencies.sort();
    }
    let index = ConstraintIndex { requires, conflicts };
    detect_requires_cycles(factor_ids, &index)?;
    detect_constraint_contradictions(factor_ids, &index)?;
    Ok(index)
}

fn constraint_parts(
    constraint: &PromptHardConstraintV1,
) -> (u8, &StableId, &StableId, Digest32) {
    match constraint {
        PromptHardConstraintV1::Conflict {
            left_factor_id,
            right_factor_id,
            support_reference_digest,
        } => (0, left_factor_id, right_factor_id, *support_reference_digest),
        PromptHardConstraintV1::Requires {
            factor_id,
            prerequisite_factor_id,
            support_reference_digest,
        } => (1, factor_id, prerequisite_factor_id, *support_reference_digest),
    }
}

fn detect_requires_cycles(
    factor_ids: &[StableId],
    index: &ConstraintIndex,
) -> Result<(), PolicyError> {
    let mut visiting = BTreeSet::new();
    let mut visited = BTreeSet::new();
    for factor_id in factor_ids {
        detect_requires_cycle_from(factor_id, index, &mut visiting, &mut visited)?;
    }
    Ok(())
}

fn detect_requires_cycle_from(
    factor_id: &StableId,
    index: &ConstraintIndex,
    visiting: &mut BTreeSet<StableId>,
    visited: &mut BTreeSet<StableId>,
) -> Result<(), PolicyError> {
    if visited.contains(factor_id) {
        return Ok(());
    }
    if !visiting.insert(factor_id.clone()) {
        return Err(PolicyError::RequiresCycle(factor_id.to_string()));
    }
    if let Some(prerequisites) = index.requires.get(factor_id) {
        for prerequisite in prerequisites {
            detect_requires_cycle_from(prerequisite, index, visiting, visited)?;
        }
    }
    visiting.remove(factor_id);
    visited.insert(factor_id.clone());
    Ok(())
}

fn detect_constraint_contradictions(
    factor_ids: &[StableId],
    index: &ConstraintIndex,
) -> Result<(), PolicyError> {
    for factor_id in factor_ids {
        let closure = prerequisite_closure(factor_id, index)?;
        let closure_vec = closure.iter().collect::<Vec<_>>();
        for (left_index, left) in closure_vec.iter().enumerate() {
            for right in closure_vec.iter().skip(left_index + 1) {
                if conflict_exists(left, right, index) {
                    return Err(PolicyError::UnsatisfiableConstraintGraph(
                        factor_id.to_string(),
                    ));
                }
            }
        }
    }
    Ok(())
}

fn prerequisite_closure(
    factor_id: &StableId,
    index: &ConstraintIndex,
) -> Result<BTreeSet<StableId>, PolicyError> {
    let mut closure = BTreeSet::new();
    collect_prerequisites(factor_id, index, &mut closure)?;
    Ok(closure)
}

fn collect_prerequisites(
    factor_id: &StableId,
    index: &ConstraintIndex,
    closure: &mut BTreeSet<StableId>,
) -> Result<(), PolicyError> {
    if !closure.insert(factor_id.clone()) {
        return Ok(());
    }
    if closure.len() > MAX_POLICY_FACTORS {
        return Err(PolicyError::FactorLimitExceeded);
    }
    if let Some(prerequisites) = index.requires.get(factor_id) {
        for prerequisite in prerequisites {
            collect_prerequisites(prerequisite, index, closure)?;
        }
    }
    Ok(())
}

fn ordered_prerequisite_package(
    root: &StableId,
    index: &ConstraintIndex,
    already_selected: &BTreeSet<StableId>,
) -> Result<Vec<StableId>, PolicyError> {
    let mut emitted = already_selected.clone();
    let mut order = Vec::new();
    emit_prerequisites(root, index, &mut emitted, &mut order)?;
    Ok(order)
}

fn emit_prerequisites(
    factor_id: &StableId,
    index: &ConstraintIndex,
    emitted: &mut BTreeSet<StableId>,
    order: &mut Vec<StableId>,
) -> Result<(), PolicyError> {
    if emitted.contains(factor_id) {
        return Ok(());
    }
    if let Some(prerequisites) = index.requires.get(factor_id) {
        for prerequisite in prerequisites {
            emit_prerequisites(prerequisite, index, emitted, order)?;
        }
    }
    if emitted.insert(factor_id.clone()) {
        order.push(factor_id.clone());
    }
    if order.len() > MAX_POLICY_FACTORS {
        return Err(PolicyError::FactorLimitExceeded);
    }
    Ok(())
}

fn evaluate_package(
    root: &StableId,
    selected: &BTreeSet<StableId>,
    price_map: &BTreeMap<StableId, &PromptPricingReceiptV1>,
    constraints: &ConstraintIndex,
    interactions: &InteractionIndex,
    missing_policy: PromptMissingInteractionPolicyV1,
    budget: &PromptPortfolioBudgetV1,
    used_tokens: u32,
) -> Result<Option<PackageEvaluation>, PolicyError> {
    let ordered_package = ordered_prerequisite_package(root, constraints, selected)?;
    if ordered_package.is_empty() {
        return Ok(None);
    }
    if selected
        .len()
        .checked_add(ordered_package.len())
        .is_none_or(|count| count > budget.maximum_selected_factors)
    {
        return Ok(None);
    }
    if package_conflicts(&ordered_package, selected, constraints) {
        return Ok(None);
    }

    let mut token_cost = 0_u32;
    let mut marginal_utility = FixedQ32::ZERO;
    for factor_id in &ordered_package {
        let Some(price) = price_map.get(factor_id) else {
            return Ok(None);
        };
        token_cost = token_cost
            .checked_add(price.token_cost)
            .ok_or(PolicyError::Arithmetic)?;
        marginal_utility = marginal_utility
            .checked_add(price.expected_utility_q32)
            .map_err(|_| PolicyError::Arithmetic)?;
    }
    if used_tokens
        .checked_add(token_cost)
        .is_none_or(|total| total > budget.token_budget)
    {
        return Ok(None);
    }

    let new_set = ordered_package.iter().cloned().collect::<BTreeSet<_>>();
    let union = selected.union(&new_set).cloned().collect::<Vec<_>>();
    for (left_index, left) in union.iter().enumerate() {
        for right in union.iter().skip(left_index + 1) {
            if !new_set.contains(left) && !new_set.contains(right) {
                continue;
            }
            let marginal = interaction_value(left, right, interactions, missing_policy)?;
            marginal_utility = marginal_utility
                .checked_add(marginal)
                .map_err(|_| PolicyError::Arithmetic)?;
        }
    }

    Ok(Some(PackageEvaluation {
        root_factor_id: root.clone(),
        ordered_package,
        token_cost,
        marginal_utility,
    }))
}

fn package_conflicts(
    package: &[StableId],
    selected: &BTreeSet<StableId>,
    constraints: &ConstraintIndex,
) -> bool {
    let package_set = package.iter().cloned().collect::<BTreeSet<_>>();
    let union = selected.union(&package_set).cloned().collect::<Vec<_>>();
    for (left_index, left) in union.iter().enumerate() {
        for right in union.iter().skip(left_index + 1) {
            if conflict_exists(left, right, constraints) {
                return true;
            }
        }
    }
    false
}

fn conflict_exists(left: &StableId, right: &StableId, index: &ConstraintIndex) -> bool {
    let key = ordered_pair(left, right);
    index.conflicts.contains(&key)
}

fn interaction_value(
    left: &StableId,
    right: &StableId,
    index: &InteractionIndex,
    missing_policy: PromptMissingInteractionPolicyV1,
) -> Result<FixedQ32, PolicyError> {
    let key = ordered_pair(left, right);
    match index.edges.get(&key).copied() {
        Some(value) => Ok(value),
        None if missing_policy == PromptMissingInteractionPolicyV1::AssumeZero => {
            Ok(FixedQ32::ZERO)
        }
        None => Err(PolicyError::MissingPairInteraction(
            key.0.to_string(),
            key.1.to_string(),
        )),
    }
}

fn portfolio_candidate_audit(
    selected: &BTreeSet<StableId>,
    price_map: &BTreeMap<StableId, &PromptPricingReceiptV1>,
    constraints: &ConstraintIndex,
    interaction_index: &InteractionIndex,
    graph: &PromptInteractionGraphV1,
    budget: &PromptPortfolioBudgetV1,
    used_tokens: u32,
) -> Result<Vec<PromptPortfolioCandidateAuditV1>, PolicyError> {
    let mut decisions = Vec::with_capacity(graph.candidate_factor_ids.len());
    for factor_id in &graph.candidate_factor_ids {
        let disposition = if selected.contains(factor_id) {
            PromptPortfolioDispositionV1::Selected
        } else if !price_map.contains_key(factor_id) {
            PromptPortfolioDispositionV1::UnavailablePricing
        } else {
            classify_unselected_factor(
                factor_id,
                selected,
                price_map,
                constraints,
                interaction_index,
                graph.missing_interaction_policy,
                budget,
                used_tokens,
            )?
        };
        decisions.push(PromptPortfolioCandidateAuditV1 {
            factor_id: factor_id.clone(),
            disposition,
        });
    }
    Ok(decisions)
}

fn classify_unselected_factor(
    factor_id: &StableId,
    selected: &BTreeSet<StableId>,
    price_map: &BTreeMap<StableId, &PromptPricingReceiptV1>,
    constraints: &ConstraintIndex,
    interaction_index: &InteractionIndex,
    missing_policy: PromptMissingInteractionPolicyV1,
    budget: &PromptPortfolioBudgetV1,
    used_tokens: u32,
) -> Result<PromptPortfolioDispositionV1, PolicyError> {
    let package = ordered_prerequisite_package(factor_id, constraints, selected)?;
    if package_conflicts(&package, selected, constraints) {
        return Ok(PromptPortfolioDispositionV1::HardConflict);
    }
    if selected
        .len()
        .checked_add(package.len())
        .is_none_or(|count| count > budget.maximum_selected_factors)
    {
        return Ok(PromptPortfolioDispositionV1::SelectionLimit);
    }
    let mut token_cost = 0_u32;
    for item in &package {
        let Some(price) = price_map.get(item) else {
            return Ok(PromptPortfolioDispositionV1::UnavailablePricing);
        };
        token_cost = token_cost
            .checked_add(price.token_cost)
            .ok_or(PolicyError::Arithmetic)?;
    }
    if used_tokens
        .checked_add(token_cost)
        .is_none_or(|total| total > budget.token_budget)
    {
        return Ok(PromptPortfolioDispositionV1::OverTokenBudget);
    }
    let Some(evaluation) = evaluate_package(
        factor_id,
        selected,
        price_map,
        constraints,
        interaction_index,
        missing_policy,
        budget,
        used_tokens,
    )? else {
        return Ok(PromptPortfolioDispositionV1::HeuristicExcluded);
    };
    if evaluation.marginal_utility <= FixedQ32::ZERO {
        Ok(PromptPortfolioDispositionV1::NonPositivePackageUtility)
    } else {
        Ok(PromptPortfolioDispositionV1::HeuristicExcluded)
    }
}

fn ordered_pair(left: &StableId, right: &StableId) -> (StableId, StableId) {
    if left < right {
        (left.clone(), right.clone())
    } else {
        (right.clone(), left.clone())
    }
}
