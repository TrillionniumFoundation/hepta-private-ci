use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn generation() -> Generation {
    let Ok(value) = Generation::new(1) else {
        panic!("test generation must be valid");
    };
    value
}

fn edge(source: &str, live: bool) -> KnowledgeEdge {
    KnowledgeEdge {
        source_id: id(source),
        relation_id: id("rel:knows"),
        target_id: id("target:1"),
        source_fact_digest: Digest32::of_bytes(source.as_bytes()),
        live,
    }
}

#[test]
fn rebuild_is_canonical_and_authority_free() {
    let snapshot = Digest32::of_bytes(b"snapshot");
    let left = rebuild(
        generation(),
        snapshot,
        vec![edge("source:b", true), edge("source:a", true)],
    );
    let right = rebuild(
        generation(),
        snapshot,
        vec![edge("source:a", true), edge("source:b", true)],
    );
    let (Ok(left), Ok(right)) = (left, right) else {
        panic!("projections must build");
    };
    assert_eq!(left, right);
    assert!(!left.authority.grants_any());
}

#[test]
fn deleted_edges_do_not_enter_projection() {
    let snapshot = Digest32::of_bytes(b"snapshot");
    let Ok(value) = rebuild(generation(), snapshot, vec![edge("source:a", false)]) else {
        panic!("projection must build");
    };
    assert!(value.edges.is_empty());
}

#[test]
fn duplicate_edges_are_rejected() {
    let snapshot = Digest32::of_bytes(b"snapshot");
    assert_eq!(
        rebuild(
            generation(),
            snapshot,
            vec![edge("source:a", true), edge("source:a", true)]
        ),
        Err(Error::DuplicateEdge("source:a".to_string()))
    );
}
