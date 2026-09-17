use std::collections::BTreeSet;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn factor(name: &str, token_cost: u64) -> RegisteredPromptFactorV1 {
    RegisteredPromptFactorV1 {
        candidate_id: id(name),
        factor_id: id(&format!("factor:{name}")),
        realization_id: id(&format!("realization:{name}")),
        admitted: true,
        legal: true,
        registry_digest: digest("registry"),
        support_digest: digest(&format!("support:{name}")),
        model_profile_digest: digest("model"),
        token_cost,
    }
}

fn candidate_set(factors: Vec<RegisteredPromptFactorV1>) -> PromptCandidateSetReceiptV1 {
    enumerate_factors(EnumerateFactorsRequestV1 {
        decision_id: id("decision:policy"),
        objective_digest: digest("objective"),
        registry_snapshot_digest: digest("registry"),
        model_profile_digest: digest("model"),
        maximum_candidates: 128,
        factors,
    })
    .expect("candidate enumeration")
}

fn pricing(
    values: &[(&str, i64, u64)],
) -> PromptPricingReceiptV1 {
    let set = candidate_set(
        values
            .iter()
            .map(|(name, _, token_cost)| factor(name, *token_cost))
            .collect(),
    );
    let estimates = values
        .iter()
        .map(|(name, gain, _)| PromptCausalEstimateV1 {
            candidate_id: id(name),
            incremental_recursive_utility: FixedQ32::from_raw(*gain),
            confidence_ppm: 900_000,
            support_digest: digest(&format!("causal:{name}")),
            scope_digest: digest("scope"),
        })
        .collect();
    let costs = values
        .iter()
        .map(|(name, _, _)| PromptCostComponentsV1 {
            candidate_id: id(name),
            token_cost: FixedQ32::ZERO,
            latency_cost: FixedQ32::ZERO,
            interference_cost: FixedQ32::ZERO,
            resource_cost: FixedQ32::ZERO,
        })
        .collect();
    price_factors(PriceFactorsRequestV1 {
        candidate_set: set,
        estimates,
        costs,
    })
    .expect("pricing")
}

fn select(
    prices: PromptPricingReceiptV1,
    budget: u64,
    maximum_selected: usize,
    constraints: Vec<PromptHardConstraintV1>,
    policy: UnknownInteractionPolicyV1,
) -> Result<PromptPortfolioReceiptV1, PolicyError> {
    select_portfolio(SelectPortfolioRequestV1 {
        pricing: prices,
        interactions: Vec::new(),
        hard_constraints: constraints,
        unknown_interaction_policy: policy,
        token_budget: budget,
        maximum_selected,
    })
}

#[test]
fn v1_pipeline_prices_cost_components_and_denies_authority() {
    let set = candidate_set(vec![factor("a", 3)]);
    let receipt = price_factors(PriceFactorsRequestV1 {
        candidate_set: set,
        estimates: vec![PromptCausalEstimateV1 {
            candidate_id: id("a"),
            incremental_recursive_utility: FixedQ32::from_raw(20),
            confidence_ppm: 750_000,
            support_digest: digest("causal:a"),
            scope_digest: digest("scope"),
        }],
        costs: vec![PromptCostComponentsV1 {
            candidate_id: id("a"),
            token_cost: FixedQ32::from_raw(2),
            latency_cost: FixedQ32::from_raw(3),
            interference_cost: FixedQ32::from_raw(4),
            resource_cost: FixedQ32::from_raw(1),
        }],
    })
    .expect("pricing must succeed");

    assert_eq!(receipt.prices[0].net_gain, FixedQ32::from_raw(10));
    assert!(!receipt.authority.grants_any());
}

#[test]
fn density_path_beats_gain_first_counterexample() {
    let portfolio = select(
        pricing(&[("a", 100, 10), ("b", 60, 5), ("c", 60, 5)]),
        10,
        2,
        Vec::new(),
        UnknownInteractionPolicyV1::AssumeZero,
    )
    .expect("portfolio selection");

    assert_eq!(portfolio.selected, vec![id("b"), id("c")]);
    assert_eq!(portfolio.total_net_gain, FixedQ32::from_raw(120));
}

#[test]
fn prerequisite_closure_can_accept_negative_prerequisite() {
    let constraints = vec![PromptHardConstraintV1::Requires {
        candidate: id("dependent"),
        prerequisite: id("prerequisite"),
        support_digest: digest("requires"),
    }];
    let portfolio = select(
        pricing(&[("dependent", 100, 1), ("prerequisite", -1, 1)]),
        2,
        2,
        constraints,
        UnknownInteractionPolicyV1::AssumeZero,
    )
    .expect("package-aware selection");

    assert_eq!(
        portfolio.selected,
        vec![id("dependent"), id("prerequisite")]
    );
    assert_eq!(portfolio.total_net_gain, FixedQ32::from_raw(99));
}

#[test]
fn sparse_interactions_allow_full_128_candidate_multi_select() {
    let values = (0..128)
        .map(|index| (format!("candidate:{index:03}"), 1_i64, 1_u64))
        .collect::<Vec<_>>();
    let factors = values
        .iter()
        .map(|(name, _, cost)| factor(name, *cost))
        .collect();
    let set = candidate_set(factors);
    let estimates = values
        .iter()
        .map(|(name, gain, _)| PromptCausalEstimateV1 {
            candidate_id: id(name),
            incremental_recursive_utility: FixedQ32::from_raw(*gain),
            confidence_ppm: 900_000,
            support_digest: digest(&format!("causal:{name}")),
            scope_digest: digest("scope"),
        })
        .collect();
    let costs = values
        .iter()
        .map(|(name, _, _)| PromptCostComponentsV1 {
            candidate_id: id(name),
            token_cost: FixedQ32::ZERO,
            latency_cost: FixedQ32::ZERO,
            interference_cost: FixedQ32::ZERO,
            resource_cost: FixedQ32::ZERO,
        })
        .collect();
    let priced = price_factors(PriceFactorsRequestV1 {
        candidate_set: set,
        estimates,
        costs,
    })
    .expect("pricing");
    let portfolio = select(
        priced,
        16,
        16,
        Vec::new(),
        UnknownInteractionPolicyV1::AssumeZero,
    )
    .expect("sparse selection");

    assert_eq!(portfolio.selected.len(), 16);
}

#[test]
fn explicit_interaction_policy_fails_closed_when_edge_is_missing() {
    let error = select(
        pricing(&[("a", 2, 1), ("b", 1, 1)]),
        2,
        2,
        Vec::new(),
        UnknownInteractionPolicyV1::RequireExplicit,
    )
    .expect_err("missing edge must fail closed");

    assert_eq!(
        error,
        PolicyError::MissingInteraction("a".to_string(), "b".to_string())
    );
}

#[test]
fn requires_cycle_is_rejected_as_structural_error() {
    let constraints = vec![
        PromptHardConstraintV1::Requires {
            candidate: id("a"),
            prerequisite: id("b"),
            support_digest: digest("a-requires-b"),
        },
        PromptHardConstraintV1::Requires {
            candidate: id("b"),
            prerequisite: id("a"),
            support_digest: digest("b-requires-a"),
        },
    ];
    let error = select(
        pricing(&[("a", 2, 1), ("b", 1, 1)]),
        2,
        2,
        constraints,
        UnknownInteractionPolicyV1::AssumeZero,
    )
    .expect_err("cycle must reject");

    assert_eq!(error, PolicyError::RequiresCycle);
}

#[test]
fn conflicting_prerequisite_closure_is_rejected() {
    let constraints = vec![
        PromptHardConstraintV1::Conflict {
            left: id("a"),
            right: id("b"),
            support_digest: digest("conflict"),
        },
        PromptHardConstraintV1::Requires {
            candidate: id("a"),
            prerequisite: id("b"),
            support_digest: digest("requires"),
        },
    ];
    let error = select(
        pricing(&[("a", 2, 1), ("b", 1, 1)]),
        2,
        2,
        constraints,
        UnknownInteractionPolicyV1::AssumeZero,
    )
    .expect_err("contradiction must reject");

    assert_eq!(error, PolicyError::UnsatisfiableConstraints("a".to_string()));
}

#[test]
fn exercise_revalidates_boundary_registry_and_model_profile() {
    let portfolio = select(
        pricing(&[("a", 2, 1)]),
        1,
        1,
        Vec::new(),
        UnknownInteractionPolicyV1::AssumeZero,
    )
    .expect("portfolio");
    let boundary = id("before-final-response");
    let decision = exercise(ExerciseRequestV1 {
        portfolio,
        registered_boundary: boundary.clone(),
        allowed_boundaries: BTreeSet::from([boundary.clone()]),
        state_digest: digest("state"),
        current_registry_digest: digest("registry"),
        current_model_profile_digest: digest("model"),
    })
    .expect("exercise decision");

    assert_eq!(decision.disposition, PromptExerciseDispositionV1::Exercise);
    assert!(!decision.authority.grants_any());
}
