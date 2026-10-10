use super::*;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn revision(value: u64) -> Revision {
    let Ok(value) = Revision::new(value) else {
        panic!("test revision must be valid");
    };
    value
}

fn generation() -> Generation {
    let Ok(value) = Generation::new(1) else {
        panic!("test generation must be valid");
    };
    value
}

fn record(revision_value: u64, predecessor: Option<Digest32>, state: RecordState) -> MemoryRecord {
    MemoryRecord {
        record_id: id("memory:1"),
        revision: revision(revision_value),
        kind: MemoryKind::Fact,
        content_digest: Digest32::of_bytes(format!("content:{revision_value}").as_bytes()),
        predecessor_digest: predecessor,
        citations: Vec::new(),
        state,
    }
}

#[test]
fn latest_revision_and_tombstone_are_preserved() {
    let first = record(1, None, RecordState::Live);
    let second = record(2, Some(first.record_digest()), RecordState::Tombstone);
    let Ok(checkpoint) = compact(
        generation(),
        Digest32::of_bytes(b"snapshot"),
        vec![second.clone(), first],
    ) else {
        panic!("compaction must succeed");
    };
    assert_eq!(checkpoint.records, vec![second]);
    assert!(!checkpoint.authority.grants_any());
}

#[test]
fn broken_lineage_is_rejected() {
    let first = record(1, None, RecordState::Live);
    let second = record(2, Some(Digest32::of_bytes(b"wrong")), RecordState::Live);
    assert_eq!(
        compact(
            generation(),
            Digest32::of_bytes(b"snapshot"),
            vec![first, second]
        ),
        Err(Error::BrokenLineage("memory:1".to_string()))
    );
}

#[test]
fn missing_initial_revision_is_rejected() {
    let second = record(2, Some(Digest32::of_bytes(b"prior")), RecordState::Live);
    assert_eq!(
        compact(generation(), Digest32::of_bytes(b"snapshot"), vec![second]),
        Err(Error::BrokenLineage("memory:1".to_string()))
    );
}
