use super::*;

fn build_generation(
    source: u64,
    target: u64,
    predecessor: Option<Digest32>,
) -> Result<QualifiedCompactionCandidateV2, QualifiedCompactionError> {
    let mut vector = snapshot_key().vector;
    vector.compact_checkpoint_generation = generation(source);
    let snapshot =
        CognitiveSnapshotKeyV1::new(vector).map_err(QualifiedCompactionError::Contract)?;
    let inputs = vec![input(
        record("memory:genesis", 1, None, RecordState::Live),
        1,
    )];
    let memory = source_memory_snapshot(&inputs);
    let semantic = semantic_payload(&snapshot, &memory);
    let (trusted_tokenizer, _) = tokenizer();
    build_qualified_candidate(
        snapshot,
        &memory,
        generation(target),
        predecessor,
        &policy(1, Vec::new()),
        &semantic,
        &trusted_tokenizer,
        inputs,
    )
}

#[test]
fn canonical_genesis_and_successor_generations_are_distinct()
-> Result<(), Box<dyn std::error::Error>> {
    let first = build_generation(1, 1, None)?;
    assert_eq!(first.checkpoint().generation.get(), 1);
    assert_eq!(first.checkpoint().predecessor_digest, None);
    let predecessor = first.checkpoint().checkpoint_digest;
    let second = build_generation(1, 2, Some(predecessor))?;
    assert_eq!(second.checkpoint().generation.get(), 2);
    assert_eq!(second.checkpoint().predecessor_digest, Some(predecessor));
    for (source, target) in [(1, 2), (2, 2), (2, 1)] {
        assert!(
            build_generation(source, target, None).is_err(),
            "unanchored source={source}, target={target} must reject"
        );
    }
    assert_eq!(
        build_generation(2, 2, Some(predecessor)),
        Err(QualifiedCompactionError::CheckpointGenerationMismatch),
    );
    assert_eq!(
        build_generation(u64::MAX, u64::MAX, Some(predecessor)),
        Err(QualifiedCompactionError::CheckpointGenerationMismatch),
    );
    Ok(())
}

#[test]
fn canonical_broken_lineage_is_rejected() {
    let first = record("memory:1", 1, None, RecordState::Live);
    let second = record("memory:1", 2, Some(digest("wrong")), RecordState::Live);
    assert_eq!(
        build(
            &policy(2, Vec::new()),
            vec![input(first, 1), input(second, 1)]
        ),
        Err(QualifiedCompactionError::BrokenLineage(
            "memory:1".to_string()
        )),
    );
}

#[test]
fn canonical_missing_initial_revision_is_rejected() {
    let second = record("memory:1", 2, Some(digest("prior")), RecordState::Live);
    assert_eq!(
        build(&policy(2, Vec::new()), vec![input(second, 1)]),
        Err(QualifiedCompactionError::BrokenLineage(
            "memory:1".to_string()
        )),
    );
}

#[test]
fn canonical_protected_set_cannot_exceed_capacity() {
    let first = record("memory:a", 1, None, RecordState::Live);
    let second = record("memory:b", 1, None, RecordState::Live);
    assert_eq!(
        build(
            &policy(1, vec![id("memory:a"), id("memory:b")]),
            vec![input(first, 1), input(second, 1)],
        ),
        Err(QualifiedCompactionError::ProtectedReferencesExceedCapacity),
    );
}
