use super::*;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

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

#[test]
fn altered_snapshot_fields_are_rejected_before_filtering() {
    let original = snapshot();
    let request = ReadRequest {
        snapshot_digest: original.snapshot_digest,
        allowed_kinds: vec![MemoryKind::Fact],
        maximum_results: 1,
        include_tombstones: false,
    };
    let mut altered = Vec::new();
    let mut value = original.clone();
    // The altered record is outside the requested kind/result window. The
    // complete frozen source still has to be checked before reading a subset.
    value.records[1].content_digest = Digest32::of_bytes(b"substituted");
    altered.push(value);
    let mut value = original.clone();
    value.records[2].state = RecordState::Live;
    altered.push(value);
    let mut value = original.clone();
    value.generation = generation(2);
    altered.push(value);
    let mut value = original.clone();
    value.records[0]
        .citations
        .push(codex_hepta_cognitive_types::Citation {
            source_id: id("source:injected"),
            source_digest: Digest32::of_bytes(b"unbound citation"),
        });
    altered.push(value);
    let mut value = original.clone();
    value.records[0].revision = revision(2);
    altered.push(value);
    let mut value = original.clone();
    value.authority.runtime = true;
    altered.push(value);
    for value in altered {
        assert_eq!(read(&value, request.clone()), Err(Error::SnapshotMismatch));
    }
    assert!(read(&original, request).is_ok());
}

#[test]
fn reordered_valid_snapshot_keeps_canonical_read_receipt() {
    let original = snapshot();
    let request = ReadRequest {
        snapshot_digest: original.snapshot_digest,
        allowed_kinds: Vec::new(),
        maximum_results: 8,
        include_tombstones: true,
    };
    let mut reordered = original.clone();
    reordered.records.reverse();
    assert_eq!(read(&reordered, request.clone()), read(&original, request));
}

#[test]
fn forged_oversize_and_duplicate_snapshot_records_are_rejected() {
    let mut value = snapshot();
    let request = ReadRequest {
        snapshot_digest: value.snapshot_digest,
        allowed_kinds: Vec::new(),
        maximum_results: 8,
        include_tombstones: true,
    };
    value.records.push(value.records[0].clone());
    assert_eq!(read(&value, request.clone()), Err(Error::SnapshotMismatch));
    value.records.resize(16_385, value.records[0].clone());
    assert_eq!(read(&value, request), Err(Error::SnapshotMismatch));
}

#[test]
fn current_revision_is_resolved_before_kind_and_tombstone_filtering() {
    let original = record("memory:history", MemoryKind::Fact, RecordState::Live);
    for (kind, state) in [
        (MemoryKind::Fact, RecordState::Tombstone),
        (MemoryKind::Episode, RecordState::Live),
        (MemoryKind::Fact, RecordState::Live),
    ] {
        let mut successor = original.clone();
        successor.revision = revision(2);
        successor.predecessor_digest = Some(original.record_digest());
        successor.kind = kind;
        successor.state = state;
        let Ok(value) = build_snapshot(generation(1), vec![successor.clone(), original.clone()])
        else {
            panic!("revision history must form a valid snapshot");
        };
        let request = ReadRequest {
            snapshot_digest: value.snapshot_digest,
            allowed_kinds: vec![MemoryKind::Fact],
            maximum_results: 8,
            include_tombstones: false,
        };
        let Ok(receipt) = read(&value, request.clone()) else {
            panic!("valid current projection must be readable");
        };
        let expected = if kind == MemoryKind::Fact && state == RecordState::Live {
            vec![successor.clone()]
        } else {
            Vec::new()
        };
        assert_eq!(receipt.records, expected);
        let Ok(including_tombstones) = read(
            &value,
            ReadRequest {
                allowed_kinds: Vec::new(),
                include_tombstones: true,
                ..request
            },
        ) else {
            panic!("current tombstone must remain inspectable");
        };
        assert_eq!(including_tombstones.records, vec![successor]);
    }
}
