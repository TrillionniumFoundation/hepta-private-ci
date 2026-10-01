use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid generation: {error}"))
}

fn support(label: &str) -> KnowledgeSupportV2 {
    KnowledgeSupportV2 {
        source_id: id(label),
        source_revision: Revision::new(1).unwrap_or_else(|error| panic!("valid revision: {error}")),
        source_fact_digest: digest(label),
        validity_digest: digest("validity"),
        valid_from_unix_seconds: None,
        valid_to_unix_seconds: None,
        tombstoned: false,
    }
}

fn node(label: &str) -> KnowledgeNodeV2 {
    KnowledgeNodeV2 {
        node_id: id(label),
        node_kind_id: id("kind:entity"),
        payload_digest: digest(label),
        supports: vec![support(label)],
    }
}

fn edge(target: &str) -> KnowledgeEdgeV2 {
    KnowledgeEdgeV2 {
        identity: KnowledgeEdgeIdentityV2 {
            source_node_id: id("node:a"),
            relation: KnowledgeRelationKindV2::Supports,
            target_node_id: id(target),
        },
        confidence: ProbabilityQ32::ONE,
        validity_digest: digest("edge-validity"),
        supports: vec![support(target)],
    }
}

fn input(nodes: Vec<KnowledgeNodeV2>, edges: Vec<KnowledgeEdgeV2>) -> KnowledgeProjectionInputV2 {
    KnowledgeProjectionInputV2 {
        source_snapshot_digest: digest("snapshot:1"),
        generation_vector_digest: digest("vector:1"),
        graph_profile_digest: digest("profile:1"),
        complete_source_cut: true,
        nodes,
        edges,
    }
}

fn graph() -> KnowledgeGenerationV2 {
    build_complete_generation(
        generation(1),
        input(
            vec![node("node:a"), node("node:b"), node("node:c")],
            vec![edge("node:b"), edge("node:c")],
        ),
    )
    .unwrap_or_else(|error| panic!("valid graph: {error}"))
}

fn query(graph: &KnowledgeGenerationV2) -> KnowledgeRelationQueryV2 {
    KnowledgeRelationQueryV2 {
        query_id: id("query:audit"),
        generation_digest: graph.generation_digest,
        seed_node_ids: vec![id("node:a")],
        relation_kinds: Vec::new(),
        valid_at_unix_seconds: None,
        maximum_edges: 1,
    }
}

#[test]
fn restored_generation_rejects_rehashed_noncanonical_order() {
    let mut reordered_nodes = graph();
    reordered_nodes.nodes.swap(0, 1);
    reordered_nodes.generation_digest = compute_generation_digest(&reordered_nodes);
    assert_eq!(
        reordered_nodes.validate(),
        Err(KnowledgeGenerationErrorV2::NonCanonicalNodeOrder)
    );

    let mut reordered_edges = graph();
    reordered_edges.edges.reverse();
    reordered_edges.generation_digest = compute_generation_digest(&reordered_edges);
    assert_eq!(
        query_relations(&reordered_edges, query(&reordered_edges)),
        Err(KnowledgeGenerationErrorV2::NonCanonicalEdgeOrder)
    );
}

#[test]
fn restored_generation_rejects_conflicting_same_revision_supports() {
    for mutate_node in [true, false] {
        let mut forged = graph();
        let supports = if mutate_node {
            &mut forged.nodes[0].supports
        } else {
            &mut forged.edges[0].supports
        };
        let mut conflicting = supports[0].clone();
        conflicting.source_fact_digest = digest("conflicting-fact");
        supports.push(conflicting);
        supports.sort();
        forged.generation_digest = compute_generation_digest(&forged);
        assert_eq!(
            forged.validate(),
            Err(KnowledgeGenerationErrorV2::DuplicateSupport)
        );
    }
}

#[test]
fn initial_publication_cannot_claim_an_unchanged_predecessor() {
    let mut receipt = publish_generation(None, &graph())
        .unwrap_or_else(|error| panic!("valid initial publication: {error}"));
    receipt.disposition = KnowledgePublicationDispositionV2::Unchanged;
    receipt.publication_digest = compute_publication_digest(&receipt);
    assert_eq!(
        receipt.validate(),
        Err(KnowledgeGenerationErrorV2::InvalidPredecessor)
    );
}

#[test]
fn changed_source_cut_with_equal_graph_remains_receipt_bound() {
    let predecessor = graph();
    let mut next_input = input(predecessor.nodes.clone(), predecessor.edges.clone());
    next_input.source_snapshot_digest = digest("snapshot:2");
    let candidate = build_complete_generation(generation(2), next_input)
        .unwrap_or_else(|error| panic!("valid next cut: {error}"));
    let receipt = publish_generation(Some(&predecessor), &candidate)
        .unwrap_or_else(|error| panic!("valid publication: {error}"));
    assert_eq!(
        receipt.disposition,
        KnowledgePublicationDispositionV2::Unchanged
    );
    assert_eq!(receipt.generation_digest, candidate.generation_digest);
    assert_ne!(receipt.generation_digest, predecessor.generation_digest);
    assert_eq!(
        receipt.predecessor_digest,
        Some(predecessor.generation_digest)
    );
}

#[test]
fn bounded_temporal_query_counts_only_visible_omissions() {
    let mut hidden_node = node("node:c");
    hidden_node.supports[0].valid_to_unix_seconds = Some(100);
    let mut retained_edge = edge("node:b");
    let mut expired_support = support("expired:ab");
    expired_support.valid_to_unix_seconds = Some(100);
    retained_edge.supports.push(expired_support);
    let mut expired_edge = edge("node:d");
    expired_edge.supports[0].valid_to_unix_seconds = Some(100);
    let omitted_edge = edge("node:e");
    let graph = build_complete_generation(
        generation(1),
        input(
            vec![
                node("node:a"),
                node("node:b"),
                hidden_node,
                node("node:d"),
                node("node:e"),
            ],
            vec![
                retained_edge.clone(),
                edge("node:c"),
                expired_edge,
                omitted_edge,
            ],
        ),
    )
    .unwrap_or_else(|error| panic!("valid temporal graph: {error}"));
    let structural = query_relations(&graph, query(&graph))
        .unwrap_or_else(|error| panic!("valid structural query: {error}"));
    retained_edge.supports.sort();
    assert_eq!(structural.edges, vec![retained_edge.clone()]);
    assert_eq!(structural.omitted_count, 3);

    let mut timed_query = query(&graph);
    timed_query.valid_at_unix_seconds = Some(150);
    let timed = query_relations(&graph, timed_query)
        .unwrap_or_else(|error| panic!("valid temporal query: {error}"));
    retained_edge
        .supports
        .retain(|support| support.visible_at(150));
    assert_eq!(timed.edges, vec![retained_edge]);
    assert_eq!(timed.omitted_count, 1);
}

#[test]
fn oversized_query_and_delta_lists_are_rejected_before_deduplication() {
    let graph = graph();
    let mut oversized_query = query(&graph);
    oversized_query.seed_node_ids = vec![id("node:a"); MAX_KNOWLEDGE_NODES_V2 + 1];
    assert_eq!(
        query_relations(&graph, oversized_query),
        Err(KnowledgeGenerationErrorV2::QueryInputLimitExceeded)
    );
    let delta = KnowledgeProjectionDeltaV2 {
        expected_predecessor_digest: graph.generation_digest,
        source_snapshot_digest: digest("snapshot:2"),
        generation_vector_digest: digest("vector:2"),
        graph_profile_digest: graph.graph_profile_digest,
        remove_node_ids: vec![id("node:a"); MAX_KNOWLEDGE_NODES_V2 + 1],
        upsert_nodes: Vec::new(),
        remove_edge_identities: Vec::new(),
        upsert_edges: Vec::new(),
    };
    assert_eq!(
        apply_incremental_delta(&graph, generation(2), delta),
        Err(KnowledgeGenerationErrorV2::NodeLimitExceeded)
    );
}

#[test]
fn generation_support_budget_is_shared_across_nodes_and_edges() {
    let template = support("budget:source");
    let mut nodes = (0..6)
        .map(|index| {
            let mut node = node(&format!("node:budget:{index}"));
            node.supports = vec![template.clone(); MAX_SUPPORTS_PER_RELATION_V2];
            node
        })
        .collect::<Vec<_>>();
    let mut edge = edge("node:budget:1");
    edge.supports =
        vec![template.clone(); MAX_KNOWLEDGE_SUPPORTS_V2 - 6 * MAX_SUPPORTS_PER_RELATION_V2];
    assert_eq!(
        validate_generation_limits(&nodes, std::slice::from_ref(&edge)),
        Ok(())
    );
    edge.supports.push(template);
    assert_eq!(
        validate_generation_limits(&nodes, std::slice::from_ref(&edge)),
        Err(KnowledgeGenerationErrorV2::TotalSupportLimitExceeded)
    );
    nodes.push(node("node:a"));
    assert_eq!(
        build_complete_generation(generation(1), input(nodes, vec![edge])),
        Err(KnowledgeGenerationErrorV2::TotalSupportLimitExceeded)
    );
}

#[test]
fn delta_combined_support_budget_is_rejected_before_predecessor_cloning() {
    let predecessor = graph();
    let template = support("budget:source");
    let nodes = (0..7)
        .map(|index| {
            let mut node = node(&format!("node:budget:{index}"));
            let count = if index == 6 {
                MAX_KNOWLEDGE_SUPPORTS_V2 - 6 * MAX_SUPPORTS_PER_RELATION_V2
            } else {
                MAX_SUPPORTS_PER_RELATION_V2
            };
            node.supports = vec![template.clone(); count];
            node
        })
        .collect::<Vec<_>>();
    assert_eq!(validate_generation_limits(&nodes, &[]), Ok(()));
    let delta = KnowledgeProjectionDeltaV2 {
        expected_predecessor_digest: predecessor.generation_digest,
        source_snapshot_digest: digest("snapshot:2"),
        generation_vector_digest: digest("vector:2"),
        graph_profile_digest: predecessor.graph_profile_digest,
        remove_node_ids: Vec::new(),
        upsert_nodes: nodes,
        remove_edge_identities: Vec::new(),
        upsert_edges: Vec::new(),
    };
    assert_eq!(
        apply_incremental_delta(&predecessor, generation(2), delta),
        Err(KnowledgeGenerationErrorV2::TotalSupportLimitExceeded)
    );
}

#[test]
fn removing_and_reinserting_a_node_drops_old_incident_edges() {
    let predecessor = graph();
    let replacement_edge = edge("node:c");
    let delta = KnowledgeProjectionDeltaV2 {
        expected_predecessor_digest: predecessor.generation_digest,
        source_snapshot_digest: digest("snapshot:2"),
        generation_vector_digest: digest("vector:2"),
        graph_profile_digest: predecessor.graph_profile_digest,
        remove_node_ids: vec![id("node:a")],
        upsert_nodes: vec![node("node:a")],
        remove_edge_identities: vec![replacement_edge.identity.clone()],
        upsert_edges: vec![replacement_edge.clone()],
    };
    let incremental = apply_incremental_delta(&predecessor, generation(2), delta)
        .unwrap_or_else(|error| panic!("valid node replacement: {error}"));
    let mut full_input = input(predecessor.nodes.clone(), vec![replacement_edge]);
    full_input.source_snapshot_digest = digest("snapshot:2");
    full_input.generation_vector_digest = digest("vector:2");
    let full = build_complete_generation(generation(2), full_input)
        .unwrap_or_else(|error| panic!("valid full node replacement: {error}"));
    assert_eq!(incremental, full);
}

#[test]
fn tombstoning_the_last_source_projects_an_empty_full_and_incremental_graph() {
    let predecessor = graph();
    let mut nodes = predecessor.nodes.clone();
    let mut edges = predecessor.edges.clone();
    for supports in nodes
        .iter_mut()
        .map(|node| &mut node.supports)
        .chain(edges.iter_mut().map(|edge| &mut edge.supports))
    {
        for support in supports {
            support.tombstoned = true;
        }
    }
    let delta = KnowledgeProjectionDeltaV2 {
        expected_predecessor_digest: predecessor.generation_digest,
        source_snapshot_digest: digest("snapshot:2"),
        generation_vector_digest: digest("vector:2"),
        graph_profile_digest: predecessor.graph_profile_digest,
        remove_node_ids: Vec::new(),
        upsert_nodes: nodes.clone(),
        remove_edge_identities: Vec::new(),
        upsert_edges: edges.clone(),
    };
    let incremental = apply_incremental_delta(&predecessor, generation(2), delta)
        .unwrap_or_else(|error| panic!("valid last-source revocation: {error}"));
    let mut full_input = input(nodes, edges);
    full_input.source_snapshot_digest = digest("snapshot:2");
    full_input.generation_vector_digest = digest("vector:2");
    let full = build_complete_generation(generation(2), full_input)
        .unwrap_or_else(|error| panic!("valid empty full projection: {error}"));
    assert_eq!(incremental, full);
    assert!(full.nodes.is_empty());
    assert!(full.edges.is_empty());

    assert_eq!(
        build_complete_generation(generation(1), input(Vec::new(), vec![edge("node:b")])),
        Err(KnowledgeGenerationErrorV2::UnknownEdgeNode)
    );
}
