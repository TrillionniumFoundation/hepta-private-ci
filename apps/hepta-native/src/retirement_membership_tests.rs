use super::MAX_MEMBERSHIP_QUERIES;
use super::RetirementMembership;
use super::RetirementStore;
use crate::journal::OperationPhase;
use crate::journal::OperationRecord;
use crate::journal::retirement_digest;
use crate::model::OperationKey;
use crate::model::PlatformAction;
use crate::model::TerminalStatus;
use crate::model::sha256_hex;

fn terminal() -> OperationRecord {
    OperationRecord {
        endpoint_id: "runtime.membership".to_owned(),
        key: OperationKey {
            session_id: "session.membership".to_owned(),
            session_generation: 1,
            operation_id: "operation.archived".to_owned(),
        },
        subject_id: "operator.membership".to_owned(),
        displayed_revision: 1,
        action: PlatformAction::CopyText,
        payload_digest: "1".repeat(64),
        binding_digest: "2".repeat(64),
        grant_digest: "3".repeat(64),
        phase: OperationPhase::Terminal,
        terminal_status: Some(TerminalStatus::Succeeded),
        outcome_digest: Some("4".repeat(64)),
    }
}

#[test]
fn mixed_membership_preserves_query_order_and_receipt_evidence_after_restart() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("operations.json");
    let record = terminal();
    let archived = retirement_digest(&record.endpoint_id, &record.key).unwrap();
    let legacy = sha256_hex("legacy.membership");
    let absent = sha256_hex("absent.membership");
    let mut store = RetirementStore::create(&path).unwrap();
    store
        .append_records(
            &[archived.clone(), legacy.clone()],
            std::slice::from_ref(&record),
        )
        .unwrap();
    let checkpoint = store.checkpoint();
    drop(store);
    let reopened = RetirementStore::open(&path, Some(&checkpoint))
        .unwrap()
        .unwrap();
    assert_eq!(
        reopened
            .memberships(&[absent, archived.clone(), legacy, archived])
            .unwrap(),
        vec![
            RetirementMembership::Absent,
            RetirementMembership::Archived(Box::new(record.clone())),
            RetirementMembership::Legacy,
            RetirementMembership::Archived(Box::new(record)),
        ]
    );
}

#[test]
fn a_warm_lookup_cache_cannot_hide_a_corrupt_or_missing_batch_bucket() {
    for missing in [false, true] {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("operations.json");
        let id = sha256_hex("legacy.membership");
        let mut store = RetirementStore::create(&path).unwrap();
        store.append(std::slice::from_ref(&id)).unwrap();
        assert!(store.contains(&id));
        let prefix = super::index_prefix(&id).unwrap();
        let bucket = store
            .root
            .path()
            .join(format!("bucket-{}.json", store.buckets[&prefix]));
        if missing {
            std::fs::remove_file(bucket).unwrap();
        } else {
            std::fs::write(bucket, b"{}").unwrap();
        }
        assert!(store.memberships(&[id]).is_err());
    }
}

#[test]
fn batch_archive_corruption_never_drops_the_closed_journal_observation() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("operations.json");
    let record = terminal();
    let id = retirement_digest(&record.endpoint_id, &record.key).unwrap();
    let mut store = RetirementStore::create(&path).unwrap();
    store
        .append_records(std::slice::from_ref(&id), &[record])
        .unwrap();
    let archive_digest = store.lookup_entry(&id).unwrap().unwrap().unwrap();
    std::fs::write(
        store
            .root
            .path()
            .join(format!("record-{archive_digest}.json")),
        b"{}",
    )
    .unwrap();
    assert!(store.memberships(&[id]).is_err());
}

#[test]
fn malformed_and_oversized_queries_are_rejected_before_membership_resolution() {
    let root = tempfile::tempdir().unwrap();
    let store = RetirementStore::create(&root.path().join("operations.json")).unwrap();
    assert!(store.memberships(&["invalid".to_owned()]).is_err());
    assert!(
        store
            .memberships(&vec![sha256_hex("valid"); MAX_MEMBERSHIP_QUERIES + 1])
            .is_err()
    );
    assert_eq!(store.memberships(&[]).unwrap(), Vec::new());
}
