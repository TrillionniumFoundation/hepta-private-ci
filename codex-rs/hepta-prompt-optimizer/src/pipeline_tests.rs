use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("valid test id");
    };
    value
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn registry_factor(name: &str) -> PromptRegistryFactorV1 {
    PromptRegistryFactorV1 {
        candidate_id: id(&format!("candidate:{name}")),
        factor_id: id(&format!("factor:{name}")),
        realization_id: id(&format!("realization:{name}")),
        admitted: true,
        legal: true,
        objective_scope_digest: digest("scope"),
        model_compatibility_digest: digest("compat"),
        token_upper_bound: 1_000,
        registry_entry_digest: digest(&format!("registry-entry:{name}")),
        support_reference_digest: digest(&format!("factor-support:{name}")),
    }
}

fn registry(factors: Vec<PromptRegistryFactorV1>) -> PromptRegistrySnapshotV1 {
    PromptRegistrySnapshotV1 {
        state_digest: digest("state"),
        registry_snapshot_digest: digest("registry"),
        registry_owner_digest: digest("registry-owner"),
        completeness_digest: digest("registry-complete"),
        factors,
    }
}

fn objective() -> PromptObjectiveProfileV1 {
    PromptObjectiveProfileV1 {
        objective_digest: digest("objective"),
        scope_digest: digest("scope"),
    }
}

fn model() -> PromptModelProfileV1 {
    PromptModelProfileV1 {
        model_profile_digest: digest("model"),
        compatibility_digest: digest("compat"),
        selection_grammar_digest: digest("grammar"),
    }
}

fn estimate(name: &str, gain: i64, supported: bool) -> PromptCausalEstimateV1 {
    PromptCausalEstimateV1 {
        factor_id: id(&format!("factor:{name}")),
        causal_incremental_utility: FixedQ32::from_raw(gain),
        downside_q32: FixedQ32::from_raw(-5),
        confidence_lower_q32: FixedQ32::from_raw(gain.saturating_sub(10)),
        confidence_upper_q32: FixedQ32::from_raw(gain.saturating_add(10)),
        confidence_ppm: 900_000,
        support_status: if supported {
            CausalSupportStatusV1::Supported
        } else {
            CausalSupportStatusV1::Unsupported
        },
        estimator_digest: digest("estimator"),
        support_reference_digest: digest(&format!("causal-support:{name}")),
    }
}

fn zero_cost(name: &str, token_units: u32) -> PromptCostBreakdownV1 {
    PromptCostBreakdownV1 {
        factor_id: id(&format!("factor:{name}")),
        token_units,
        latency_cost_micros: u64::from(token_units) * 100,
        interference_ppm: 100,
        token_utility_cost: FixedQ32::ZERO,
        latency_utility_cost: FixedQ32::ZERO,
        interference_utility_cost: FixedQ32::ZERO,
        resource_utility_cost: FixedQ32::ZERO,
        privacy_utility_cost: FixedQ32::ZERO,
        instability_utility_cost: FixedQ32::ZERO,
        future_context_option_value_cost: FixedQ32::ZERO,
        support_reference_digest: digest(&format!("cost-support:{name}")),
    }
}

fn priced(specs: &[(&str, i64, u32)]) -> PromptPricingBatchV1 {
    let factors = specs
        .iter()
        .map(|(name, _, _)| registry_factor(name))
        .collect();
    let Ok(enumerated) = enumerate_factors_with_audit(registry(factors), objective(), model())
    else {
        panic!("enumeration must succeed");
    };
    let causal = PromptCausalEstimateSetV1 {
        state_digest: digest("state"),
        selection_grammar_digest: digest("grammar"),
        ledger_snapshot_digest: digest("ledger"),
        ledger_owner_digest: digest("ledger-owner"),
        estimates: specs
            .iter()
            .map(|(name, gain, _)| estimate(name, *gain, true))
            .collect(),
    };
    let costs = PromptCostModelV1 {
        state_digest: digest("state"),
        selection_grammar_digest: digest("grammar"),
        cost_model_digest: digest("cost-model"),
        costs: specs
            .iter()
            .map(|(name, _, tokens)| zero_cost(name, *tokens))
            .collect(),
    };
    let Ok(pricing) = price_factors_with_audit(enumerated, causal, costs) else {
        panic!("pricing must succeed");
    };
    pricing
}

fn relations(policy: UnknownInteractionPolicyV1) -> PromptInteractionSetV1 {
    PromptInteractionSetV1 {
        graph_snapshot_digest: digest("graph"),
        graph_owner_digest: digest("graph-owner"),
        unknown_interaction_policy: policy,
        interactions: Vec::new(),
        hard_constraints: Vec::new(),
    }
}

fn budget(tokens: u32, maximum_selected_factors: usize) -> PromptPortfolioBudgetV1 {
    PromptPortfolioBudgetV1 {
        token_budget: tokens,
        maximum_selected_factors,
        valid_until_unix_ms: 9_999_999,
    }
}

#[test]
fn registered_candidate_contract_shape_is_emitted_and_audit_records_truncation() {
    let factors = (0..130)
        .map(|index| registry_factor(&format!("{index:03}")))
        .collect();
    let Ok(enumerated) = enumerate_factors_with_audit(registry(factors), objective(), model())
    else {
        panic!("enumeration must succeed");
    };

    assert_eq!(
        enumerated.receipt.candidate_factor_ids.len(),
        MAX_FACTORS_V1
    );
    assert_eq!(enumerated.receipt.objective_digest, digest("objective"));
    assert_eq!(enumerated.receipt.state_digest, digest("state"));
    assert_eq!(enumerated.receipt.registry_digest, digest("registry"));
    assert_eq!(
        enumerated.receipt.selection_grammar_digest,
        digest("grammar")
    );
    assert_eq!(enumerated.audit.source_factor_count, 130);
    assert_eq!(enumerated.audit.eligible_factor_count, 130);
    assert_eq!(enumerated.audit.omitted_count, 2);
    assert_eq!(
        enumerated.audit.registry_completeness_digest,
        digest("registry-complete")
    );
    assert!(!enumerated.receipt.authority().grants_any());
}

#[test]
fn pricing_emits_exact_per_factor_contracts_and_explicit_decomposition() {
    let factors = vec![registry_factor("a"), registry_factor("b")];
    let Ok(enumerated) = enumerate_factors_with_audit(registry(factors), objective(), model())
    else {
        panic!("enumeration");
    };
    let causal = PromptCausalEstimateSetV1 {
        state_digest: digest("state"),
        selection_grammar_digest: digest("grammar"),
        ledger_snapshot_digest: digest("ledger"),
        ledger_owner_digest: digest("ledger-owner"),
        estimates: vec![estimate("a", 100, true), estimate("b", 500, false)],
    };
    let mut cost_a = zero_cost("a", 5);
    cost_a.token_utility_cost = FixedQ32::from_raw(4);
    cost_a.latency_utility_cost = FixedQ32::from_raw(4);
    cost_a.interference_utility_cost = FixedQ32::from_raw(4);
    cost_a.resource_utility_cost = FixedQ32::from_raw(4);
    cost_a.privacy_utility_cost = FixedQ32::from_raw(4);
    cost_a.instability_utility_cost = FixedQ32::from_raw(4);
    cost_a.future_context_option_value_cost = FixedQ32::from_raw(4);
    let costs = PromptCostModelV1 {
        state_digest: digest("state"),
        selection_grammar_digest: digest("grammar"),
        cost_model_digest: digest("cost-model"),
        costs: vec![cost_a, zero_cost("b", 5)],
    };

    let Ok(exact_receipts) = price_factors(enumerated.clone(), causal.clone(), costs.clone())
    else {
        panic!("registered pricing surface");
    };
    let Ok(batch) = price_factors_with_audit(enumerated, causal, costs) else {
        panic!("pricing");
    };
    assert_eq!(exact_receipts, batch.receipts);
    assert_eq!(batch.receipts.len(), 2);
    assert_eq!(batch.receipts[0].factor_id, id("factor:a"));
    assert_eq!(batch.receipts[0].state_digest, digest("state"));
    assert_eq!(
        batch.receipts[0].expected_utility_q32,
        FixedQ32::from_raw(72)
    );
    assert_eq!(batch.receipts[0].token_cost, 5);
    assert_eq!(batch.audit[0].total_utility_cost, FixedQ32::from_raw(28));
    assert_eq!(
        batch.audit[1].availability,
        PromptPriceAvailabilityV1::UnsupportedCausalEvidence
    );
    assert_eq!(batch.receipts[1].expected_utility_q32, FixedQ32::ZERO);
    assert!(!batch.receipts[0].authority().grants_any());
}

#[test]
fn v1_selector_handles_gain_first_counterexample_better_than_legacy_surface() {
    let pricing = priced(&[("a", 100, 10), ("b", 60, 5), ("c", 60, 5)]);
    let Ok(decision) = select_portfolio_with_audit(
        pricing,
        relations(UnknownInteractionPolicyV1::MissingAsZero),
        budget(10, 2),
    ) else {
        panic!("selection");
    };
    assert_eq!(
        decision.receipt.factor_ids,
        vec![id("factor:b"), id("factor:c")]
    );
    assert_eq!(
        decision.receipt.expected_utility_q32,
        FixedQ32::from_raw(120)
    );
    assert_eq!(
        decision.audit.optimality,
        PromptOptimalityDisclosureV1::HeuristicNoCertificate
    );
}

#[test]
fn prerequisite_closure_selects_negative_prerequisite_with_positive_dependent_bundle() {
    let pricing = priced(&[("dependent", 100, 1), ("prerequisite", -1, 1)]);
    let mut graph = relations(UnknownInteractionPolicyV1::MissingAsZero);
    graph
        .hard_constraints
        .push(PromptHardConstraintV1::Requires {
            factor_id: id("factor:dependent"),
            prerequisite_factor_id: id("factor:prerequisite"),
            support_reference_digest: digest("requires"),
        });
    let Ok(decision) = select_portfolio_with_audit(pricing, graph, budget(2, 2)) else {
        panic!("selection");
    };
    assert_eq!(
        decision.receipt.factor_ids,
        vec![id("factor:prerequisite"), id("factor:dependent")]
    );
    assert_eq!(
        decision.receipt.expected_utility_q32,
        FixedQ32::from_raw(99)
    );
    let Some(dependent) = decision
        .audit
        .decisions
        .iter()
        .find(|item| item.factor_id == id("factor:dependent"))
    else {
        panic!("dependent audit decision");
    };
    assert_eq!(
        dependent.prerequisite_closure,
        vec![id("factor:prerequisite"), id("factor:dependent")]
    );
}

#[test]
fn sparse_graph_allows_full_128_factor_multi_select_capacity() {
    let owned = (0..MAX_FACTORS_V1)
        .map(|index| (format!("{index:03}"), 10_i64, 1_u32))
        .collect::<Vec<_>>();
    let specs = owned
        .iter()
        .map(|(name, gain, tokens)| (name.as_str(), *gain, *tokens))
        .collect::<Vec<_>>();
    let pricing = priced(&specs);
    let Ok(decision) = select_portfolio_with_audit(
        pricing,
        relations(UnknownInteractionPolicyV1::MissingAsZero),
        budget(16, 16),
    ) else {
        panic!("sparse selection");
    };
    assert_eq!(decision.receipt.factor_ids.len(), 16);
    assert_eq!(
        decision.audit.unknown_interaction_policy,
        UnknownInteractionPolicyV1::MissingAsZero
    );
}

#[test]
fn reject_missing_interaction_policy_fails_closed_when_pair_is_needed() {
    let result = select_portfolio_with_audit(
        priced(&[("a", 10, 1), ("b", 9, 1)]),
        relations(UnknownInteractionPolicyV1::RejectMissing),
        budget(2, 2),
    );
    assert!(matches!(
        result,
        Err(PipelineError::MissingPairInteraction(_, _))
    ));
}

#[test]
fn requires_cycle_is_reported_explicitly() {
    let mut graph = relations(UnknownInteractionPolicyV1::MissingAsZero);
    graph.hard_constraints = vec![
        PromptHardConstraintV1::Requires {
            factor_id: id("factor:a"),
            prerequisite_factor_id: id("factor:b"),
            support_reference_digest: digest("a-b"),
        },
        PromptHardConstraintV1::Requires {
            factor_id: id("factor:b"),
            prerequisite_factor_id: id("factor:a"),
            support_reference_digest: digest("b-a"),
        },
    ];
    let result =
        select_portfolio_with_audit(priced(&[("a", 10, 1), ("b", 9, 1)]), graph, budget(2, 2));
    assert!(matches!(result, Err(PipelineError::RequiresCycle(_))));
}

#[test]
fn requires_conflict_contradiction_is_reported_unsatisfiable() {
    let mut graph = relations(UnknownInteractionPolicyV1::MissingAsZero);
    graph.hard_constraints = vec![
        PromptHardConstraintV1::Conflict {
            left_factor_id: id("factor:a"),
            right_factor_id: id("factor:b"),
            support_reference_digest: digest("conflict"),
        },
        PromptHardConstraintV1::Requires {
            factor_id: id("factor:a"),
            prerequisite_factor_id: id("factor:b"),
            support_reference_digest: digest("requires"),
        },
    ];
    let result =
        select_portfolio_with_audit(priced(&[("a", 10, 1), ("b", 1, 1)]), graph, budget(2, 2));
    assert!(matches!(
        result,
        Err(PipelineError::UnsatisfiableConstraintGraph(_))
    ));
}

#[test]
fn portfolio_audit_records_rejection_reason_completeness_confidence_and_support() {
    let pricing = priced(&[("a", 10, 1), ("b", 9, 10)]);
    let Ok(decision) = select_portfolio_with_audit(
        pricing,
        relations(UnknownInteractionPolicyV1::MissingAsZero),
        budget(1, 16),
    ) else {
        panic!("selection");
    };
    let Some(rejected) = decision
        .audit
        .decisions
        .iter()
        .find(|item| item.factor_id == id("factor:b"))
    else {
        panic!("decision for factor:b");
    };
    assert_eq!(
        rejected.disposition,
        PromptPortfolioDispositionV1::OverBudget
    );
    assert_eq!(rejected.confidence_ppm, 900_000);
    assert!(!rejected.causal_support_reference_digest.is_zero());
    assert!(!rejected.cost_support_reference_digest.is_zero());
    assert_eq!(
        decision.audit.registry_completeness_digest,
        digest("registry-complete")
    );
    assert_eq!(decision.audit.omitted_count, 0);
    assert_eq!(decision.audit.model_compatibility_digest, digest("compat"));
    assert!(!decision.authority().grants_any());
}

#[test]
fn exercise_emits_registered_shape_and_drift_is_explicit_in_audit() {
    let Ok(portfolio) = select_portfolio_with_audit(
        priced(&[("a", 10, 1)]),
        relations(UnknownInteractionPolicyV1::MissingAsZero),
        budget(1, 1),
    ) else {
        panic!("portfolio");
    };
    let boundary = RegisteredPromptBoundaryV1 {
        decision_boundary: PromptDecisionBoundaryV1::BeforeFinalResponse,
        boundary_digest: digest("boundary"),
        registry_snapshot_digest: digest("registry"),
        model_profile_digest: digest("model"),
        model_compatibility_digest: digest("compat"),
    };
    let state = PromptExerciseStateV1 {
        state_digest: digest("state"),
        objective_digest: digest("objective"),
        registry_snapshot_digest: digest("registry"),
        model_profile_digest: digest("model"),
        model_compatibility_digest: digest("compat"),
        exercise_now_value_q32: FixedQ32::from_raw(10),
        wait_value_q32: FixedQ32::from_raw(5),
    };
    let Ok(outcome) = exercise_with_audit(portfolio.clone(), boundary.clone(), state) else {
        panic!("exercise");
    };
    assert_eq!(
        outcome.receipt.factor_or_portfolio_id,
        portfolio.receipt.portfolio_id
    );
    assert_eq!(
        outcome.receipt.decision_boundary,
        PromptDecisionBoundaryV1::BeforeFinalResponse
    );
    assert_eq!(outcome.receipt.decision, PromptExerciseActionV1::Exercise);
    assert_eq!(
        outcome.audit.disposition,
        PromptExerciseDispositionV1::Exercise
    );

    let drifted = PromptExerciseStateV1 {
        registry_snapshot_digest: digest("other-registry"),
        ..state
    };
    let Ok(outcome) = exercise_with_audit(portfolio, boundary, drifted) else {
        panic!("drift exercise");
    };
    assert_eq!(outcome.receipt.decision, PromptExerciseActionV1::Wait);
    assert_eq!(
        outcome.audit.disposition,
        PromptExerciseDispositionV1::InvalidatedRegistryDrift
    );
}

#[test]
fn all_four_target_operations_have_registered_contract_outputs() {
    let factors = vec![registry_factor("a")];
    let Ok(enumerated) = enumerate_factors_with_audit(registry(factors), objective(), model())
    else {
        panic!("enumeration");
    };
    let direct_receipt =
        enumerate_factors(registry(vec![registry_factor("a")]), objective(), model());
    assert!(direct_receipt.is_ok());

    let causal = PromptCausalEstimateSetV1 {
        state_digest: digest("state"),
        selection_grammar_digest: digest("grammar"),
        ledger_snapshot_digest: digest("ledger"),
        ledger_owner_digest: digest("ledger-owner"),
        estimates: vec![estimate("a", 50, true)],
    };
    let costs = PromptCostModelV1 {
        state_digest: digest("state"),
        selection_grammar_digest: digest("grammar"),
        cost_model_digest: digest("cost-model"),
        costs: vec![zero_cost("a", 1)],
    };
    let Ok(pricing) = price_factors_with_audit(enumerated, causal, costs) else {
        panic!("pricing");
    };
    assert_eq!(pricing.receipts.len(), 1);
    let Ok(portfolio) = select_portfolio_with_audit(
        pricing,
        relations(UnknownInteractionPolicyV1::MissingAsZero),
        budget(1, 1),
    ) else {
        panic!("portfolio");
    };
    let boundary = RegisteredPromptBoundaryV1 {
        decision_boundary: PromptDecisionBoundaryV1::BeforeFinalResponse,
        boundary_digest: digest("boundary"),
        registry_snapshot_digest: digest("registry"),
        model_profile_digest: digest("model"),
        model_compatibility_digest: digest("compat"),
    };
    let state = PromptExerciseStateV1 {
        state_digest: digest("state"),
        objective_digest: digest("objective"),
        registry_snapshot_digest: digest("registry"),
        model_profile_digest: digest("model"),
        model_compatibility_digest: digest("compat"),
        exercise_now_value_q32: FixedQ32::from_raw(10),
        wait_value_q32: FixedQ32::ZERO,
    };
    let Ok(exercise_receipt) = exercise(portfolio, boundary, state) else {
        panic!("exercise");
    };
    assert_eq!(exercise_receipt.decision, PromptExerciseActionV1::Exercise);
    assert!(!exercise_receipt.authority().grants_any());
}
