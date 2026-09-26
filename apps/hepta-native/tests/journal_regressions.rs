mod common;

use common::private_tempdir;
use hepta_native::journal::OperationJournal;
use hepta_native::journal::OperationPhase;
use hepta_native::journal::OperationRecord;
use hepta_native::model::OperationKey;
use hepta_native::model::PlatformAction;
use hepta_native::model::TerminalStatus;

fn prepared() -> OperationRecord {
    OperationRecord {
        endpoint_id: "runtime.one".to_owned(),
        key: OperationKey {
            session_id: "session.one".to_owned(),
            session_generation: 1,
            operation_id: "operation.one".to_owned(),
        },
        subject_id: "operator.one".to_owned(),
        displayed_revision: 1,
        action: PlatformAction::CopyText,
        payload_digest: "1".repeat(64),
        binding_digest: "2".repeat(64),
        grant_digest: "3".repeat(64),
        phase: OperationPhase::Prepared,
        terminal_status: None,
        outcome_digest: None,
    }
}

fn terminal() -> OperationRecord {
    OperationRecord {
        phase: OperationPhase::Terminal,
        terminal_status: Some(TerminalStatus::Succeeded),
        outcome_digest: Some("4".repeat(64)),
        ..prepared()
    }
}

#[test]
fn terminal_observation_cannot_be_rewritten_even_with_same_operation_binding() {
    let root = private_tempdir();
    let path = root.path().join("operations.json");
    let mut journal = OperationJournal::open(&path).unwrap();
    let receipt = terminal();
    journal.upsert(receipt.clone()).unwrap();
    let before = std::fs::read(&path).unwrap();
    journal.upsert(receipt.clone()).unwrap();
    let mut conflicting = receipt.clone();
    conflicting.terminal_status = Some(TerminalStatus::Failed);
    assert!(journal.upsert(conflicting).is_err());
    let mut conflicting = receipt.clone();
    conflicting.outcome_digest = Some("5".repeat(64));
    assert!(journal.upsert(conflicting).is_err());
    assert_eq!(std::fs::read(&path).unwrap(), before);
    drop(journal);
    let reopened = OperationJournal::open(&path).unwrap();
    assert_eq!(reopened.find(&receipt.key), Some(&receipt));
}

#[test]
fn operation_identity_cannot_move_between_endpoints() {
    let root = private_tempdir();
    let mut journal = OperationJournal::open(root.path().join("operations.json")).unwrap();
    let record = prepared();
    journal.upsert(record.clone()).unwrap();
    let mut changed = record.clone();
    changed.endpoint_id = "runtime.other".to_owned();
    assert!(journal.upsert(changed).is_err());
    assert_eq!(journal.find(&record.key), Some(&record));
}

#[test]
fn reopened_snapshot_rejects_duplicate_operation_keys() {
    let root = private_tempdir();
    let path = root.path().join("operations.json");
    let record = terminal();
    let mut journal = OperationJournal::open(&path).unwrap();
    journal.upsert(record.clone()).unwrap();
    drop(journal);
    let state = serde_json::json!({
        "schema": "hepta.native-operation-journal.v2",
        "operations": [record.clone(), record],
    });
    std::fs::write(&path, serde_json::to_vec(&state).unwrap()).unwrap();
    assert!(
        OperationJournal::open(&path)
            .unwrap_err()
            .to_string()
            .contains("duplicate")
    );
}

#[test]
fn reopened_snapshot_rejects_unknown_critical_fields() {
    let root = private_tempdir();
    let path = root.path().join("operations.json");
    let mut journal = OperationJournal::open(&path).unwrap();
    journal.upsert(prepared()).unwrap();
    drop(journal);
    let mut state: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    state["critical_future_semantics"] = true.into();
    std::fs::write(&path, serde_json::to_vec(&state).unwrap()).unwrap();
    assert!(OperationJournal::open(&path).is_err());
}

#[test]
fn failed_persistence_fences_owner_until_reopen() {
    let root = private_tempdir();
    let path = root.path().join("operations.json");
    let backup = root.path().join("saved.json");
    let mut journal = OperationJournal::open(&path).unwrap();
    let record = prepared();
    journal.upsert(record.clone()).unwrap();
    std::fs::rename(&path, &backup).unwrap();
    std::fs::create_dir(&path).unwrap();
    let invoking = OperationRecord {
        phase: OperationPhase::Invoking,
        ..record.clone()
    };
    assert!(journal.upsert(invoking.clone()).is_err());
    std::fs::remove_dir(&path).unwrap();
    std::fs::rename(&backup, &path).unwrap();
    assert!(journal.ensure_healthy().is_err());
    assert!(journal.upsert(invoking).is_err());
    drop(journal);
    let reopened = OperationJournal::open(&path).unwrap();
    reopened.ensure_healthy().unwrap();
    assert_eq!(reopened.find(&record.key), Some(&record));
}

#[test]
fn cleanup_moves_terminal_identity_to_durable_retirement_frontier() {
    let root = private_tempdir();
    let path = root.path().join("operations.json");
    let mut journal = OperationJournal::open(&path).unwrap();
    let record = terminal();
    journal.upsert(record.clone()).unwrap();
    journal.compact_terminal(0).unwrap();
    assert_eq!(journal.find(&record.key), None);
    assert_eq!(journal.retired_count(), 1);
    assert!(
        journal
            .ensure_not_retired(&record.endpoint_id, &record.key)
            .is_err()
    );
    assert!(journal.upsert(record.clone()).is_err());
    drop(journal);

    let mut reopened = OperationJournal::open(&path).unwrap();
    assert_eq!(reopened.find(&record.key), None);
    assert_eq!(reopened.retired_count(), 1);
    let mut changed = record.clone();
    changed.payload_digest = "9".repeat(64);
    assert!(reopened.upsert(changed).is_err());
}

#[test]
fn different_session_generations_do_not_share_operation_records() {
    let root = private_tempdir();
    let mut journal = OperationJournal::open(root.path().join("operations.json")).unwrap();
    let first = terminal();
    let mut next = prepared();
    next.key.session_generation = 2;
    journal.upsert(first.clone()).unwrap();
    journal.upsert(next.clone()).unwrap();
    assert_eq!(journal.find(&first.key), Some(&first));
    assert_eq!(journal.find(&next.key), Some(&next));
}

#[test]
fn retirement_keeps_requested_latest_terminal_records() {
    let root = private_tempdir();
    let path = root.path().join("operations.json");
    let mut journal = OperationJournal::open(&path).unwrap();
    let first = terminal();
    let mut second = terminal();
    second.key.operation_id = "operation.two".to_owned();
    journal.upsert(first.clone()).unwrap();
    journal.upsert(second.clone()).unwrap();
    journal.compact_terminal(1).unwrap();
    assert_eq!(journal.find(&first.key), None);
    assert_eq!(journal.find(&second.key), Some(&second));
    assert_eq!(journal.retired_count(), 1);
}

#[test]
fn duplicate_or_overlapping_retirement_frontier_is_rejected_on_reopen() {
    let root = private_tempdir();
    let path = root.path().join("operations.json");
    let record = terminal();
    let mut journal = OperationJournal::open(&path).unwrap();
    journal.upsert(record.clone()).unwrap();
    journal.compact_terminal(0).unwrap();
    drop(journal);

    let mut state: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    let digest = state["retired_operation_digests"][0].clone();
    state["retired_operation_digests"]
        .as_array_mut()
        .unwrap()
        .push(digest);
    std::fs::write(&path, serde_json::to_vec(&state).unwrap()).unwrap();
    assert!(OperationJournal::open(&path).is_err());
}

#[test]
fn legacy_v2_journal_migrates_on_first_persisted_change() {
    let root = private_tempdir();
    let path = root.path().join("operations.json");
    std::fs::write(
        &path,
        br#"{"schema":"hepta.native-operation-journal.v2","operations":[]}"#,
    )
    .unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    }
    let mut journal = OperationJournal::open(&path).unwrap();
    journal.upsert(prepared()).unwrap();
    drop(journal);
    let state: serde_json::Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    assert_eq!(state["schema"], "hepta.native-operation-journal.v3");
    assert_eq!(state["retired_operation_digests"], serde_json::json!([]));
}

#[test]
fn invoking_cannot_regress_to_prepared() {
    let root = private_tempdir();
    let mut journal = OperationJournal::open(root.path().join("operations.json")).unwrap();
    let record = prepared();
    journal.upsert(record.clone()).unwrap();
    let invoking = OperationRecord {
        phase: OperationPhase::Invoking,
        ..record.clone()
    };
    journal.upsert(invoking.clone()).unwrap();
    assert!(journal.upsert(record).is_err());
    assert_eq!(journal.find(&invoking.key), Some(&invoking));
}
