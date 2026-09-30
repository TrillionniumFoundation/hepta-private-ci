mod common;

#[path = "common/snapshot.rs"]
mod snapshot;

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
    snapshot::write_private_json(
        &path,
        &serde_json::json!({
            "schema": "hepta.native-operation-journal.v3",
            "operations": [record.clone()],
            "retired_operation_digests": legacy,
        }),
    );
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
    // A pre-WAL checkpoint models the durable snapshot at this publication
    // boundary without requiring each modern transition to rewrite it.
    let schema = "hepta.native-operation-journal.v5";
    let operations = vec![journal.find(&record.key).unwrap().clone()];
    let retired_operation_digests = Vec::<String>::new();
    let checksum =
        sha256_hex(serde_json::to_vec(&(schema, &operations, &retired_operation_digests)).unwrap());
    let pre_retirement = serde_json::json!({
        "schema": schema,
        "operations": operations,
        "retired_operation_digests": retired_operation_digests,
        "checksum": checksum,
    });
    journal.compact_closed_history(0).unwrap();
    drop(journal);
    // Simulate the durable publication boundary, retaining the new segment head.
    snapshot::write_private_json(&path, &pre_retirement);
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
    let live = serde_json::json!({
        "schema": "hepta.native-operation-journal.v2",
        "operations": [record.clone()],
    });
    journal.close_observation(&record.key).unwrap();
    journal.compact_closed_history(0).unwrap();
    drop(journal);
    snapshot::write_private_json(&path, &live);
    assert!(
        OperationJournal::open(&path)
            .unwrap_err()
            .to_string()
            .contains("rollback")
    );
}

#[test]
fn a_closed_checkpoint_cannot_replace_a_committed_archive_with_changed_evidence() {
    let temp = private_tempdir();
    let path = temp.path().join("operations.json");
    let record = unknown("operation.changed-archive");
    let mut journal = OperationJournal::open(&path).unwrap();
    journal.upsert(record.clone()).unwrap();
    journal.close_observation(&record.key).unwrap();
    let mut changed = journal.find(&record.key).unwrap().clone();
    changed.payload_digest = "9".repeat(64);
    journal.compact_closed_history(0).unwrap();
    drop(journal);
    let schema = "hepta.native-operation-journal.v5";
    let operations = vec![changed];
    let retired_operation_digests = Vec::<String>::new();
    let checksum =
        sha256_hex(serde_json::to_vec(&(schema, &operations, &retired_operation_digests)).unwrap());
    snapshot::write_private_json(
        &path,
        &serde_json::json!({
            "schema": schema,
            "operations": operations,
            "retired_operation_digests": retired_operation_digests,
            "checksum": checksum,
        }),
    );
    assert!(
        OperationJournal::open(&path)
            .unwrap_err()
            .to_string()
            .contains("differs from its durable archive")
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

#[test]
fn archive_retains_unknown_receipt_across_restart_without_replay() {
    let temp = private_tempdir();
    let path = temp.path().join("operations.json");
    let record = unknown("operation.archived");
    let mut journal = OperationJournal::open(&path).unwrap();
    journal.upsert(record.clone()).unwrap();
    let closed = journal.close_observation(&record.key).unwrap();
    journal.compact_closed_history(0).unwrap();
    drop(journal);
    let mut journal = OperationJournal::open(&path).unwrap();
    let archived = journal
        .archived_record(&record.endpoint_id, &record.key)
        .unwrap()
        .unwrap();
    assert_eq!(archived.receipt(), closed);
    assert_eq!(archived.phase, OperationPhase::ObservationClosed);
    assert!(archived.terminal_status.is_none());
    assert!(archived.outcome_digest.is_none());
    assert_eq!(journal.capacity().active_records, 0);
    assert!(
        journal
            .ensure_not_retired(&record.endpoint_id, &record.key)
            .is_err()
    );
    assert!(journal.upsert(record.clone()).is_err());
    assert!(
        journal
            .archived_record("other.endpoint", &record.key)
            .unwrap()
            .is_none()
    );
}

#[test]
fn missing_or_modified_archive_never_becomes_a_new_operation() {
    for corrupt in [false, true] {
        let temp = private_tempdir();
        let path = temp.path().join("operations.json");
        let record = unknown("operation.archive-integrity");
        let mut journal = OperationJournal::open(&path).unwrap();
        journal.upsert(record.clone()).unwrap();
        journal.close_observation(&record.key).unwrap();
        journal.compact_closed_history(0).unwrap();
        drop(journal);
        let archived = std::fs::read_dir(temp.path().join("operations.json.retirement"))
            .unwrap()
            .map(|entry| entry.unwrap().path())
            .find(|path| {
                path.file_name()
                    .unwrap()
                    .to_string_lossy()
                    .starts_with("record-")
            })
            .unwrap();
        if corrupt {
            std::fs::write(archived, b"{}").unwrap();
        } else {
            std::fs::remove_file(archived).unwrap();
        }
        let mut journal = OperationJournal::open(&path).unwrap();
        assert!(
            journal
                .archived_record(&record.endpoint_id, &record.key)
                .is_err()
        );
        assert!(
            journal
                .ensure_not_retired(&record.endpoint_id, &record.key)
                .is_err()
        );
        assert!(journal.upsert(record).is_err());
    }
}

#[test]
fn retirement_failure_keeps_active_evidence_and_fences_the_owner() {
    let temp = private_tempdir();
    let path = temp.path().join("operations.json");
    let record = unknown("operation.archive-fault");
    let mut journal = OperationJournal::open(&path).unwrap();
    journal.upsert(record.clone()).unwrap();
    journal.close_observation(&record.key).unwrap();
    let closed = journal.find(&record.key).unwrap().clone();
    let directory = temp.path().join("operations.json.retirement");
    hepta_native::private_state::PrivateStateRoot::open(directory.clone()).unwrap();
    // A complete empty head is followed by a conflicting immutable record path.
    let head = serde_json::json!({"schema":"hepta.native-retirement.v1", "checkpoint":{"head":null,"count":0}});
    std::fs::write(
        directory.join("head.json"),
        serde_json::to_vec(&head).unwrap(),
    )
    .unwrap();
    let digest = sha256_hex(serde_json::to_vec(&closed).unwrap());
    std::fs::create_dir(directory.join(format!("record-{digest}.json"))).unwrap();
    assert!(journal.compact_closed_history(0).is_err());
    assert!(journal.ensure_healthy().is_err());
    assert_eq!(journal.find(&record.key), Some(&closed));
    drop(journal);
    let journal = OperationJournal::open(&path).unwrap();
    assert_eq!(journal.find(&record.key), Some(&closed));
    assert_eq!(journal.retired_count(), 0);
}

#[test]
fn repeated_restart_compaction_keeps_old_receipts_and_reclaims_capacity() {
    let temp = private_tempdir();
    let path = temp.path().join("operations.json");
    for cycle in 0..3 {
        let mut journal = OperationJournal::open(&path).unwrap();
        for index in 0..24 {
            let record = unknown(&format!("operation.{cycle}.{index}"));
            journal.upsert(record.clone()).unwrap();
            journal.close_observation(&record.key).unwrap();
        }
        journal.compact_closed_history(0).unwrap();
        assert_eq!(journal.capacity().active_records, 0);
        assert_eq!(journal.retired_count(), (cycle + 1) * 24);
    }
    let journal = OperationJournal::open(&path).unwrap();
    for cycle in 0..3 {
        for index in 0..24 {
            let record = unknown(&format!("operation.{cycle}.{index}"));
            let archived = journal
                .archived_record(&record.endpoint_id, &record.key)
                .unwrap()
                .unwrap();
            assert!(archived.receipt().observation_closed);
            assert!(!archived.receipt().terminal_observed);
        }
    }
}
