use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
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

fn record(name: &str) -> MemoryRecord {
    MemoryRecord {
        record_id: id(name),
        revision: revision(1),
        kind: MemoryKind::Fact,
        content_digest: digest(name.as_bytes()),
        predecessor_digest: None,
        citations: vec![Citation {
            source_id: id("source:1"),
            source_digest: digest(b"source"),
        }],
        state: RecordState::Live,
    }
}

#[test]
fn snapshot_is_canonical_and_authority_free() {
    let left = build_snapshot(generation(1), vec![record("record:b"), record("record:a")]);
    let right = build_snapshot(generation(1), vec![record("record:a"), record("record:b")]);
    let (Ok(left), Ok(right)) = (left, right) else {
        panic!("canonical snapshots must build");
    };
    assert_eq!(left, right);
    assert!(!left.authority.grants_any());
}

#[test]
fn later_revision_requires_predecessor() {
    let mut value = record("record:1");
    value.revision = revision(2);
    assert_eq!(value.validate(), Err(Error::MissingPredecessor));
}

#[test]
fn duplicate_citation_is_rejected() {
    let mut value = record("record:1");
    value.citations.push(value.citations[0].clone());
    assert_eq!(
        value.validate(),
        Err(Error::DuplicateCitation("source:1".to_string()))
    );
}

#[test]
fn one_source_identity_cannot_bind_conflicting_digests() {
    let mut value = record("record:1");
    value.citations.push(Citation {
        source_id: id("source:1"),
        source_digest: digest(b"conflicting source bytes"),
    });
    assert_eq!(
        value.validate(),
        Err(Error::DuplicateCitation("source:1".to_string()))
    );

    value.citations[1].source_id = id("source:2");
    assert_eq!(value.validate(), Ok(()));
}

#[test]
fn valid_v1_record_and_snapshot_digests_remain_stable() {
    let value = record("record:1");
    assert_eq!(
        value.record_digest().to_string(),
        "a63e977e68eb04a2a8d75217349dafc43d2fe4ad51b1364d6b059ae36551d7d4"
    );
    let Ok(snapshot) = build_snapshot(generation(1), vec![value]) else {
        panic!("valid snapshot must build");
    };
    assert_eq!(
        snapshot.snapshot_digest.to_string(),
        "f2023bd15e4a3e09328e6dd5e82b3b76ba5f622c3a84b83950a89a02077035dc"
    );
    assert_eq!(snapshot.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn duplicate_record_revision_is_rejected() {
    let value = record("record:1");
    assert_eq!(
        build_snapshot(generation(1), vec![value.clone(), value]),
        Err(Error::DuplicateRecord("record:1".to_string()))
    );
}
