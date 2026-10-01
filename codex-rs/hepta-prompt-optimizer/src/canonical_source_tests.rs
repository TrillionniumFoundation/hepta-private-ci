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

pub(super) fn selection_request() -> PromptPortfolioRequestV1 {
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
        "edge-support",
        "edge-confidence",
        "edge-validity",
        "edge-tombstone",
        "node-support",
    ] {
        let mut graph = baseline.clone();
        // Independent supplement labels cannot bypass registered baseline checks.
        if tamper != "omit" {
            graph.source_snapshot_digest = digest("supplemental source");
            graph.graph_profile_digest = digest("supplemental profile");
        }
        match tamper {
            "omit" => graph.edges.clear(),
            "supplemental-omit" => graph.edges.clear(),
            "relation" => graph.edges[0].identity.relation = KnowledgeRelationKindV2::Causes,
            "edge-clock" => graph.edges[0].supports[0].valid_from_unix_seconds = Some(1),
            "node-clock" => graph.nodes[1].supports[0].valid_from_unix_seconds = Some(1),
            "edge-support" => {
                graph.edges[0].supports[0].source_fact_digest = digest("altered fact")
            }
            "edge-confidence" => graph.edges[0].confidence = ProbabilityQ32::ZERO,
            "edge-validity" => graph.edges[0].validity_digest = digest("altered validity"),
            "edge-tombstone" => graph.edges[0].supports[0].tombstoned = true,
            "node-support" => {
                graph.nodes[1].supports[0].tombstoned = true;
                graph.nodes[1]
                    .supports
                    .push(support("replacement-endpoint"));
            }
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
            matches!(&result, Err(CanonicalPromptError::KnowledgeGraph(_))),
            "registered owner constraint tampering must be rejected: {tamper}: {result:?}"
        );
    }
}

fn signed_pair(
    graph: &KnowledgeGenerationV2,
    verifier: &LearningEvidenceVerifierV1,
) -> PromptPairUtilityEvidenceV1 {
    let edge = graph
        .edges
        .iter()
        .find(|edge| {
            matches!(
                edge.identity.relation,
                KnowledgeRelationKindV2::PromptComplements
                    | KnowledgeRelationKindV2::PromptSubstitutes
            )
        })
        .expect("registered numeric relation");
    let value = FixedQ32::from_raw(-10);
    let placeholder = temporal::sign_temporal_evidence(
        verifier,
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        8,
        b"placeholder",
    );
    let mut evidence = PromptPairUtilityEvidenceV1 {
        left_factor_id: id("factor:a"),
        right_factor_id: id("factor:b"),
        state_digest: digest("state"),
        graph_generation_digest: graph.generation_digest,
        edge_validity_digest: edge.validity_digest,
        marginal_utility_q32: value,
        confidence_lower_q32: value,
        confidence_upper_q32: value,
        support_audit_digest: digest("independent registered pair audit"),
        evidence: placeholder,
    };
    evidence.evidence = temporal::sign_temporal_evidence(
        verifier,
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        8,
        &pair_utility_evidence_signing_payload_v1(&evidence),
    );
    evidence
}

#[test]
fn registered_numeric_relations_require_exact_edges_and_authenticated_pair_evidence() {
    for kind in [
        PromptFactorRelationKind::Complements,
        PromptFactorRelationKind::Substitutes,
    ] {
        let temp = tempfile::tempdir().expect("tempdir");
        let registry = registered_relation_fixture(&temp.path().join("registry"), kind);
        let (priced, verifier) = temporal::authentic_temporal_prices(&registry);
        let baseline = owner_graph(&registry);
        assert_eq!(
            select_portfolio_v1(
                &priced,
                &baseline,
                Vec::new(),
                &verifier,
                selection_request(),
                100
            ),
            Err(CanonicalPromptError::MissingPairEvidence(
                "factor:a".to_owned(),
                "factor:b".to_owned()
            )),
        );
        let mut omitted = baseline.clone();
        omitted.edges.clear();
        omitted.source_snapshot_digest = digest("independent supplement source");
        omitted.graph_profile_digest = digest("independent supplement profile");
        assert!(matches!(
            select_portfolio_v1(
                &priced,
                &rebuild_graph(omitted),
                Vec::new(),
                &verifier,
                selection_request(),
                100
            ),
            Err(CanonicalPromptError::KnowledgeGraph(_)),
        ));
        // The supplied graph and its signed pair digest are preserved, including
        // independently supplied prerequisites alongside the exact owner edge.
        let mut supplement = baseline.clone();
        supplement.source_snapshot_digest = digest("independent supplement source");
        supplement.graph_profile_digest = digest("independent supplement profile");
        supplement.edges.push(KnowledgeEdgeV2 {
            identity: KnowledgeEdgeIdentityV2 {
                source_node_id: id("factor:a"),
                relation: KnowledgeRelationKindV2::PromptRequires,
                target_node_id: id("factor:b"),
            },
            confidence: ProbabilityQ32::ONE,
            validity_digest: digest("supplemental prerequisite"),
            supports: vec![support("supplemental-prerequisite")],
        });
        let supplement = rebuild_graph(supplement);
        let selected = select_portfolio_v1(
            &priced,
            &supplement,
            vec![signed_pair(&supplement, &verifier)],
            &verifier,
            selection_request(),
            100,
        )
        .expect("authenticated numeric owner relation plus caller supplement");
        assert_eq!(
            selected.graph_generation_digest,
            supplement.generation_digest
        );
        assert_eq!(
            selected.receipt.factor_ids,
            vec![id("factor:a"), id("factor:b")]
        );
        assert_eq!(
            exercise_v1(
                registry.registry().expect("registry"),
                &selected,
                exercise_request_for(&selected)
            )
            .expect("numeric substitutes are not hard conflicts")
            .decision,
            PromptExerciseActionV1::Exercise,
        );
    }
}

#[test]
fn owner_projection_source_or_profile_labels_require_the_complete_owner_generation() {
    let temp = tempfile::tempdir().expect("tempdir");
    let registry = registered_relation_fixture(
        &temp.path().join("registry"),
        PromptFactorRelationKind::Conflicts,
    );
    let (priced, verifier) = temporal::authentic_temporal_prices(&registry);
    let baseline = owner_graph(&registry);
    for claim in ["factor-source", "owner-profile", "registry-digest"] {
        let mut graph = baseline.clone();
        graph.source_snapshot_digest = digest("independent supplement source");
        graph.graph_profile_digest = digest("independent supplement profile");
        graph.nodes.push(KnowledgeNodeV2 {
            node_id: id("factor:extra"),
            node_kind_id: id("kind:supplement"),
            payload_digest: digest("extra payload"),
            supports: vec![support("extra")],
        });
        match claim {
            "factor-source" => graph.source_snapshot_digest = baseline.source_snapshot_digest,
            "owner-profile" => graph.graph_profile_digest = baseline.graph_profile_digest,
            "registry-digest" => {
                graph.source_snapshot_digest = priced.candidates.registry_snapshot.registry_digest
            }
            _ => unreachable!(),
        }
        assert_eq!(
            select_portfolio_v1(
                &priced,
                &rebuild_graph(graph),
                Vec::new(),
                &verifier,
                selection_request(),
                100
            ),
            Err(CanonicalPromptError::KnowledgeGraph(
                "claimed registry projection diverged from sealed owner source".to_owned(),
            )),
            "claim: {claim}",
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
