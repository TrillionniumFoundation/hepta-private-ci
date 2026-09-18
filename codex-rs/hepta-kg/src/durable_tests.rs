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
