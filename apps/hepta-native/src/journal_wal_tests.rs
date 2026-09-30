use super::OperationJournal;
use super::OperationPhase;
use super::OperationRecord;
use super::WAL_CHECKPOINT_ENTRIES;
use crate::model::OperationKey;
use crate::model::PlatformAction;

use crate::private_state_test_support::private_tempdir;

fn record(operation_id: &str, phase: OperationPhase) -> OperationRecord {
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
        phase,
        terminal_status: None,
        outcome_digest: None,
    }
}

#[test]
fn wal_recovers_prepared_and_invoking_without_blind_replay() {
    let root = private_tempdir();
    let path = root.path().join("operations.json");
    let prepared = record("operation.one", OperationPhase::Prepared);
    let key = prepared.key.clone();
    {
        let mut journal = OperationJournal::open(&path).unwrap();
        journal.upsert(prepared).unwrap();
        assert_eq!(journal.find(&key).unwrap().phase, OperationPhase::Prepared);
        assert!(!path.exists());
    }
    {
        let mut journal = OperationJournal::open(&path).unwrap();
        assert_eq!(journal.find(&key).unwrap().phase, OperationPhase::Prepared);
        journal
            .upsert(record("operation.one", OperationPhase::Invoking))
            .unwrap();
    }
    let wal = crate::journal_storage::wal_path(&path);
    use std::io::Write as _;
    let mut file = std::fs::OpenOptions::new().append(true).open(&wal).unwrap();
    file.write_all(b"HPTNWAL1\0").unwrap();
    file.sync_all().unwrap();
    drop(file);
    let journal = OperationJournal::open(&path).unwrap();
    assert_eq!(journal.find(&key).unwrap().phase, OperationPhase::Invoking);
    assert!(
        std::fs::metadata(wal).unwrap().len() > 0,
        "complete WAL frames remain until a checkpoint"
    );
}

#[test]
fn bounded_wal_checkpoints_and_reopens_with_exact_index() {
    let root = private_tempdir();
    let path = root.path().join("operations.json");
    {
        let mut journal = OperationJournal::open(&path).unwrap();
        for index in 0..WAL_CHECKPOINT_ENTRIES {
            journal
                .upsert(record(
                    &format!("operation.{index}"),
                    OperationPhase::Prepared,
                ))
                .unwrap();
        }
        assert!(path.exists());
        assert_eq!(
            std::fs::metadata(crate::journal_storage::wal_path(&path))
                .unwrap()
                .len(),
            0
        );
    }
    let journal = OperationJournal::open(&path).unwrap();
    for index in 0..WAL_CHECKPOINT_ENTRIES {
        let key = OperationKey {
            session_id: "session.one".to_owned(),
            session_generation: 1,
            operation_id: format!("operation.{index}"),
        };
        assert_eq!(journal.find(&key).unwrap().phase, OperationPhase::Prepared);
    }
}
