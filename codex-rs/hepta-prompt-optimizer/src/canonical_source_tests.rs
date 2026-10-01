use super::*;
use codex_hepta_kg::build_prompt_factor_projection_v1;

fn registered_relation_fixture(
    directory: &std::path::Path,
    kind: PromptFactorRelationKind,
) -> DurablePromptRegistry {
    let (mut registry, _tuple, authority, signing_key, now) = registry_fixture(directory, &[1]);
    register_second_factor(&mut registry, &authority, &signing_key, now);
    registry
        .register_factor_relation(PromptFactorRelation {
            relation_id: id("relation:a:b:registered"),
            left_factor_id: id("factor:a"),
            right_factor_id: id("factor:b"),
            kind,
            evidence_digest: digest("registered relation evidence"),
        })
        .expect("register owner relation before freezing candidates");
    registry
}

fn owner_graph(registry: &DurablePromptRegistry) -> KnowledgeGenerationV2 {
    let source = registry
        .registry()
        .expect("registry")
        .factor_graph_source_v1();
    build_prompt_factor_projection_v1(
        Generation::new(1).expect("generation"),
        digest("generation-vector"),
        &source,
    )
    .expect("complete sealed owner projection")
    .generation()
    .clone()
}

fn selection_request() -> PromptPortfolioRequestV1 {
    PromptPortfolioRequestV1 {
        portfolio_id: id("portfolio:owner-source"),
        graph_query_id: id("query:owner-source"),
        token_budget: 2,
        maximum_selected_factors: 2,
        requested_valid_until_unix_ms: 5_000,
    }
}

fn rebuild_graph(graph: KnowledgeGenerationV2) -> KnowledgeGenerationV2 {
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
    .expect("internally valid caller-built complete graph")
}

#[test]
fn registered_owner_conflict_cannot_be_omitted_or_clock_masked_from_selection() {
    let temp = tempfile::tempdir().expect("tempdir");
    let registry = registered_relation_fixture(
        &temp.path().join("registry"),
        PromptFactorRelationKind::Conflicts,
    );
    let (priced, verifier) = temporal::authentic_temporal_prices(&registry);
    let baseline = owner_graph(&registry);
    let selected = select_portfolio_v1(
        &priced,
        &baseline,
        Vec::new(),
        &verifier,
        selection_request(),
        100,
    )
    .expect("authentic owner projection selects a legal portfolio");
    assert_eq!(selected.receipt.factor_ids, vec![id("factor:a")]);
    assert_eq!(
        exercise_v1(
            registry.registry().expect("registry"),
            &selected,
            exercise_request_for(&selected),
        )
        .expect("legal owner-bound portfolio is exercisable")
        .decision,
        PromptExerciseActionV1::Exercise
    );
    for tamper in [
        "omit",
        "supplemental-omit",
        "relation",
        "edge-clock",
        "node-clock",
    ] {
        let mut graph = baseline.clone();
        match tamper {
            "omit" => graph.edges.clear(),
            "supplemental-omit" => {
                graph.edges.clear();
                graph.source_snapshot_digest = digest("supplemental source");
                graph.graph_profile_digest = digest("supplemental profile");
            }
            "relation" => graph.edges[0].identity.relation = KnowledgeRelationKindV2::Causes,
            "edge-clock" => graph.edges[0].supports[0].valid_from_unix_seconds = Some(1),
            "node-clock" => graph.nodes[1].supports[0].valid_from_unix_seconds = Some(1),
            _ => unreachable!(),
        }
        let graph = rebuild_graph(graph);
        let result = select_portfolio_v1(
            &priced,
            &graph,
            Vec::new(),
            &verifier,
            selection_request(),
            100,
        );
        assert!(
            matches!(result, Err(CanonicalPromptError::KnowledgeGraph(_))),
            "registered owner constraint tampering must be rejected: {tamper}: {result:?}"
        );
    }
}

#[test]
fn exercise_rejects_registered_conflict_in_fresh_recomputed_portfolio() {
    let temp = tempfile::tempdir().expect("tempdir");
    let registry = registered_relation_fixture(
        &temp.path().join("registry"),
        PromptFactorRelationKind::Conflicts,
    );
    let selected = selected_portfolio(&registry, vec![id("factor:a"), id("factor:b")]);
    assert_eq!(
        selected.receipt.receipt_digest,
        selected.compute_receipt_digest()
    );
    assert_eq!(
        exercise_v1(
            registry.registry().expect("registry"),
            &selected,
            exercise_request_for(&selected),
        )
        .expect("owner conflict decision")
        .decision,
        PromptExerciseActionV1::RejectStale
    );
}
