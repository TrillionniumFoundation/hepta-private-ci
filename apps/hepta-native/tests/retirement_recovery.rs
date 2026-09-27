mod common;

use common::private_tempdir;
use hepta_native::journal::{OperationJournal, OperationPhase, OperationRecord};
use hepta_native::model::{OperationKey, PlatformAction, sha256_hex};

fn unknown(id: &str) -> OperationRecord {
    OperationRecord {
        endpoint_id: "endpoint.test".to_owned(),
        key: OperationKey {
            session_id: "session.test".to_owned(),
            session_generation: 1,
            operation_id: id.to_owned(),
        },
        subject_id: "subject.test".to_owned(),
        displayed_revision: 1,
        action: PlatformAction::CopyText,
        payload_digest: "1".repeat(64),
        binding_digest: "2".repeat(64),
        grant_digest: "3".repeat(64),
        phase: OperationPhase::Indeterminate,
        terminal_status: None,
        outcome_digest: None,
    }
}

#[test]
fn full_legacy_frontier_migrates_without_deleting_any_identity() {
    let temp = private_tempdir();
    let path = temp.path().join("operations.json");
    let legacy: Vec<_> = (0..32_768)
        .map(|index| sha256_hex(format!("legacy.{index}")))
        .collect();
    let record = unknown("operation.new");
    let mut journal = OperationJournal::open(&path).unwrap();
    journal.upsert(record.clone()).unwrap();
    drop(journal);
    let mut state: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    state["schema"] = "hepta.native-operation-journal.v3".into();
    state.as_object_mut().unwrap().remove("checksum");
    state
        .as_object_mut()
        .unwrap()
        .remove("retirement_checkpoint");
    state["retired_operation_digests"] = serde_json::to_value(&legacy).unwrap();
    std::fs::write(&path, serde_json::to_vec(&state).unwrap()).unwrap();
    let mut journal = OperationJournal::open(&path).unwrap();
    journal.close_observation(&record.key).unwrap();
    journal.compact_closed_history(0).unwrap();
    assert_eq!(journal.retired_count(), 32_769);
    assert_eq!(journal.capacity().retirement_limit, None);
    drop(journal);
    let mut journal = OperationJournal::open(&path).unwrap();
    assert_eq!(journal.retired_count(), 32_769);
    assert!(journal.upsert(record).is_err());
    journal
        .upsert(unknown("operation.after-migration"))
        .unwrap();
}

#[test]
fn crash_after_retirement_head_before_journal_replacement_preserves_no_replay() {
    let temp = private_tempdir();
    let path = temp.path().join("operations.json");
    let record = unknown("operation.first");
    let mut journal = OperationJournal::open(&path).unwrap();
    journal.upsert(record.clone()).unwrap();
    journal.close_observation(&record.key).unwrap();
    let pre_retirement = std::fs::read(&path).unwrap();
    journal.compact_closed_history(0).unwrap();
    drop(journal);
    // Simulate the durable publication boundary, retaining the new segment head.
    std::fs::write(&path, pre_retirement).unwrap();
    let mut journal = OperationJournal::open(&path).unwrap();
    assert_eq!(journal.pending().count(), 0);
    assert_eq!(journal.retired_count(), 1);
    assert!(journal.upsert(record).is_err());
    journal.upsert(unknown("operation.next")).unwrap();
}

#[test]
fn old_live_backup_cannot_override_newer_retirement_evidence() {
    let temp = private_tempdir();
    let path = temp.path().join("operations.json");
    let record = unknown("operation.first");
    let mut journal = OperationJournal::open(&path).unwrap();
    journal.upsert(record.clone()).unwrap();
    let live = std::fs::read(&path).unwrap();
    journal.close_observation(&record.key).unwrap();
    journal.compact_closed_history(0).unwrap();
    drop(journal);
    std::fs::write(&path, live).unwrap();
    assert!(
        OperationJournal::open(&path)
            .unwrap_err()
            .to_string()
            .contains("rollback")
    );
}

#[test]
fn referenced_retirement_directory_cannot_be_deleted_to_reset_capacity() {
    let temp = private_tempdir();
    let path = temp.path().join("operations.json");
    let record = unknown("operation.first");
    let mut journal = OperationJournal::open(&path).unwrap();
    journal.upsert(record.clone()).unwrap();
    journal.close_observation(&record.key).unwrap();
    journal.compact_closed_history(0).unwrap();
    drop(journal);
    std::fs::remove_dir_all(temp.path().join("operations.json.retirement")).unwrap();
    assert!(OperationJournal::open(&path).is_err());
}
