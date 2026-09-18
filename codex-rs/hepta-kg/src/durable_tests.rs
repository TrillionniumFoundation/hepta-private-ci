use super::*;

fn node(id: &str) -> DurableProjectionNodeV2 {
    DurableProjectionNodeV2 {
        node_id: id.to_string(),
        canonical_entity_id: format!("entity:{id}"),
        entity_type: "person".to_string(),
        label: id.to_string(),
        valid_from: 1,
        valid_to: None,
        memory_id: "memory:v2:abc".to_string(),
        memory_revision: 1,
        source_id: "source:v1:def".to_string(),
        source_revision: 1,
    }
}

#[test]
fn durable_digest_is_stable_and_binds_relation_semantics() {
    let nodes = vec![node("a"), node("b")];
    let edge = DurableProjectionEdgeV2 {
        edge_id: "edge:1".to_string(),
        canonical_relation_id: "relation:1".to_string(),
        from_node_id: "a".to_string(),
        to_node_id: "b".to_string(),
        relation: "supports".to_string(),
        valid_from: 1,
        valid_to: None,
        memory_id: "memory:v2:abc".to_string(),
        memory_revision: 1,
        source_id: "source:v1:def".to_string(),
        source_revision: 1,
    };
    let first = durable_projection_digest_v2("agent_private", &nodes, &[edge.clone()])
        .expect("valid projection");
    let second = durable_projection_digest_v2("agent_private", &nodes, &[edge.clone()])
        .expect("same projection");
    assert_eq!(first, second);

    let mut changed = edge;
    changed.relation = "contradicts".to_string();
    let changed = durable_projection_digest_v2("agent_private", &nodes, &[changed])
        .expect("changed projection");
    assert_ne!(first, changed);
}

#[test]
fn durable_projection_rejects_dangling_edges() {
    let edge = DurableProjectionEdgeV2 {
        edge_id: "edge:1".to_string(),
        canonical_relation_id: "relation:1".to_string(),
        from_node_id: "a".to_string(),
        to_node_id: "missing".to_string(),
        relation: "supports".to_string(),
        valid_from: 1,
        valid_to: None,
        memory_id: "memory:v2:abc".to_string(),
        memory_revision: 1,
        source_id: "source:v1:def".to_string(),
        source_revision: 1,
    };
    assert!(matches!(
        durable_projection_digest_v2("agent_private", &[node("a")], &[edge]),
        Err(DurableProjectionErrorV2::MissingEdgeEndpoint(id)) if id == "missing"
    ));
}


#[test]
fn custom_relation_is_lossless_and_generation_bound() {
    use codex_hepta_types::Generation;

    let nodes = vec![node("a"), node("b")];
    let edge = DurableProjectionEdgeV2 {
        edge_id: "edge:1".to_string(),
        canonical_relation_id: "relation:custom".to_string(),
        from_node_id: "a".to_string(),
        to_node_id: "b".to_string(),
        relation: "collaborated_with".to_string(),
        valid_from: 1,
        valid_to: None,
        memory_id: "memory:v2:abc".to_string(),
        memory_revision: 1,
        source_id: "source:v1:def".to_string(),
        source_revision: 1,
    };
    let heads = vec![DurableProjectionHeadV2 {
        memory_id: "memory:v2:abc".to_string(),
        revision: 1,
        content_sha256: Digest32::of_bytes(b"content").to_string(),
        verification: "verified".to_string(),
        lifecycle: "active".to_string(),
        fact_set_sha256: Digest32::of_bytes(b"facts").to_string(),
    }];
    let generation = build_durable_generation_v2(
        Generation::new(1).expect("generation"),
        "agent_private",
        &heads,
        &nodes,
        &[edge],
    )
    .expect("durable generation");
    assert_eq!(generation.nodes.len(), 2);
    assert_eq!(generation.edges.len(), 1);
    match &generation.edges[0].identity.relation {
        KnowledgeRelationKindV2::CustomPredicate(id) => {
            assert!(id.as_str().starts_with("kg-predicate:v2:"));
        }
        other => panic!("unexpected relation kind: {other:?}"),
    }
    generation.validate().expect("canonical generation");
}

#[test]
fn built_in_relation_keeps_symbolic_kind() {
    assert_eq!(
        durable_relation_kind_v2("supports").expect("supports relation"),
        KnowledgeRelationKindV2::Supports
    );
}
