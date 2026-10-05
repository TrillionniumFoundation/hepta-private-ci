mod common;

#[path = "common/snapshot.rs"]
mod snapshot;

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

fn wal_path(path: &std::path::Path) -> std::path::PathBuf {
    let mut name = path.as_os_str().to_os_string();
    name.push(".wal");
    name.into()
}

// Exercise the real bounded WAL checkpoint policy without a test-only flush API.
fn advance_to_checkpoint(
    journal: &mut OperationJournal,
) -> Result<(), hepta_native::error::ShellError> {
    while journal.capacity().wal_entries != 0 {
        let mut record = prepared();
        record.key.operation_id = format!("checkpoint.{}", journal.all().len());
        journal.upsert(record)?;
    }
    Ok(())
}

#[test]
fn terminal_observation_cannot_be_rewritten_even_with_same_operation_binding() {
    let root = private_tempdir();
    let path = root.path().join("operations.json");
    let mut journal = OperationJournal::open(&path).unwrap();
    let receipt = terminal();
    journal.upsert(receipt.clone()).unwrap();
    let before = std::fs::read(wal_path(&path)).unwrap();
    journal.upsert(receipt.clone()).unwrap();
    let mut conflicting = receipt.clone();
    conflicting.terminal_status = Some(TerminalStatus::Failed);
    assert!(journal.upsert(conflicting).is_err());
    let mut conflicting = receipt.clone();
    conflicting.outcome_digest = Some("5".repeat(64));
    assert!(journal.upsert(conflicting).is_err());
    assert_eq!(std::fs::read(wal_path(&path)).unwrap(), before);
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

#[cfg(unix)]
#[test]
fn journal_rejects_a_dangling_lock_without_creating_its_target() {
    let root = private_tempdir();
    let path = root.path().join("operations.json");
    let target = root.path().join("unrelated-state");
    std::os::unix::fs::symlink(&target, path.with_extension("lock")).unwrap();

    assert!(OperationJournal::open(path).is_err());
    assert!(!target.exists());
}

#[cfg(unix)]
#[test]
fn journal_rejects_a_replaced_root_before_writing_under_another_owner() {
    let parent = private_tempdir();
    let root = parent.path().join("native-state");
    let path = root.join("operations.json");
    let mut journal = OperationJournal::open(&path).unwrap();
    let record = prepared();
    journal.upsert(record.clone()).unwrap();
    std::fs::rename(&root, parent.path().join("original-state")).unwrap();

    let _replacement_owner = OperationJournal::open(&path).unwrap();
    assert!(journal.ensure_healthy().is_err());
    assert!(
        journal
            .upsert(OperationRecord {
                phase: OperationPhase::Invoking,
                ..record.clone()
            })
            .is_err()
    );
    assert_eq!(journal.find(&record.key), Some(&record));
    assert!(!root.join("operations.json.wal").exists());
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
    snapshot::write_private_json(&path, &state);
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
    advance_to_checkpoint(&mut journal).unwrap();
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
    let wal = wal_path(&path);
    std::fs::rename(&wal, &backup).unwrap();
    std::fs::create_dir(&wal).unwrap();
    let invoking = OperationRecord {
        phase: OperationPhase::Invoking,
        ..record.clone()
    };
    assert!(journal.upsert(invoking.clone()).is_err());
    std::fs::remove_dir(&wal).unwrap();
    std::fs::rename(&backup, &wal).unwrap();
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
    // Legacy duplicate-frontier validation remains independent of v6 segments.
    state["schema"] = "hepta.native-operation-journal.v3".into();
    state.as_object_mut().unwrap().remove("checksum");
    state
        .as_object_mut()
        .unwrap()
        .remove("retirement_checkpoint");
    state.as_object_mut().unwrap().remove("wal_sequence");
    state.as_object_mut().unwrap().remove("wal_frontier");
    state["retired_operation_digests"] = serde_json::json!(["1".repeat(64), "1".repeat(64)]);
    std::fs::write(&path, serde_json::to_vec(&state).unwrap()).unwrap();
    assert!(OperationJournal::open(&path).is_err());
}

#[test]
fn legacy_v2_journal_recovers_wal_and_migrates_at_the_next_checkpoint() {
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
    let record = prepared();
    journal.upsert(record.clone()).unwrap();
    drop(journal);
    let mut journal = OperationJournal::open(&path).unwrap();
    assert_eq!(journal.find(&record.key), Some(&record));
    advance_to_checkpoint(&mut journal).unwrap();
    drop(journal);
    let state: serde_json::Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    assert_eq!(state["schema"], "hepta.native-operation-journal.v7");
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

#[test]
fn valid_json_content_corruption_is_detected_without_falling_back() {
    let root = private_tempdir();
    let path = root.path().join("operations.json");
    let mut journal = OperationJournal::open(&path).unwrap();
    journal.upsert(prepared()).unwrap();
    advance_to_checkpoint(&mut journal).unwrap();
    journal.upsert(terminal()).unwrap();
    advance_to_checkpoint(&mut journal).unwrap();
    drop(journal);
    let backup = root.path().join("operations.json.previous");
    let checkpoint = std::fs::read(&backup).unwrap();
    let mut state: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    state["operations"][0]["payload_digest"] = "9".repeat(64).into();
    let corrupted = serde_json::to_vec(&state).unwrap();
    std::fs::write(&path, &corrupted).unwrap();
    assert!(OperationJournal::open(&path).is_err());
    assert_eq!(std::fs::read(&path).unwrap(), corrupted);
    assert_eq!(std::fs::read(&backup).unwrap(), checkpoint);
}

#[test]
fn missing_primary_never_replays_the_older_prepared_checkpoint() {
    let root = private_tempdir();
    let path = root.path().join("operations.json");
    let mut journal = OperationJournal::open(&path).unwrap();
    journal.upsert(prepared()).unwrap();
    advance_to_checkpoint(&mut journal).unwrap();
    journal.upsert(terminal()).unwrap();
    advance_to_checkpoint(&mut journal).unwrap();
    drop(journal);
    std::fs::remove_file(&path).unwrap();
    assert!(OperationJournal::open(&path).is_err());
    assert!(!path.exists());
}

#[test]
fn corruption_while_owned_is_not_overwritten_by_a_new_checkpoint() {
    let root = private_tempdir();
    let path = root.path().join("operations.json");
    let mut journal = OperationJournal::open(&path).unwrap();
    journal.upsert(prepared()).unwrap();
    advance_to_checkpoint(&mut journal).unwrap();
    std::fs::write(&path, b"truncated").unwrap();
    journal.upsert(terminal()).unwrap();
    assert!(advance_to_checkpoint(&mut journal).is_err());
    assert!(journal.ensure_healthy().is_err());
    assert_eq!(std::fs::read(&path).unwrap(), b"truncated");
}

#[test]
fn exact_duplicate_does_not_append_a_new_wal_entry() {
    let root = private_tempdir();
    let path = root.path().join("operations.json");
    let mut journal = OperationJournal::open(&path).unwrap();
    let record = prepared();
    journal.upsert(record.clone()).unwrap();
    let before = std::fs::read(wal_path(&path)).unwrap();
    journal.upsert(record).unwrap();
    assert_eq!(std::fs::read(wal_path(&path)).unwrap(), before);
    assert!(!root.path().join("operations.json.previous").exists());
}

#[test]
fn closing_observation_is_unknown_immutable_and_retired_without_replay() {
    let root = private_tempdir();
    let path = root.path().join("operations.json");
    let mut journal = OperationJournal::open(&path).unwrap();
    let record = OperationRecord {
        phase: OperationPhase::Indeterminate,
        ..prepared()
    };
    journal.upsert(record.clone()).unwrap();
    let receipt = journal.close_observation(&record.key).unwrap();
    assert!(!receipt.terminal_observed);
    assert!(receipt.observation_closed);
    assert_eq!(receipt.terminal_status, None);
    assert_eq!(receipt.outcome_digest, None);
    assert_eq!(journal.pending().count(), 0);
    assert_eq!(journal.close_observation(&record.key).unwrap(), receipt);
    assert!(journal.upsert(terminal()).is_err());
    drop(journal);
    let mut reopened = OperationJournal::open(&path).unwrap();
    assert_eq!(reopened.find(&record.key).unwrap().receipt(), receipt);
    reopened.compact_closed_history(0).unwrap();
    drop(reopened);
    let mut reopened = OperationJournal::open(&path).unwrap();
    assert!(reopened.upsert(record.clone()).is_err());
    assert!(
        reopened
            .ensure_not_retired(&record.endpoint_id, &record.key)
            .is_err()
    );
}

#[test]
fn live_invocation_and_prepared_intent_cannot_be_archived() {
    let root = private_tempdir();
    let mut journal = OperationJournal::open(root.path().join("operations.json")).unwrap();
    let record = prepared();
    journal.upsert(record.clone()).unwrap();
    assert!(journal.close_observation(&record.key).is_err());
    journal
        .upsert(OperationRecord {
            phase: OperationPhase::Invoking,
            ..record.clone()
        })
        .unwrap();
    assert!(journal.close_observation(&record.key).is_err());
    assert_eq!(journal.pending().count(), 1);
}

#[test]
fn closed_unknown_batches_survive_restart_without_accumulating_pending_records() {
    let root = private_tempdir();
    let path = root.path().join("operations.json");
    let mut first = None;
    for batch in 0..4 {
        let mut journal = OperationJournal::open(&path).unwrap();
        for index in 0..32 {
            let mut record = prepared();
            record.key.operation_id = format!("operation.{batch}.{index}");
            record.phase = OperationPhase::Indeterminate;
            if first.is_none() {
                first = Some(record.clone());
            }
            journal.upsert(record.clone()).unwrap();
            journal.close_observation(&record.key).unwrap();
        }
        journal.compact_closed_history(8).unwrap();
        assert_eq!(journal.pending().count(), 0);
        assert!(journal.all().len() <= 8);
    }
    let reopened = OperationJournal::open(&path).unwrap();
    let first = first.unwrap();
    assert!(
        reopened
            .ensure_not_retired(&first.endpoint_id, &first.key)
            .is_err()
    );
    assert_eq!(reopened.capacity().retired_identities, 120);
}

#[test]
fn v4_cannot_smuggle_v5_observation_closure() {
    let root = private_tempdir();
    let path = root.path().join("operations.json");
    let mut journal = OperationJournal::open(&path).unwrap();
    let record = OperationRecord {
        phase: OperationPhase::Indeterminate,
        ..prepared()
    };
    journal.upsert(record.clone()).unwrap();
    journal.close_observation(&record.key).unwrap();
    advance_to_checkpoint(&mut journal).unwrap();
    drop(journal);
    let mut state: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    state["schema"] = "hepta.native-operation-journal.v4".into();
    state.as_object_mut().unwrap().remove("wal_sequence");
    state.as_object_mut().unwrap().remove("wal_frontier");
    state["checksum"] = hepta_native::model::sha256_hex(
        serde_json::to_vec(&(
            &state["schema"],
            &state["operations"],
            &state["retired_operation_digests"],
        ))
        .unwrap(),
    )
    .into();
    std::fs::write(&path, serde_json::to_vec(&state).unwrap()).unwrap();
    assert!(OperationJournal::open(&path).is_err());
}

#[test]
fn receipt_exposes_only_legal_observation_closure() {
    let mut value = prepared();
    assert!(!value.receipt().can_close_observation);
    value.phase = OperationPhase::Invoking;
    assert!(!value.receipt().can_close_observation);
    value.phase = OperationPhase::Indeterminate;
    assert!(value.receipt().can_close_observation);
    value.phase = OperationPhase::ObservationClosed;
    assert!(!value.receipt().can_close_observation);
    assert!(!value.receipt().terminal_observed);
    assert!(value.receipt().may_have_executed);
}
