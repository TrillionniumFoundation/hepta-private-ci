use super::RetirementStore;
use crate::journal::OperationPhase;
use crate::journal::OperationRecord;
use crate::journal::retirement_digest;
use crate::model::OperationKey;
use crate::model::PlatformAction;
use crate::model::TerminalStatus;

fn terminal(operation_id: &str) -> OperationRecord {
    OperationRecord {
        endpoint_id: "runtime.one".to_owned(),
        key: OperationKey {
            session_id: "session.one".to_owned(),
            session_generation: 1,
            operation_id: operation_id.to_owned(),
        },
        subject_id: "operator.one".to_owned(),
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
fn legacy_tombstone_cannot_acquire_an_uncommitted_receipt_in_a_mixed_batch() {
    let root = tempfile::tempdir().unwrap();
    let journal = root.path().join("operations.json");
    let mut store = RetirementStore::create(&journal).unwrap();
    let old = terminal("operation.old");
    let new = terminal("operation.new");
    let old_id = retirement_digest(&old.endpoint_id, &old.key).unwrap();
    let new_id = retirement_digest(&new.endpoint_id, &new.key).unwrap();
    store.append(std::slice::from_ref(&old_id)).unwrap();
    let before = store.checkpoint();
    assert!(
        store
            .append_records(&[old_id.clone(), new_id.clone()], &[old, new])
            .is_err()
    );
    assert_eq!(store.checkpoint(), before);
    assert!(store.read_record(&old_id).unwrap().is_none());
    assert!(!store.contains(&new_id));
    drop(store);
    let reopened = RetirementStore::open(&journal, Some(&before))
        .unwrap()
        .unwrap();
    assert!(reopened.contains(&old_id));
    assert!(reopened.read_record(&old_id).unwrap().is_none());
    assert!(!reopened.contains(&new_id));
}

#[test]
fn exact_archived_duplicate_still_returns_the_same_receipt_after_restart() {
    let root = tempfile::tempdir().unwrap();
    let journal = root.path().join("operations.json");
    let mut store = RetirementStore::create(&journal).unwrap();
    let record = terminal("operation.one");
    let id = retirement_digest(&record.endpoint_id, &record.key).unwrap();
    store
        .append_records(std::slice::from_ref(&id), std::slice::from_ref(&record))
        .unwrap();
    let before = store.checkpoint();
    store
        .append_records(std::slice::from_ref(&id), std::slice::from_ref(&record))
        .unwrap();
    assert_eq!(store.checkpoint(), before);
    assert_eq!(store.read_record(&id).unwrap(), Some(record.clone()));
    drop(store);
    let reopened = RetirementStore::open(&journal, Some(&before))
        .unwrap()
        .unwrap();
    assert_eq!(reopened.read_record(&id).unwrap(), Some(record));
}
