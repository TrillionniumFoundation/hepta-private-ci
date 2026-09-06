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
