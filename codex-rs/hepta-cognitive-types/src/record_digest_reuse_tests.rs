//! Frozen concatenating oracle for the existing borrowed-record digest path.

use super::*;
use crate::contract::Validated;

fn record(count: usize, kind: MemoryKind, state: RecordState) -> MemoryRecord {
    MemoryRecord {
        record_id: StableId::new("record:borrowed").expect("record id"),
        revision: Revision::new(1).expect("revision"),
        kind,
        content_digest: Digest32::of_bytes(b"payload"),
        predecessor_digest: None,
        citations: (0..count)
            .map(|index| Citation {
                source_id: StableId::new(format!("source:{index:03}")).expect("source id"),
                source_digest: Digest32::of_bytes(format!("source bytes {index}").as_bytes()),
            })
            .collect(),
        state,
    }
}

// Deliberately retain the old clone-and-concatenate algorithm in tests only.
// Do not delegate framing, tags or ordering to production helpers.
fn frozen_reference(value: &MemoryRecord) -> Digest32 {
    let mut bytes = b"hepta.cognitive.record.v1".to_vec();
    let text = value.record_id.as_str();
    bytes.extend_from_slice(&(text.len() as u32).to_be_bytes());
    bytes.extend_from_slice(text.as_bytes());
    bytes.extend_from_slice(&value.revision.get().to_be_bytes());
    bytes.push(match value.kind {
        MemoryKind::Episode => 0,
        MemoryKind::Fact => 1,
        MemoryKind::Preference => 2,
        MemoryKind::Procedure => 3,
    });
    bytes.push(match value.state {
        RecordState::Live => 0,
        RecordState::Tombstone => 1,
    });
    bytes.extend_from_slice(value.content_digest.as_array());
    match value.predecessor_digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
    let mut citations = value.citations.clone();
    citations.sort();
    for citation in citations {
        let source = citation.source_id.as_str().as_bytes();
        bytes.extend_from_slice(&(source.len() as u32).to_be_bytes());
        bytes.extend_from_slice(source);
        bytes.extend_from_slice(citation.source_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

#[test]
fn borrowed_digest_preserves_frozen_bytes_and_does_not_mutate_input() {
    for count in [0, 1, 2, 8, 32, MAX_CITATIONS] {
        for kind in [
            MemoryKind::Episode,
            MemoryKind::Fact,
            MemoryKind::Preference,
            MemoryKind::Procedure,
        ] {
            for state in [RecordState::Live, RecordState::Tombstone] {
                for later in [false, true] {
                    let mut value = record(count, kind, state);
                    if later {
                        value.revision = Revision::new(2).expect("revision");
                        value.predecessor_digest = Some(Digest32::of_bytes(b"predecessor"));
                    }
                    let expected = frozen_reference(&value);
                    for _ in 0..3 {
                        if !value.citations.is_empty() {
                            value.citations.rotate_left(1);
                        }
                        value.citations.reverse();
                        let before = value.clone();
                        let checked = Validated::new(value.clone()).expect("valid record");
                        assert_eq!(value.record_digest(), expected);
                        assert_eq!(checked.checked_record_digest(), expected);
                        assert_eq!(value, before);
                    }
                }
            }
        }
    }
}

#[test]
fn borrowed_validation_keeps_logical_identity_and_capacity_failures() {
    let mut value = record(MAX_CITATIONS, MemoryKind::Fact, RecordState::Live);
    value.validate().expect("exact citation ceiling");
    value.citations.push(value.citations[0].clone());
    assert_eq!(value.validate(), Err(Error::CitationLimitExceeded));
    value.citations.pop();
    value.citations[1].source_id = value.citations[0].source_id.clone();
    assert_eq!(
        value.validate(),
        Err(Error::DuplicateCitation("source:000".to_string()))
    );
    // Even an invalid raw DTO keeps the historical digest interpretation.
    assert_eq!(value.record_digest(), frozen_reference(&value));
    assert!(Validated::new(value).is_err());
}

#[test]
fn a_later_call_recomputes_content_and_snapshot_identity() {
    let mut value = record(/*count*/ 8, MemoryKind::Fact, RecordState::Live);
    let first = value.record_digest();
    let generation = Generation::new(7).expect("generation");
    let snapshot = build_snapshot(generation, vec![value.clone()]).expect("snapshot");
    value.citations[0].source_digest = Digest32::of_bytes(b"changed source content");
    assert_ne!(value.record_digest(), first);
    assert_eq!(value.record_digest(), frozen_reference(&value));
    let changed = build_snapshot(generation, vec![value.clone()]).expect("changed snapshot");
    assert_ne!(snapshot.snapshot_digest, changed.snapshot_digest);
    let mut stale = snapshot;
    stale.records = vec![value];
    assert_eq!(stale.validate_integrity(), Err(Error::SnapshotDigestMismatch));
}
