#[test]
fn bounded_solver_improves_the_legacy_greedy_counterexample() {
    let priced = direct_priced(&[(10, 100), (5, 60), (5, 60)]);
    let mut problem = DensePromptProblem::new(&priced, 10, 2)
        .unwrap_or_else(|error| panic!("dense problem: {error}"));
    problem
        .finish_constraints()
        .unwrap_or_else(|error| panic!("constraints: {error}"));
    let outcome =
        solve_prompt_problem(&problem).unwrap_or_else(|error| panic!("solve: {error}"));
    let selected = outcome
        .selected
        .indices(problem.rows.len())
        .collect::<Vec<_>>();
    assert_eq!(selected, vec![1, 2]);
    assert_eq!(
        problem
            .utility(outcome.selected)
            .unwrap_or_else(|error| panic!("utility: {error}")),
        FixedQ32::from_raw(120)
    );
}

#[test]
fn conflicting_prerequisite_closure_is_a_structural_error() {
    let priced = direct_priced(&[(1, 10), (1, 10)]);
    let mut problem = DensePromptProblem::new(&priced, 2, 2)
        .unwrap_or_else(|error| panic!("dense problem: {error}"));
    problem.requires[0].insert(1);
    problem.conflicts[0].insert(1);
    problem.conflicts[1].insert(0);
    assert!(matches!(
        problem.finish_constraints(),
        Err(VerifiedPromptError::UnsatisfiableGraph(_))
    ));
}

#[test]
fn portfolio_receipt_tamper_is_rejected_before_exercise() {
    let priced = direct_priced(&[(1, 10)]);
    let binding = priced.rows[0].binding.clone();
    let interaction_digest = digest("interaction");
    let graph_generation_digest = digest("graph");
    let mut selected = v1::SelectedPromptPortfolioV1 {
        receipt: v1::PromptPortfolioReceiptV1 {
            portfolio_id: id("portfolio:test"),
            candidate_set_digest: priced.candidates.candidates_digest,
            factor_ids: vec![binding.factor_id.clone()],
            interaction_digest,
            expected_utility_q32: FixedQ32::from_raw(10),
            total_token_upper_bound: 1,
            valid_until_unix_ms: 10_000,
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        },
        selected: vec![binding],
        objective_digest: priced.candidates.receipt.objective_digest,
        state_digest: priced.candidates.receipt.state_digest,
        model_tuple: priced.candidates.model_tuple.clone(),
        model_tuple_digest: priced.candidates.model_tuple.digest(),
        generation_vector_digest: priced.candidates.generation_vector_digest,
        pricing_set_digest: priced.pricing_set_digest,
        graph_generation_digest,
        selection_method: PromptSelectionMethodV1::GreedyPrerequisiteBundleV1,
        optimality: PromptOptimalityDisclosureV1::HeuristicNoCertificate,
    };
    let receipt_digest = digest_portfolio_receipt_v2(
        &selected.receipt.portfolio_id,
        selected.receipt.candidate_set_digest,
        &selected.receipt.factor_ids,
        selected.receipt.interaction_digest,
        selected.receipt.expected_utility_q32,
        selected.receipt.total_token_upper_bound,
        selected.receipt.valid_until_unix_ms,
        selected.pricing_set_digest,
        selected.graph_generation_digest,
    );
    selected.receipt.receipt_digest = receipt_digest;
    validate_selected_shape(&selected)
        .unwrap_or_else(|error| panic!("valid selected portfolio: {error}"));
    selected.receipt.expected_utility_q32 = FixedQ32::from_raw(999);
    assert_eq!(
        validate_selected_shape(&selected),
        Err(VerifiedPromptError::ReceiptDigest("portfolio receipt"))
    );
}
