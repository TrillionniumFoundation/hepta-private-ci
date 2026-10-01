use super::*;
use codex_hepta_kg::KnowledgeProjectionInputV2;
use codex_hepta_kg::build_complete_generation;

#[path = "canonical_temporal_fixture_tests.rs"]
mod fixture;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("fixture ID: {error:?}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn rebuild(graph: KnowledgeGenerationV2) -> KnowledgeGenerationV2 {
    build_complete_generation(
        graph.generation,
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: graph.source_snapshot_digest,
            generation_vector_digest: graph.generation_vector_digest,
            graph_profile_digest: graph.graph_profile_digest,
            complete_source_cut: true,
            nodes: graph.nodes,
            edges: graph.edges,
        },
    )
    .unwrap_or_else(|error| panic!("rebuild temporal generation: {error:?}"))
}

fn select(
    fixture: &fixture::Fixture,
    graph: &KnowledgeGenerationV2,
    pair_evidence: Vec<PromptPairUtilityEvidenceV1>,
    now_unix_ms: u64,
) -> SelectedPromptPortfolioV1 {
    select_portfolio_v1(
        &fixture.priced,
        graph,
        pair_evidence,
        &fixture.verifier,
        PromptPortfolioRequestV1 {
            portfolio_id: id("portfolio:temporal"),
            graph_query_id: id("query:temporal"),
            token_budget: 8,
            maximum_selected_factors: 2,
            requested_valid_until_unix_ms: 8_000,
        },
        now_unix_ms,
    )
    .unwrap_or_else(|error| panic!("actual canonical selection: {error:?}"))
}

fn exercise(
    fixture: &fixture::Fixture,
    portfolio: &SelectedPromptPortfolioV1,
    now_unix_ms: u64,
) -> PromptExerciseDecisionV1 {
    exercise_v1(
        fixture
            .registry
            .registry()
            .unwrap_or_else(|error| panic!("current durable view: {error:?}")),
        portfolio,
        PromptExerciseRequestV1 {
            decision_boundary: PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
            current_state_digest: portfolio.state_digest,
            generation_vector_digest: portfolio.generation_vector_digest,
            model_tuple: portfolio.model_tuple.clone(),
            now_unix_ms,
            wait_value_q32: FixedQ32::ZERO,
            policy_digest: digest("policy:exercise"),
        },
    )
    .unwrap_or_else(|error| panic!("actual exercise: {error:?}"))
}

#[test]
fn future_conflict_caps_portfolio_before_the_edge_becomes_visible() {
    let fixture = fixture::fixture();
    let mut graph = tests::graph(
        &["factor:a", "factor:b"],
        vec![(
            "factor:a",
            KnowledgeRelationKindV2::PromptConflicts,
            "factor:b",
        )],
    );
    graph.edges[0].supports[0].valid_from_unix_seconds = Some(2);
    let graph = rebuild(graph);
    let portfolio = select(&fixture, &graph, Vec::new(), /*now_unix_ms*/ 1_000);
    assert_eq!(
        portfolio.receipt.factor_ids,
        vec![id("factor:a"), id("factor:b")]
    );
    assert_eq!(portfolio.receipt.valid_until_unix_ms, 2_000);
    assert_eq!(
        exercise(&fixture, &portfolio, /*now_unix_ms*/ 1_999).decision,
        PromptExerciseActionV1::Exercise
    );
    assert_eq!(
        exercise(&fixture, &portfolio, /*now_unix_ms*/ 2_000).decision,
        PromptExerciseActionV1::RejectStale
    );
    let after = select(&fixture, &graph, Vec::new(), /*now_unix_ms*/ 2_000);
    assert_eq!(after.receipt.factor_ids, vec![id("factor:a")]);
    assert_eq!(after.receipt.valid_until_unix_ms, 8_000);
}

#[test]
fn expiring_complement_cannot_preserve_its_pair_utility_past_support_expiry() {
    let fixture = fixture::fixture();
    let mut graph = tests::graph(
        &["factor:a", "factor:b"],
        vec![(
            "factor:a",
            KnowledgeRelationKindV2::PromptComplements,
            "factor:b",
        )],
    );
    graph.edges[0].supports[0].valid_to_unix_seconds = Some(2);
    let graph = rebuild(graph);
    let portfolio = select(
        &fixture,
        &graph,
        vec![fixture.pair_evidence(&graph)],
        /*now_unix_ms*/ 1_000,
    );
    assert_eq!(
        portfolio.receipt.expected_utility_q32,
        FixedQ32::ONE
            .checked_add(FixedQ32::ONE)
            .unwrap_or_else(|error| panic!("two: {error:?}"))
            .checked_add(FixedQ32::ONE)
            .unwrap_or_else(|error| panic!("three: {error:?}"))
    );
    assert_eq!(portfolio.receipt.valid_until_unix_ms, 2_000);
    assert_eq!(
        exercise(&fixture, &portfolio, /*now_unix_ms*/ 2_000).decision,
        PromptExerciseActionV1::RejectStale
    );
    let after = select(&fixture, &graph, Vec::new(), /*now_unix_ms*/ 2_000);
    assert_eq!(
        after.receipt.expected_utility_q32,
        FixedQ32::ONE
            .checked_add(FixedQ32::ONE)
            .unwrap_or_else(|error| panic!("two: {error:?}"))
    );
    assert_eq!(after.receipt.valid_until_unix_ms, 8_000);
}

#[test]
fn future_endpoint_visibility_caps_an_absent_conflict() {
    let fixture = fixture::fixture();
    let mut graph = tests::graph(
        &["factor:a", "factor:b"],
        vec![(
            "factor:a",
            KnowledgeRelationKindV2::PromptConflicts,
            "factor:b",
        )],
    );
    graph.nodes[0].supports[0].valid_from_unix_seconds = Some(2);
    let graph = rebuild(graph);
    let portfolio = select(&fixture, &graph, Vec::new(), /*now_unix_ms*/ 1_000);
    assert_eq!(
        portfolio.receipt.factor_ids,
        vec![id("factor:a"), id("factor:b")]
    );
    assert_eq!(portfolio.receipt.valid_until_unix_ms, 2_000);
    assert_eq!(
        exercise(&fixture, &portfolio, /*now_unix_ms*/ 2_000).decision,
        PromptExerciseActionV1::RejectStale
    );
    assert_eq!(
        select(&fixture, &graph, Vec::new(), /*now_unix_ms*/ 2_000)
            .receipt
            .factor_ids,
        vec![id("factor:a")]
    );
}

#[test]
fn expiring_endpoint_caps_the_current_conflict_projection() {
    let fixture = fixture::fixture();
    let mut graph = tests::graph(
        &["factor:a", "factor:b"],
        vec![(
            "factor:a",
            KnowledgeRelationKindV2::PromptConflicts,
            "factor:b",
        )],
    );
    graph.nodes[0].supports[0].valid_to_unix_seconds = Some(2);
    let graph = rebuild(graph);
    let before = select(&fixture, &graph, Vec::new(), /*now_unix_ms*/ 1_000);
    assert_eq!(before.receipt.factor_ids, vec![id("factor:a")]);
    assert_eq!(before.receipt.valid_until_unix_ms, 2_000);
    let after = select(&fixture, &graph, Vec::new(), /*now_unix_ms*/ 2_000);
    assert_eq!(
        after.receipt.factor_ids,
        vec![id("factor:a"), id("factor:b")]
    );
    assert_eq!(after.receipt.valid_until_unix_ms, 8_000);
}

#[test]
fn future_required_factor_outside_candidates_also_limits_the_cut() {
    let fixture = fixture::fixture();
    let mut graph = tests::graph(
        &["factor:a", "factor:b", "factor:missing"],
        vec![(
            "factor:a",
            KnowledgeRelationKindV2::PromptRequires,
            "factor:missing",
        )],
    );
    graph.edges[0].supports[0].valid_from_unix_seconds = Some(2);
    let graph = rebuild(graph);
    let portfolio = select(&fixture, &graph, Vec::new(), /*now_unix_ms*/ 1_000);
    assert_eq!(portfolio.receipt.valid_until_unix_ms, 2_000);
    assert_eq!(
        exercise(&fixture, &portfolio, /*now_unix_ms*/ 2_000).decision,
        PromptExerciseActionV1::RejectStale
    );
}

#[test]
fn unrelated_edges_nodes_and_non_prompt_relations_do_not_shorten_the_portfolio() {
    let fixture = fixture::fixture();
    let mut graph = tests::graph(
        &["factor:a", "factor:b", "factor:c", "factor:d"],
        vec![
            (
                "factor:c",
                KnowledgeRelationKindV2::PromptConflicts,
                "factor:d",
            ),
            ("factor:a", KnowledgeRelationKindV2::Supports, "factor:b"),
        ],
    );
    for edge in &mut graph.edges {
        edge.supports[0].valid_from_unix_seconds = Some(2);
    }
    graph.nodes[2].supports[0].valid_to_unix_seconds = Some(3);
    let portfolio = select(
        &fixture,
        &rebuild(graph),
        Vec::new(),
        /*now_unix_ms*/ 1_000,
    );
    assert_eq!(
        portfolio.receipt.factor_ids,
        vec![id("factor:a"), id("factor:b")]
    );
    assert_eq!(portfolio.receipt.valid_until_unix_ms, 8_000);
}

#[test]
fn second_transitions_have_exact_exclusive_millisecond_boundaries() {
    let fixture = fixture::fixture();
    let mut graph = tests::graph(
        &["factor:a", "factor:b"],
        vec![(
            "factor:a",
            KnowledgeRelationKindV2::PromptConflicts,
            "factor:b",
        )],
    );
    graph.edges[0].supports[0].valid_from_unix_seconds = Some(2);
    graph.edges[0].supports[0].valid_to_unix_seconds = Some(6);
    let graph = rebuild(graph);
    for (now_unix_ms, valid_until_unix_ms, factors) in [
        (1_999, 2_000, vec![id("factor:a"), id("factor:b")]),
        (2_000, 6_000, vec![id("factor:a")]),
        (5_999, 6_000, vec![id("factor:a")]),
        (6_000, 8_000, vec![id("factor:a"), id("factor:b")]),
    ] {
        let portfolio = select(&fixture, &graph, Vec::new(), now_unix_ms);
        assert_eq!(portfolio.receipt.factor_ids, factors);
        assert_eq!(portfolio.receipt.valid_until_unix_ms, valid_until_unix_ms);
        assert_eq!(
            exercise(&fixture, &portfolio, valid_until_unix_ms).decision,
            PromptExerciseActionV1::RejectStale
        );
    }
}

#[test]
fn negative_and_unrepresentable_second_bounds_do_not_wrap_deadlines() {
    let fixture = fixture::fixture();
    for (lower, upper) in [(-2, -1), (i64::MAX - 1, i64::MAX)] {
        let mut graph = tests::graph(
            &["factor:a", "factor:b"],
            vec![(
                "factor:a",
                KnowledgeRelationKindV2::PromptConflicts,
                "factor:b",
            )],
        );
        graph.edges[0].supports[0].valid_from_unix_seconds = Some(lower);
        graph.edges[0].supports[0].valid_to_unix_seconds = Some(upper);
        let portfolio = select(
            &fixture,
            &rebuild(graph),
            Vec::new(),
            /*now_unix_ms*/ 1_000,
        );
        assert_eq!(
            portfolio.receipt.factor_ids,
            vec![id("factor:a"), id("factor:b")]
        );
        assert_eq!(portfolio.receipt.valid_until_unix_ms, 8_000);
    }
}

#[test]
fn future_support_in_an_already_visible_relation_still_bounds_the_query_cut() {
    let fixture = fixture::fixture();
    let mut graph = tests::graph(
        &["factor:a", "factor:b"],
        vec![(
            "factor:a",
            KnowledgeRelationKindV2::PromptConflicts,
            "factor:b",
        )],
    );
    let mut future_support = graph.edges[0].supports[0].clone();
    future_support.source_id = id("support:future");
    future_support.valid_from_unix_seconds = Some(2);
    graph.edges[0].supports.push(future_support);
    let graph = rebuild(graph);
    let before = select(&fixture, &graph, Vec::new(), /*now_unix_ms*/ 1_000);
    let after = select(&fixture, &graph, Vec::new(), /*now_unix_ms*/ 2_000);
    assert_eq!(before.receipt.factor_ids, after.receipt.factor_ids);
    assert_eq!(before.receipt.valid_until_unix_ms, 2_000);
    assert_eq!(after.receipt.valid_until_unix_ms, 8_000);
    assert_ne!(
        before.receipt.interaction_digest,
        after.receipt.interaction_digest
    );
}

#[test]
fn empty_portfolio_obeys_the_same_time_and_scope_currentness_checks() {
    let fixture = fixture::fixture();
    let portfolio = select_portfolio_v1(
        &fixture.priced,
        &tests::graph(&["factor:a", "factor:b"], Vec::new()),
        Vec::new(),
        &fixture.verifier,
        PromptPortfolioRequestV1 {
            portfolio_id: id("portfolio:empty"),
            graph_query_id: id("query:empty"),
            token_budget: 0,
            maximum_selected_factors: 2,
            requested_valid_until_unix_ms: 1_100,
        },
        /*now_unix_ms*/ 1_000,
    )
    .unwrap_or_else(|error| panic!("real signed empty selection: {error:?}"));
    assert!(portfolio.selected.is_empty());
    for (now_unix_ms, expected) in [
        (999, PromptExerciseActionV1::RejectStale),
        (1_000, PromptExerciseActionV1::NoIntervention),
        (1_099, PromptExerciseActionV1::NoIntervention),
        (1_100, PromptExerciseActionV1::RejectStale),
    ] {
        assert_eq!(
            exercise(&fixture, &portfolio, now_unix_ms).decision,
            expected
        );
    }
    let current = PromptExerciseRequestV1 {
        decision_boundary: PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
        current_state_digest: portfolio.state_digest,
        generation_vector_digest: portfolio.generation_vector_digest,
        model_tuple: portfolio.model_tuple.clone(),
        now_unix_ms: 1_000,
        wait_value_q32: FixedQ32::ZERO,
        policy_digest: digest("policy:empty-exercise"),
    };
    let mut wrong_model = current.clone();
    wrong_model.model_tuple.model_version = "another-model-version".to_owned();
    for request in [
        PromptExerciseRequestV1 {
            current_state_digest: digest("other-state"),
            ..current.clone()
        },
        PromptExerciseRequestV1 {
            generation_vector_digest: digest("other-vector"),
            ..current
        },
        wrong_model,
    ] {
        assert_eq!(
            exercise_v1(
                fixture
                    .registry
                    .registry()
                    .unwrap_or_else(|error| panic!("registry: {error:?}")),
                &portfolio,
                request
            )
            .unwrap_or_else(|error| panic!("stale empty proposal: {error:?}"))
            .decision,
            PromptExerciseActionV1::RejectStale
        );
    }
}
