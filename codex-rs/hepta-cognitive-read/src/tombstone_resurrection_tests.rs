use super::*;
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

fn record(
    record_id: &str,
    revision_value: u64,
    predecessor_digest: Option<Digest32>,
    state: RecordState,
) -> MemoryRecord {
    MemoryRecord {
        record_id: id(record_id),
        revision: revision(revision_value),
        kind: MemoryKind::Fact,
        content_digest: Digest32::of_bytes(
            format!("{record_id}:{revision_value}:{state:?}").as_bytes(),
        ),
        predecessor_digest,
        citations: Vec::new(),
        state,
    }
}

fn snapshot(records: Vec<MemoryRecord>) -> CognitiveSnapshot {
    let Ok(generation) = Generation::new(/*value*/ 1) else {
        panic!("test generation must be valid");
    };
    let Ok(snapshot) = build_snapshot(generation, records) else {
        panic!("test snapshot must build");
    };
    snapshot
}

fn request(snapshot: &CognitiveSnapshot, include_tombstones: bool) -> ReadRequest {
    ReadRequest {
        snapshot_digest: snapshot.snapshot_digest,
        allowed_kinds: Vec::new(),
        maximum_results: 8,
        include_tombstones,
    }
}

fn maximum_lineage(tombstone_before_last: bool) -> CognitiveSnapshot {
    let mut records = Vec::with_capacity(16_384);
    let mut predecessor_digest = None;
    for revision_value in 1_u64..=16_384 {
        let state = if tombstone_before_last && revision_value == 16_383 {
            RecordState::Tombstone
        } else {
            RecordState::Live
        };
        let current = record(
            "memory:maximum-lineage",
            revision_value,
            predecessor_digest,
            state,
        );
        predecessor_digest = Some(current.record_digest());
        records.push(current);
    }
    snapshot(records)
}

#[test]
fn complete_tombstone_resurrection_is_rejected_in_any_record_order() {
    let first = record(
        "memory:resurrected",
        /*revision_value*/ 1,
        /*predecessor_digest*/ None,
        RecordState::Live,
    );
    let tombstone = record(
        "memory:resurrected",
        /*revision_value*/ 2,
        Some(first.record_digest()),
        RecordState::Tombstone,
    );
    let resurrected = record(
        "memory:resurrected",
        /*revision_value*/ 3,
        Some(tombstone.record_digest()),
        RecordState::Live,
    );
    let canonical = snapshot(vec![first, tombstone, resurrected]);
    let mut reordered = canonical.clone();
    reordered.records.reverse();

    for value in [&canonical, &reordered] {
        assert_eq!(
            read(value, request(value, /*include_tombstones*/ true)),
            Err(Error::SnapshotMismatch)
        );
    }
}

#[test]
fn maximum_lineage_keeps_linearithmic_terminal_edge_validation() {
    let live = maximum_lineage(/*tombstone_before_last*/ false);
    assert_eq!(
        read(&live, request(&live, /*include_tombstones*/ false)).map(|receipt| receipt.records),
        Ok(vec![live.records[16_383].clone()])
    );

    let resurrected = maximum_lineage(/*tombstone_before_last*/ true);
    assert_eq!(
        read(
            &resurrected,
            request(&resurrected, /*include_tombstones*/ false)
        ),
        Err(Error::SnapshotMismatch)
    );
}

#[test]
fn live_lineage_and_terminal_tombstone_remain_readable() {
    let first = record(
        "memory:valid",
        /*revision_value*/ 1,
        /*predecessor_digest*/ None,
        RecordState::Live,
    );
    let second = record(
        "memory:valid",
        /*revision_value*/ 2,
        Some(first.record_digest()),
        RecordState::Live,
    );
    let live = snapshot(vec![first.clone(), second.clone()]);
    assert_eq!(
        read(&live, request(&live, /*include_tombstones*/ false)).map(|receipt| receipt.records),
        Ok(vec![second.clone()])
    );

    let tombstone = record(
        "memory:valid",
        /*revision_value*/ 3,
        Some(second.record_digest()),
        RecordState::Tombstone,
    );
    let terminal = snapshot(vec![first, second, tombstone.clone()]);
    assert_eq!(
        read(&terminal, request(&terminal, /*include_tombstones*/ false))
            .map(|receipt| receipt.records),
        Ok(Vec::new())
    );
    assert_eq!(
        read(&terminal, request(&terminal, /*include_tombstones*/ true))
            .map(|receipt| receipt.records),
        Ok(vec![tombstone])
    );
}

#[test]
fn missing_tombstone_ancestor_is_not_inferred_from_a_truncated_snapshot() {
    let omitted_tombstone = record(
        "memory:truncated",
        /*revision_value*/ 2,
        Some(Digest32::of_bytes(b"r1")),
        RecordState::Tombstone,
    );
    let current = record(
        "memory:truncated",
        /*revision_value*/ 3,
        Some(omitted_tombstone.record_digest()),
        RecordState::Live,
    );
    let value = snapshot(vec![current.clone()]);

    assert_eq!(
        read(&value, request(&value, /*include_tombstones*/ false)).map(|receipt| receipt.records),
        Ok(vec![current])
    );
}

#[test]
fn a_same_id_tombstone_on_an_unselected_fork_is_not_an_ancestor() {
    let first = record(
        "memory:forked",
        /*revision_value*/ 1,
        /*predecessor_digest*/ None,
        RecordState::Live,
    );
    let tombstone = record(
        "memory:forked",
        /*revision_value*/ 2,
        Some(first.record_digest()),
        RecordState::Tombstone,
    );
    let fork = record(
        "memory:forked",
        /*revision_value*/ 3,
        Some(first.record_digest()),
        RecordState::Live,
    );
    let value = snapshot(vec![first, tombstone, fork.clone()]);

    assert_eq!(
        read(&value, request(&value, /*include_tombstones*/ false)).map(|receipt| receipt.records),
        Ok(vec![fork])
    );
}

#[test]
fn a_cross_record_predecessor_is_not_treated_as_resurrection() {
    let tombstone = record(
        "memory:deleted",
        /*revision_value*/ 1,
        /*predecessor_digest*/ None,
        RecordState::Tombstone,
    );
    let live = record(
        "memory:other",
        /*revision_value*/ 2,
        Some(tombstone.record_digest()),
        RecordState::Live,
    );
    let value = snapshot(vec![tombstone, live.clone()]);

    assert_eq!(
        read(&value, request(&value, /*include_tombstones*/ false)).map(|receipt| receipt.records),
        Ok(vec![live])
    );
}
