use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test id must be valid");
    };
    value
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn registered_candidate(name: &str, token_cost: u32) -> RegisteredPromptCandidateV1 {
    RegisteredPromptCandidateV1 {
        candidate_id: id(&format!("candidate:{name}")),
        factor_id: id(&format!("factor:{name}")),
        realization_id: id(&format!("realization:{name}")),
        registry_digest: digest("registry"),
        model_tuple_digest: digest("model-tuple"),
        support_digest: digest(&format!("support:{name}")),
        token_cost_upper_bound: token_cost,
        valid_until_unix_ms: Some(10_000),
        admitted: true,
        legal: true,
    }
}

fn snapshot(candidates: Vec<RegisteredPromptCandidateV1>) -> PromptRegistrySnapshotInputV1 {
    let mut snapshot = PromptRegistrySnapshotInputV1 {
        registry_digest: digest("registry"),
        snapshot_digest: Digest32::ZERO,
        model_tuple_digest: digest("model-tuple"),
        candidates,
        omitted_count: 0,
    };
    snapshot.snapshot_digest = snapshot.compute_snapshot_digest();
    snapshot
}

fn enumerate(snapshot: PromptRegistrySnapshotInputV1) -> PromptCandidateSetDecisionV1 {
    let Ok(value) = enumerate_factors_audited(CandidateEnumerationInputV1 {
        set_id: id("candidate-set:1"),
        objective_digest: digest("objective"),
        state_digest: digest("state"),
        selection_grammar_digest: digest("grammar"),
        now_unix_ms: 100,
        registry_snapshot: snapshot,
    }) else {
        panic!("enumeration must succeed");
    };
    value
}

fn pricing_for(
    candidate_set: &PromptCandidateSetDecisionV1,
    values: &[(&str, i64, u32)],
) -> PromptPricingDecisionV1 {
    let mut receipts = Vec::new();
    let mut audits = Vec::new();
    for (name, utility, token_cost) in values {
        let factor_id = id(&format!("factor:{name}"));
        let receipt = PromptPricingReceiptV1 {
            factor_id: factor_id.clone(),
            state_digest: candidate_set.receipt.state_digest,
            expected_utility_q32: *utility,
            downside_q32: 0,
            token_cost: *token_cost,
            latency_cost_micros: 0,
            interference_ppm: 0,
            confidence_interval: PromptConfidenceIntervalV1 {
                lower_q32: *utility,
                upper_q32: *utility,
                confidence_ppm: PPM_SCALE,
                support_digest: digest(&format!("causal:{name}")),
                scope_digest: digest(&format!("scope:{name}")),
            },
        };
        audits.push(PromptPricingAuditV1 {
            factor_id: factor_id.clone(),
            realization_id: id(&format!("realization:{name}")),
            disposition: PricingDispositionV1::Priced,
            gross_utility_q32: Some(*utility),
            token_shadow_cost_q32: Some(0),
            latency_shadow_cost_q32: Some(0),
            interference_shadow_cost_q32: Some(0),
            resource_shadow_cost_q32: Some(0),
            causal_support_digest: Some(digest(&format!("causal:{name}"))),
            cost_support_digest: Some(digest(&format!("cost:{name}"))),
            model_tuple_digest: digest("model-tuple"),
            realization_support_digest: digest(&format!("support:{name}")),
            valid_until_unix_ms: Some(10_000),
        });
        receipts.push(receipt);
    }
    receipts.sort_by(|left, right| left.factor_id.cmp(&right.factor_id));
    audits.sort_by(|left, right| left.factor_id.cmp(&right.factor_id));
    let candidate_set_digest = candidate_set.receipt.digest();
    let pricing_digest = digest_pricing(candidate_set_digest, &receipts, &audits);
    PromptPricingDecisionV1 {
        candidate_set_digest,
        receipts,
        audits,
        pricing_digest,
    }
}

fn selection_input(
    candidate_set: PromptCandidateSetDecisionV1,
    pricing: PromptPricingDecisionV1,
    budget: u64,
    maximum_selected: usize,
) -> PortfolioSelectionInputV1 {
    PortfolioSelectionInputV1 {
        portfolio_id: id("portfolio:1"),
        candidate_set,
        pricing,
        interactions: Vec::new(),
        hard_constraints: Vec::new(),
        missing_interaction_policy: MissingInteractionPolicyV1::SupportedZero(digest(
            "independence-support",
        )),
        token_budget: budget,
        maximum_selected_factors: maximum_selected,
        valid_until_unix_ms: 9_000,
    }
}

#[test]
fn candidate_enumeration_emits_registered_v1_contract_and_rejects_truncation() {
    let decision = enumerate(snapshot(vec![
        registered_candidate("b", 4),
        registered_candidate("a", 3),
    ]));
    assert_eq!(
        decision.receipt.candidate_factor_ids,
        vec![id("factor:a"), id("factor:b")]
    );
    assert_eq!(decision.audit.enumerated_count, 2);
    assert_eq!(decision.audit.enumerated_at_unix_ms, 100);
    assert!(decision.audit.complete);
    assert!(!decision.authority().grants_any());
    assert!(!decision.receipt.digest().is_zero());

    let mut truncated = snapshot(vec![registered_candidate("a", 3)]);
    truncated.omitted_count = 1;
    truncated.snapshot_digest = truncated.compute_snapshot_digest();
    assert_eq!(
        enumerate_factors_audited(CandidateEnumerationInputV1 {
            set_id: id("candidate-set:2"),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            selection_grammar_digest: digest("grammar"),
            now_unix_ms: 100,
            registry_snapshot: truncated,
        }),
        Err(PolicyError::CandidateSetIncomplete(1))
    );
}

#[test]
fn pricing_subtracts_all_registered_cost_components_and_marks_missing_evidence_unavailable() {
    let registry = snapshot(vec![
        registered_candidate("a", 5),
        registered_candidate("b", 5),
    ]);
    let candidate_set = enumerate(registry.clone());
    let Ok(decision) = price_factors_audited(PricingInputV1 {
        candidate_set,
        registry_snapshot: registry,
        causal_estimates: vec![CausalUtilityEstimateV1 {
            factor_id: id("factor:a"),
            state_digest: digest("state"),
            gross_utility: FixedQ32::from_raw(100),
            downside: FixedQ32::from_raw(7),
            confidence_lower: FixedQ32::from_raw(70),
            confidence_upper: FixedQ32::from_raw(120),
            confidence_ppm: 900_000,
            support_digest: digest("causal-a"),
            scope_digest: digest("scope-a"),
        }],
        cost_estimates: vec![
            PromptCostEstimateV1 {
                factor_id: id("factor:a"),
                token_shadow_cost: FixedQ32::from_raw(10),
                latency_cost_micros: 25,
                latency_shadow_cost: FixedQ32::from_raw(5),
                interference_ppm: 10_000,
                interference_shadow_cost: FixedQ32::from_raw(3),
                resource_shadow_cost: FixedQ32::from_raw(2),
                support_digest: digest("cost-a"),
            },
            PromptCostEstimateV1 {
                factor_id: id("factor:b"),
                token_shadow_cost: FixedQ32::ZERO,
                latency_cost_micros: 0,
                latency_shadow_cost: FixedQ32::ZERO,
                interference_ppm: 0,
                interference_shadow_cost: FixedQ32::ZERO,
                resource_shadow_cost: FixedQ32::ZERO,
                support_digest: digest("cost-b"),
            },
        ],
    }) else {
        panic!("pricing must succeed");
    };
    assert_eq!(decision.receipts.len(), 1);
    let receipt = &decision.receipts[0];
    assert_eq!(receipt.factor_id, id("factor:a"));
    assert_eq!(receipt.expected_utility_q32, 80);
    assert_eq!(receipt.downside_q32, 7);
    assert_eq!(receipt.token_cost, 5);
    assert_eq!(receipt.confidence_interval.lower_q32, 50);
    assert_eq!(receipt.confidence_interval.upper_q32, 100);
    assert_eq!(
        decision
            .audits
            .iter()
            .find(|audit| audit.factor_id == id("factor:b"))
            .map(|audit| audit.disposition),
        Some(PricingDispositionV1::MissingCausalEstimate)
    );
}

#[test]
fn portfolio_selector_escapes_the_legacy_highest_gain_knapsack_trap() {
    let candidate_set = enumerate(snapshot(vec![
        registered_candidate("a", 10),
        registered_candidate("b", 5),
        registered_candidate("c", 5),
    ]));
    let pricing = pricing_for(
        &candidate_set,
        &[("a", 100, 10), ("b", 60, 5), ("c", 60, 5)],
    );
    let Ok(decision) = select_portfolio_audited(selection_input(candidate_set, pricing, 10, 2))
    else {
        panic!("selection must succeed");
    };
    assert_eq!(
        decision.receipt.factor_ids,
        vec![id("factor:b"), id("factor:c")]
    );
    assert_eq!(decision.receipt.expected_utility_q32, 120);
    assert_eq!(
        decision.audit.selection_method,
        PortfolioSelectionMethodV1::GreedyClosureDropOneV1
    );
    assert_eq!(
        decision.audit.optimality,
        PortfolioOptimalityV1::HeuristicNoCertificate
    );
}

#[test]
fn prerequisite_closure_can_select_a_negative_prerequisite_when_the_bundle_is_positive() {
    let candidate_set = enumerate(snapshot(vec![
        registered_candidate("dependent", 1),
        registered_candidate("prerequisite", 1),
    ]));
    let pricing = pricing_for(
        &candidate_set,
        &[("dependent", 100, 1), ("prerequisite", -1, 1)],
    );
    let mut input = selection_input(candidate_set, pricing, 2, 2);
    input.hard_constraints.push(PromptHardConstraintV1::Requires {
        factor_id: id("factor:dependent"),
        prerequisite_factor_id: id("factor:prerequisite"),
        support_digest: digest("requires"),
    });
    let Ok(decision) = select_portfolio_audited(input) else {
        panic!("selection must succeed");
    };
    assert_eq!(decision.receipt.factor_ids.len(), 2);
    assert!(decision.receipt.factor_ids.contains(&id("factor:dependent")));
    assert!(
        decision
            .receipt
            .factor_ids
            .contains(&id("factor:prerequisite"))
    );
    assert_eq!(decision.receipt.expected_utility_q32, 99);
}

#[test]
fn sparse_supported_zero_policy_allows_128_factor_multi_select_without_complete_graph() {
    let candidates = (0..MAX_POLICY_FACTORS)
        .map(|index| registered_candidate(&format!("{index:03}"), 1))
        .collect::<Vec<_>>();
    let candidate_set = enumerate(snapshot(candidates));
    let values = (0..MAX_POLICY_FACTORS)
        .map(|index| (format!("{index:03}"), 1_i64, 1_u32))
        .collect::<Vec<_>>();
    let tuple_values = values
        .iter()
        .map(|(name, utility, cost)| (name.as_str(), *utility, *cost))
        .collect::<Vec<_>>();
    let pricing = pricing_for(&candidate_set, &tuple_values);
    let Ok(decision) = select_portfolio_audited(selection_input(
        candidate_set,
        pricing,
        16,
        MAX_POLICY_SELECTED_FACTORS,
    )) else {
        panic!("128-factor sparse selection must succeed");
    };
    assert_eq!(decision.receipt.factor_ids.len(), MAX_POLICY_SELECTED_FACTORS);
    assert_eq!(decision.receipt.total_token_upper_bound, 16);
}

#[test]
fn requires_cycles_and_requirement_conflicts_are_reported_explicitly() {
    let candidate_set = enumerate(snapshot(vec![
        registered_candidate("a", 1),
        registered_candidate("b", 1),
    ]));
    let pricing = pricing_for(&candidate_set, &[("a", 10, 1), ("b", 9, 1)]);
    let mut cycle = selection_input(candidate_set.clone(), pricing.clone(), 2, 2);
    cycle.hard_constraints = vec![
        PromptHardConstraintV1::Requires {
            factor_id: id("factor:a"),
            prerequisite_factor_id: id("factor:b"),
            support_digest: digest("a-requires-b"),
        },
        PromptHardConstraintV1::Requires {
            factor_id: id("factor:b"),
            prerequisite_factor_id: id("factor:a"),
            support_digest: digest("b-requires-a"),
        },
    ];
    assert!(matches!(
        select_portfolio_audited(cycle),
        Err(PolicyError::RequiresCycle(_))
    ));

    let mut contradiction = selection_input(candidate_set, pricing, 2, 2);
    contradiction.hard_constraints = vec![
        PromptHardConstraintV1::Conflict {
            left_factor_id: id("factor:a"),
            right_factor_id: id("factor:b"),
            support_digest: digest("conflict"),
        },
        PromptHardConstraintV1::Requires {
            factor_id: id("factor:a"),
            prerequisite_factor_id: id("factor:b"),
            support_digest: digest("requires"),
        },
    ];
    assert!(matches!(
        select_portfolio_audited(contradiction),
        Err(PolicyError::UnsatisfiableRequirementConflict(_))
    ));
}

#[test]
fn reject_unknown_sparse_interactions_produces_auditable_nonselection_reason() {
    let candidate_set = enumerate(snapshot(vec![
        registered_candidate("a", 1),
        registered_candidate("b", 1),
    ]));
    let pricing = pricing_for(&candidate_set, &[("a", 10, 1), ("b", 9, 1)]);
    let mut input = selection_input(candidate_set, pricing, 2, 2);
    input.missing_interaction_policy = MissingInteractionPolicyV1::RejectUnknown;
    let Ok(decision) = select_portfolio_audited(input) else {
        panic!("selection must succeed with one supported singleton");
    };
    assert_eq!(decision.receipt.factor_ids, vec![id("factor:a")]);
    assert_eq!(
        decision
            .audit
            .candidates
            .iter()
            .find(|audit| audit.factor_id == id("factor:b"))
            .map(|audit| audit.disposition),
        Some(PortfolioCandidateDispositionV1::MissingInteractionEvidence)
    );
}

#[test]
fn exercise_binds_state_registry_model_and_registered_boundary() {
    let candidate_set = enumerate(snapshot(vec![registered_candidate("a", 1)]));
    let pricing = pricing_for(&candidate_set, &[("a", 10, 1)]);
    let Ok(portfolio) = select_portfolio_audited(selection_input(candidate_set, pricing, 1, 1))
    else {
        panic!("portfolio selection must succeed");
    };
    let Ok(decision) = exercise(ExerciseInputV1 {
        portfolio: portfolio.clone(),
        decision_boundary: PromptDecisionBoundaryV1::BeforeFinalResponse,
        now_unix_ms: 100,
        state_digest: digest("state"),
        registry_digest: digest("registry"),
        registry_snapshot_digest: portfolio.audit.registry_snapshot_digest,
        model_tuple_digest: digest("model-tuple"),
        exercise_now_value: FixedQ32::from_raw(10),
        wait_value: FixedQ32::from_raw(5),
        policy_digest: digest("exercise-policy"),
    }) else {
        panic!("exercise must succeed");
    };
    assert_eq!(decision.decision, PromptExerciseDispositionV1::Exercise);
    assert_eq!(
        decision.decision_boundary,
        PromptDecisionBoundaryV1::BeforeFinalResponse
    );
    assert!(!decision.authority().grants_any());

    assert_eq!(
        exercise(ExerciseInputV1 {
            portfolio: portfolio.clone(),
            decision_boundary: PromptDecisionBoundaryV1::BeforeFinalResponse,
            now_unix_ms: 100,
            state_digest: digest("state"),
            registry_digest: digest("registry"),
            registry_snapshot_digest: portfolio.audit.registry_snapshot_digest,
            model_tuple_digest: digest("different-model"),
            exercise_now_value: FixedQ32::from_raw(10),
            wait_value: FixedQ32::from_raw(5),
            policy_digest: digest("exercise-policy"),
        }),
        Err(PolicyError::IntegrityMismatch("exercise model tuple"))
    );
}
