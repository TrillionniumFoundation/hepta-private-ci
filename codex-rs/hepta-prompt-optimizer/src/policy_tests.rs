use std::collections::BTreeSet;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn factor(name: &str, token_cost: u32) -> RegisteredPromptFactorV1 {
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

fn candidate_set_audit(
    factors: Vec<RegisteredPromptFactorV1>,
    maximum_candidates: usize,
) -> PromptCandidateSetAuditV1 {
    enumerate_factors_with_audit(EnumerateFactorsRequestV1 {
        set_id: id("set:policy"),
        objective_digest: digest("objective"),
        state_digest: digest("state"),
        registry_digest: digest("registry"),
        model_profile_digest: digest("model"),
        selection_grammar_digest: digest("grammar"),
        maximum_candidates,
        factors,
    })
    .expect("candidate enumeration")
}

fn pricing_audit(values: &[(&str, i64, u32)]) -> PromptPricingSetAuditV1 {
    let set = candidate_set_audit(
        values
            .iter()
            .map(|(name, _, token_cost)| factor(name, *token_cost))
            .collect(),
        128,
    );
    let estimates = values
        .iter()
        .map(|(name, gain, _)| PromptCausalEstimateV1 {
            candidate_id: id(name),
            expected_utility_q32: FixedQ32::from_raw(*gain),
            confidence_interval: PromptConfidenceIntervalV1 {
                lower_q32: FixedQ32::from_raw(gain.saturating_sub(1)),
                upper_q32: FixedQ32::from_raw(gain.saturating_add(1)),
                confidence_ppm: 900_000,
            },
            support_digest: digest(&format!("causal:{name}")),
            scope_digest: digest("scope"),
        })
        .collect();
    let costs = values
        .iter()
        .map(|(name, _, token_cost)| PromptCostComponentsV1 {
            candidate_id: id(name),
            downside_q32: FixedQ32::ZERO,
            token_cost: *token_cost,
            latency_cost_micros: 0,
            interference_ppm: 0,
            token_penalty_q32: FixedQ32::ZERO,
            latency_penalty_q32: FixedQ32::ZERO,
            interference_penalty_q32: FixedQ32::ZERO,
            resource_penalty_q32: FixedQ32::ZERO,
        })
        .collect();
    price_factors_with_audit(PriceFactorsRequestV1 {
        candidate_set: set,
        estimates,
        costs,
    })
    .expect("pricing")
}

fn select_audit(
    pricing: PromptPricingSetAuditV1,
    budget: u64,
    maximum_selected: usize,
    constraints: Vec<PromptHardConstraintV1>,
    policy: UnknownInteractionPolicyV1,
) -> Result<PromptPortfolioAuditV1, PolicyError> {
    select_portfolio_with_audit(SelectPortfolioRequestV1 {
        portfolio_id: id("portfolio:policy"),
        pricing,
        interactions: Vec::new(),
        hard_constraints: constraints,
        unknown_interaction_policy: policy,
        token_budget: budget,
        maximum_selected,
        valid_until_unix_ms: 1,
    })
}

#[test]
fn canonical_v1_shapes_are_emitted_with_audit_lineage() {
    let set = candidate_set_audit(vec![factor("a", 3)], 128);
    assert_eq!(set.receipt.set_id, id("set:policy"));
    assert_eq!(set.receipt.candidate_factor_ids, vec![id("factor:a")]);
    assert!(set.complete);
    assert!(!set.authority.grants_any());

    let registered_prices = price_factors(PriceFactorsRequestV1 {
        candidate_set: set,
        estimates: vec![PromptCausalEstimateV1 {
            candidate_id: id("a"),
            expected_utility_q32: FixedQ32::from_raw(20),
            confidence_interval: PromptConfidenceIntervalV1 {
                lower_q32: FixedQ32::from_raw(18),
                upper_q32: FixedQ32::from_raw(22),
                confidence_ppm: 750_000,
            },
            support_digest: digest("causal:a"),
            scope_digest: digest("scope"),
        }],
        costs: vec![PromptCostComponentsV1 {
            candidate_id: id("a"),
            downside_q32: FixedQ32::from_raw(1),
            token_cost: 3,
            latency_cost_micros: 7,
            interference_ppm: 11,
            token_penalty_q32: FixedQ32::from_raw(2),
            latency_penalty_q32: FixedQ32::from_raw(3),
            interference_penalty_q32: FixedQ32::from_raw(4),
            resource_penalty_q32: FixedQ32::from_raw(1),
        }],
    })
    .expect("registered pricing");
    assert_eq!(registered_prices.len(), 1);
    assert_eq!(registered_prices[0].factor_id, id("factor:a"));
    assert_eq!(registered_prices[0].token_cost, 3);
}

#[test]
fn pricing_decomposition_and_portfolio_heuristics_close_known_gaps() {
    let set = candidate_set_audit(vec![factor("priced", 3)], 128);
    let priced = price_factors_with_audit(PriceFactorsRequestV1 {
        candidate_set: set,
        estimates: vec![PromptCausalEstimateV1 {
            candidate_id: id("priced"),
            expected_utility_q32: FixedQ32::from_raw(20),
            confidence_interval: PromptConfidenceIntervalV1 {
                lower_q32: FixedQ32::from_raw(18),
                upper_q32: FixedQ32::from_raw(22),
                confidence_ppm: 750_000,
            },
            support_digest: digest("causal:priced"),
            scope_digest: digest("scope"),
        }],
        costs: vec![PromptCostComponentsV1 {
            candidate_id: id("priced"),
            downside_q32: FixedQ32::from_raw(1),
            token_cost: 3,
            latency_cost_micros: 7,
            interference_ppm: 11,
            token_penalty_q32: FixedQ32::from_raw(2),
            latency_penalty_q32: FixedQ32::from_raw(3),
            interference_penalty_q32: FixedQ32::from_raw(4),
            resource_penalty_q32: FixedQ32::from_raw(1),
        }],
    })
    .expect("pricing");
    assert_eq!(priced.prices[0].net_gain_q32, FixedQ32::from_raw(9));
    assert!(!priced.authority.grants_any());

    let portfolio = select_audit(
        pricing_audit(&[("a", 100, 10), ("b", 60, 5), ("c", 60, 5)]),
        10,
        2,
        Vec::new(),
        UnknownInteractionPolicyV1::AssumeZero,
    )
    .expect("portfolio selection");
    assert_eq!(portfolio.selected_candidate_ids, vec![id("b"), id("c")]);
    assert_eq!(portfolio.receipt.factor_ids, vec![id("factor:b"), id("factor:c")]);
    assert_eq!(portfolio.receipt.expected_utility_q32, FixedQ32::from_raw(120));
}

#[test]
fn prerequisite_closure_accepts_positive_bundle_and_rejects_invalid_graphs() {
    let requires = vec![PromptHardConstraintV1::Requires {
        candidate: id("dependent"),
        prerequisite: id("prerequisite"),
        support_digest: digest("requires"),
    }];
    let portfolio = select_audit(
        pricing_audit(&[("dependent", 100, 1), ("prerequisite", -1, 1)]),
        2,
        2,
        requires,
        UnknownInteractionPolicyV1::AssumeZero,
    )
    .expect("package-aware selection");
    assert_eq!(
        portfolio.selected_candidate_ids,
        vec![id("dependent"), id("prerequisite")]
    );
    assert_eq!(portfolio.receipt.expected_utility_q32, FixedQ32::from_raw(99));

    let cycle = vec![
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
    assert_eq!(
        select_audit(
            pricing_audit(&[("a", 2, 1), ("b", 1, 1)]),
            2,
            2,
            cycle,
            UnknownInteractionPolicyV1::AssumeZero,
        ),
        Err(PolicyError::RequiresCycle)
    );

    let contradiction = vec![
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
    assert_eq!(
        select_audit(
            pricing_audit(&[("a", 2, 1), ("b", 1, 1)]),
            2,
            2,
            contradiction,
            UnknownInteractionPolicyV1::AssumeZero,
        ),
        Err(PolicyError::UnsatisfiableConstraints("a".to_string()))
    );
}

#[test]
fn sparse_policy_supports_128_candidates_and_explicit_policy_fails_closed() {
    let values = (0..128)
        .map(|index| (format!("candidate:{index:03}"), 1_i64, 1_u32))
        .collect::<Vec<_>>();
    let set = candidate_set_audit(
        values
            .iter()
            .map(|(name, _, cost)| factor(name, *cost))
            .collect(),
        128,
    );
    let estimates = values
        .iter()
        .map(|(name, gain, _)| PromptCausalEstimateV1 {
            candidate_id: id(name),
            expected_utility_q32: FixedQ32::from_raw(*gain),
            confidence_interval: PromptConfidenceIntervalV1 {
                lower_q32: FixedQ32::ZERO,
                upper_q32: FixedQ32::from_raw(2),
                confidence_ppm: 900_000,
            },
            support_digest: digest(&format!("causal:{name}")),
            scope_digest: digest("scope"),
        })
        .collect();
    let costs = values
        .iter()
        .map(|(name, _, cost)| PromptCostComponentsV1 {
            candidate_id: id(name),
            downside_q32: FixedQ32::ZERO,
            token_cost: *cost,
            latency_cost_micros: 0,
            interference_ppm: 0,
            token_penalty_q32: FixedQ32::ZERO,
            latency_penalty_q32: FixedQ32::ZERO,
            interference_penalty_q32: FixedQ32::ZERO,
            resource_penalty_q32: FixedQ32::ZERO,
        })
        .collect();
    let priced = price_factors_with_audit(PriceFactorsRequestV1 {
        candidate_set: set,
        estimates,
        costs,
    })
    .expect("pricing");
    let portfolio = select_audit(
        priced,
        16,
        16,
        Vec::new(),
        UnknownInteractionPolicyV1::AssumeZero,
    )
    .expect("sparse selection");
    assert_eq!(portfolio.selected_candidate_ids.len(), 16);

    assert_eq!(
        select_audit(
            pricing_audit(&[("a", 2, 1), ("b", 1, 1)]),
            2,
            2,
            Vec::new(),
            UnknownInteractionPolicyV1::RequireExplicit,
        ),
        Err(PolicyError::MissingInteraction("a".to_string(), "b".to_string()))
    );
}

#[test]
fn completeness_audit_and_exercise_drift_remain_visible() {
    let truncated = candidate_set_audit(
        vec![factor("a", 1), factor("b", 1), factor("c", 1)],
        2,
    );
    assert_eq!(truncated.omitted_count, 1);
    assert!(!truncated.complete);

    let priced = price_factors_with_audit(PriceFactorsRequestV1 {
        estimates: truncated
            .candidates
            .iter()
            .map(|candidate| PromptCausalEstimateV1 {
                candidate_id: candidate.candidate_id.clone(),
                expected_utility_q32: FixedQ32::from_raw(2),
                confidence_interval: PromptConfidenceIntervalV1 {
                    lower_q32: FixedQ32::from_raw(1),
                    upper_q32: FixedQ32::from_raw(3),
                    confidence_ppm: 900_000,
                },
                support_digest: digest("causal"),
                scope_digest: digest("scope"),
            })
            .collect(),
        costs: truncated
            .candidates
            .iter()
            .map(|candidate| PromptCostComponentsV1 {
                candidate_id: candidate.candidate_id.clone(),
                downside_q32: FixedQ32::ZERO,
                token_cost: candidate.token_cost,
                latency_cost_micros: 0,
                interference_ppm: 0,
                token_penalty_q32: FixedQ32::ZERO,
                latency_penalty_q32: FixedQ32::ZERO,
                interference_penalty_q32: FixedQ32::ZERO,
                resource_penalty_q32: FixedQ32::ZERO,
            })
            .collect(),
        candidate_set: truncated,
    })
    .expect("pricing");
    let portfolio = select_audit(
        priced,
        2,
        2,
        Vec::new(),
        UnknownInteractionPolicyV1::AssumeZero,
    )
    .expect("portfolio");
    assert_eq!(portfolio.omitted_count, 1);
    assert!(!portfolio.candidate_set_complete);
    assert_eq!(portfolio.candidate_audit.len(), 2);
    assert_eq!(
        portfolio.optimality,
        PromptOptimalityV1::HeuristicBestOfGainAndDensityNoCertificate
    );

    let allowed = BTreeSet::from([PromptDecisionBoundaryV1::BeforeFinalResponse]);
    let exercised = exercise_with_audit(ExerciseRequestV1 {
        portfolio: portfolio.clone(),
        decision_boundary: PromptDecisionBoundaryV1::BeforeFinalResponse,
        allowed_boundaries: allowed.clone(),
        state_digest: digest("state:exercise"),
        current_registry_digest: digest("registry"),
        current_model_profile_digest: digest("model"),
        wait_value_q32: FixedQ32::ZERO,
    })
    .expect("exercise");
    assert_eq!(exercised.disposition, PromptExerciseDispositionV1::Exercise);
    assert_eq!(exercised.receipt.decision, PromptExerciseActionV1::Exercise);
    assert!(!exercised.authority.grants_any());

    let drifted = exercise_with_audit(ExerciseRequestV1 {
        portfolio,
        decision_boundary: PromptDecisionBoundaryV1::BeforeFinalResponse,
        allowed_boundaries: allowed,
        state_digest: digest("state:exercise"),
        current_registry_digest: digest("other-registry"),
        current_model_profile_digest: digest("model"),
        wait_value_q32: FixedQ32::ZERO,
    })
    .expect("drift decision");
    assert_eq!(
        drifted.disposition,
        PromptExerciseDispositionV1::RejectRegistryDrift
    );
    assert_eq!(drifted.receipt.decision, PromptExerciseActionV1::Wait);
}
