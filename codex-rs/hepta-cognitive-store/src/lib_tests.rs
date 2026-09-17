use super::*;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Revision;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tempfile::TempDir;

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

fn store() -> QualificationCognitiveStoreV1 {
    let Ok(value) = QualificationCognitiveStoreV1::new(8) else {
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

fn durable_agent_id() -> AgentId {
    AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2cee").expect("valid agent id")
}

async fn durable_store(temp: &TempDir) -> CognitiveStore {
    let fleet_root = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet_root).expect("fleet root");
    let fleet = HeptaFleetRoot::parse(fleet_root.canonicalize().expect("canonical fleet"))
        .expect("parse fleet root");
    CognitiveStore::open(&fleet.layout().agent(&durable_agent_id()))
        .await
        .expect("open durable store")
}

fn production_authority(agent_id: AgentId, marker: &[u8]) -> ProductionAuthorityLease {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system clock")
        .as_secs();
    ProductionAuthorityLease::from_verified_parts(
        agent_id,
        Sha256Digest::for_bytes(marker),
        41,
        7,
        now + 3_600,
        ProductionAuthorityToken::from_verified_bytes(
            [b"authority-token:".as_slice(), marker].concat(),
        )
        .expect("authority token"),
    )
    .expect("authority lease")
}

struct AllowVerifier;

impl ProductionAuthorityVerifier for AllowVerifier {
    fn verify(
        &self,
        _authority: &ProductionAuthorityLease,
        _expected_agent: &AgentId,
    ) -> Result<(), String> {
        Ok(())
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

#[tokio::test]
async fn production_authority_lock_blocks_distinct_live_leases_for_same_owner() {
    let temp = TempDir::new().expect("temp dir");
    let store = durable_store(&temp).await;
    let owner = store.owner_agent_id().clone();
    let first = ProductionDurableWriter::open(
        store.clone(),
        production_authority(owner.clone(), b"grant-a"),
        &AllowVerifier,
        "production:authority:a",
        1,
    )
    .await
    .expect("first authority writer");

    let denied = ProductionDurableWriter::open(
        store.clone(),
        production_authority(owner.clone(), b"grant-b"),
        &AllowVerifier,
        "production:authority:b",
        1,
    )
    .await
    .expect_err("a second lease must not become a concurrent product writer");
    assert!(matches!(denied, ProductionWriterError::WriterBusy));

    first.release().await.expect("release first lease");
    drop(first);
    ProductionDurableWriter::open(
        store,
        production_authority(owner, b"grant-b"),
        &AllowVerifier,
        "production:authority:b",
        1,
    )
    .await
    .expect("released owner lock permits the next fenced lease");
}
