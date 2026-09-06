use super::*;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

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

fn generation(value: u64) -> Generation {
    let Ok(value) = Generation::new(value) else {
        panic!("test generation must be valid");
    };
    value
}

fn record(name: &str, kind: MemoryKind, state: RecordState) -> MemoryRecord {
    MemoryRecord {
        record_id: id(name),
        revision: revision(1),
        kind,
        content_digest: Digest32::of_bytes(name.as_bytes()),
        predecessor_digest: None,
        citations: Vec::new(),
        state,
    }
}

fn snapshot() -> CognitiveSnapshot {
    let result = build_snapshot(
        generation(1),
        vec![
            record("memory:a", MemoryKind::Fact, RecordState::Live),
            record("memory:b", MemoryKind::Episode, RecordState::Live),
            record("memory:c", MemoryKind::Fact, RecordState::Tombstone),
        ],
    );
    let Ok(value) = result else {
        panic!("test snapshot must build");
    };
    value
}

#[test]
fn read_is_snapshot_bound_and_authority_free() {
    let snapshot = snapshot();
    let request = ReadRequest {
        snapshot_digest: snapshot.snapshot_digest,
        allowed_kinds: vec![MemoryKind::Fact],
        maximum_results: 8,
        include_tombstones: false,
    };
    let Ok(receipt) = read(&snapshot, request) else {
        panic!("bounded read must succeed");
    };
    assert_eq!(receipt.records.len(), 1);
    assert_eq!(receipt.records[0].record_id, id("memory:a"));
    assert!(!receipt.authority.grants_any());
}

#[test]
fn stale_snapshot_is_rejected() {
    let snapshot = snapshot();
    let request = ReadRequest {
        snapshot_digest: Digest32::of_bytes(b"stale"),
        allowed_kinds: Vec::new(),
        maximum_results: 8,
        include_tombstones: false,
    };
    assert_eq!(read(&snapshot, request), Err(Error::SnapshotMismatch));
}

#[test]
fn bounded_result_count_is_explicit() {
    let snapshot = snapshot();
    let request = ReadRequest {
        snapshot_digest: snapshot.snapshot_digest,
        allowed_kinds: Vec::new(),
        maximum_results: 1,
        include_tombstones: true,
    };
    let Ok(receipt) = read(&snapshot, request) else {
        panic!("bounded read must succeed");
    };
    assert_eq!(receipt.records.len(), 1);
    assert_eq!(receipt.omitted_count, 2);
}
