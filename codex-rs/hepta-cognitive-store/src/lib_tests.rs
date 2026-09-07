use super::*;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_types::Revision;
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

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn record(revision_value: u64, predecessor: Option<Digest32>, state: RecordState) -> MemoryRecord {
    MemoryRecord {
        record_id: id("memory:1"),
        revision: revision(revision_value),
        kind: MemoryKind::Fact,
        content_digest: digest(format!("content:{revision_value}").as_bytes()),
        predecessor_digest: predecessor,
        citations: Vec::new(),
        state,
    }
}

fn store() -> CognitiveStore {
    let Ok(value) = CognitiveStore::new(8) else {
        panic!("test store must initialize");
    };
    value
}

fn must<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("test operation failed: {error:?}"),
    }
}

#[test]
fn append_and_correction_are_predecessor_fenced() {
    let mut value = store();
    let first = record(1, None, RecordState::Live);
    let first_digest = first.record_digest();
    assert!(value.append(first, None).is_ok());
    let second = record(2, Some(first_digest), RecordState::Live);
    let Ok(receipt) = value.append(second, Some(first_digest)) else {
        panic!("fenced correction must succeed");
    };
    assert!(!receipt.authority.grants_any());
}

#[test]
fn stale_correction_is_rejected() {
    let mut value = store();
    let first = record(1, None, RecordState::Live);
    let first_digest = first.record_digest();
    assert!(value.append(first, None).is_ok());
    let second = record(2, Some(first_digest), RecordState::Live);
    assert_eq!(
        value.append(second, Some(digest(b"stale"))),
        Err(Error::StalePredecessor)
    );
}

#[test]
fn tombstone_prevents_resurrection() {
    let mut value = store();
    let first = record(1, None, RecordState::Live);
    let first_digest = first.record_digest();
    assert!(value.append(first, None).is_ok());
    let tombstone = record(2, Some(first_digest), RecordState::Tombstone);
    let tombstone_digest = tombstone.record_digest();
    assert!(value.append(tombstone, Some(first_digest)).is_ok());
    let resurrected = record(3, Some(tombstone_digest), RecordState::Live);
    assert_eq!(
        value.append(resurrected, Some(tombstone_digest)),
        Err(Error::ResurrectionDenied)
    );
}

#[test]
fn identical_append_is_idempotent() {
    let mut value = store();
    let first = record(1, None, RecordState::Live);
    assert_eq!(
        value
            .append(first.clone(), None)
            .map(|receipt| receipt.disposition),
        Ok(AppendDisposition::Inserted)
    );
    assert_eq!(
        value.append(first, None).map(|receipt| receipt.disposition),
        Ok(AppendDisposition::Unchanged)
    );
}

#[test]
fn sequence_exhaustion_rejects_insert_without_mutating_store() {
    let mut value = store();
    value.sequence = must(LogicalSequence::new(u64::MAX));
    let before = value.clone();

    assert_eq!(
        value.append(record(1, None, RecordState::Live), None),
        Err(Error::SequenceOverflow)
    );
    assert_eq!(value, before);
}

#[test]
fn sequence_exhaustion_rejects_correction_without_mutating_store() {
    let mut value = store();
    let first = record(1, None, RecordState::Live);
    let predecessor = first.record_digest();
    must(value.append(first, None));
    value.sequence = must(LogicalSequence::new(u64::MAX));
    let before = value.clone();

    assert_eq!(
        value.append(
            record(2, Some(predecessor), RecordState::Tombstone),
            Some(predecessor)
        ),
        Err(Error::SequenceOverflow)
    );
    assert_eq!(value, before);
}

#[test]
fn exhausted_revision_cannot_be_reused_for_changed_content() {
    let mut value = store();
    let first = record(u64::MAX, Some(digest(b"predecessor")), RecordState::Live);
    let predecessor = first.record_digest();
    value.records.insert(
        first.record_id.clone(),
        StoredRecord {
            record: first,
            sequence: value.sequence,
        },
    );
    let before = value.clone();

    assert_eq!(
        value.append(
            record(u64::MAX, Some(predecessor), RecordState::Tombstone),
            Some(predecessor)
        ),
        Err(Error::RevisionNotAdvanced)
    );
    assert_eq!(value, before);
}

#[test]
fn identical_retry_still_succeeds_at_sequence_exhaustion() {
    let mut value = store();
    let first = record(1, None, RecordState::Live);
    must(value.append(first.clone(), None));
    value.sequence = must(LogicalSequence::new(u64::MAX));
    let before = value.clone();

    assert_eq!(
        value.append(first, None).map(|receipt| receipt.disposition),
        Ok(AppendDisposition::Unchanged)
    );
    assert_eq!(value, before);
}

#[test]
fn retry_after_unrelated_append_preserves_original_commit_sequence() {
    let mut value = store();
    let first = record(1, None, RecordState::Live);
    let mut expected = must(value.append(first.clone(), None));
    let mut unrelated = first.clone();
    unrelated.record_id = id("memory:2");
    must(value.append(unrelated, None));
    expected.disposition = AppendDisposition::Unchanged;

    assert_eq!(value.append(first, None), Ok(expected));
}
