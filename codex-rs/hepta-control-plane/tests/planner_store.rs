#![cfg(unix)]

use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_control_plane::PlannerCheckpointAnchorV1;
use codex_hepta_control_plane::PlannerDecisionEnvelopeV1;
use codex_hepta_control_plane::PlannerStoreCheckpointV1;
use codex_hepta_control_plane::PlannerStoreError;
use codex_hepta_control_plane::PlannerStoreRecordKindV1;
use codex_hepta_control_plane::PlannerStoreV1;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

#[derive(Clone)]
struct TestAnchor {
    current: Arc<Mutex<PlannerStoreCheckpointV1>>,
    fail_before_commit: bool,
    fail_after_commit: bool,
}

impl PlannerCheckpointAnchorV1 for TestAnchor {
    fn load(&mut self, id: Digest32) -> Result<PlannerStoreCheckpointV1, PlannerStoreError> {
        let checkpoint = *self.current.lock().unwrap();
        if checkpoint.store_id != id {
            return Err(PlannerStoreError::AnchorMismatch);
        }
        Ok(checkpoint)
    }

    fn advance(
        &mut self,
        expected: PlannerStoreCheckpointV1,
        next: PlannerStoreCheckpointV1,
    ) -> Result<(), PlannerStoreError> {
        if self.fail_before_commit {
            return Err(PlannerStoreError::AnchorUnavailable);
        }
        let mut current = self.current.lock().unwrap();
        if *current != expected {
            return Err(PlannerStoreError::AnchorMismatch);
        }
        *current = next;
        if self.fail_after_commit {
            return Err(PlannerStoreError::AnchorUnavailable);
        }
        Ok(())
    }
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn anchor() -> TestAnchor {
    TestAnchor {
        current: Arc::new(Mutex::new(PlannerStoreCheckpointV1 {
            store_id: digest(b"store"),
            sequence: 0,
            head_digest: Digest32::ZERO,
        })),
        fail_before_commit: false,
        fail_after_commit: false,
    }
}

fn private_directory() -> tempfile::TempDir {
    let directory = tempfile::tempdir().unwrap();
    fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o700)).unwrap();
    directory
}

fn envelope() -> Vec<u8> {
    PlannerDecisionEnvelopeV1 {
        codec_digest: digest(b"test-only-owner-codec"),
        snapshot: b"complete snapshot fixture".to_vec(),
        prepared_plan: b"complete prepared fixture".to_vec(),
        ndu_evaluation: b"complete evaluation fixture".to_vec(),
        plan_receipt: b"complete receipt fixture".to_vec(),
    }
    .encode()
    .unwrap()
}

#[test]
fn envelope_round_trip_rejects_truncation_and_trailing_bytes() {
    let bytes = envelope();
    assert_eq!(
        PlannerDecisionEnvelopeV1::decode(&bytes)
            .unwrap()
            .encode()
            .unwrap(),
        bytes
    );
    for end in 0..bytes.len() {
        assert!(PlannerDecisionEnvelopeV1::decode(&bytes[..end]).is_err());
    }
    let mut extra = bytes;
    extra.push(0);
    assert!(PlannerDecisionEnvelopeV1::decode(&extra).is_err());
}

#[test]
fn full_body_reopen_idempotency_and_single_writer() {
    let directory = private_directory();
    let anchor = anchor();
    let id = digest(b"store");
    let mut store = PlannerStoreV1::create(directory.path(), id, anchor.clone()).unwrap();
    assert!(matches!(
        PlannerStoreV1::open(directory.path(), id, anchor.clone()),
        Err(PlannerStoreError::Busy)
    ));
    let first = store
        .append(
            PlannerStoreRecordKindV1::Decision,
            digest(b"operation"),
            digest(b"decision"),
            &envelope(),
        )
        .unwrap();
    assert_eq!(
        store
            .append(
                PlannerStoreRecordKindV1::Decision,
                digest(b"operation"),
                digest(b"decision"),
                &envelope(),
            )
            .unwrap(),
        first
    );
    assert!(matches!(
        store.append(
            PlannerStoreRecordKindV1::Observation,
            digest(b"operation"),
            digest(b"decision"),
            b"different semantics",
        ),
        Err(PlannerStoreError::IdentityConflict)
    ));
    let expected = store.records().to_vec();
    drop(store);
    let reopened = PlannerStoreV1::open(directory.path(), id, anchor).unwrap();
    assert_eq!(reopened.records(), expected);
    assert_eq!(reopened.records()[0].body, envelope());
}

#[test]
fn partial_unacknowledged_tail_is_removed_but_committed_truncation_rejects() {
    let directory = private_directory();
    let anchor = anchor();
    let id = digest(b"store");
    let mut store = PlannerStoreV1::create(directory.path(), id, anchor.clone()).unwrap();
    store
        .append(
            PlannerStoreRecordKindV1::Decision,
            digest(b"operation"),
            digest(b"decision"),
            &envelope(),
        )
        .unwrap();
    drop(store);
    let path = directory.path().join("planner.log");
    let committed = fs::read(&path).unwrap();
    let mut file = OpenOptions::new().append(true).open(&path).unwrap();
    file.write_all(b"torn next frame").unwrap();
    file.sync_all().unwrap();
    drop(file);
    let reopened = PlannerStoreV1::open(directory.path(), id, anchor.clone()).unwrap();
    assert_eq!(reopened.records().len(), 1);
    assert_eq!(fs::read(&path).unwrap(), committed);
    drop(reopened);
    OpenOptions::new()
        .write(true)
        .open(&path)
        .unwrap()
        .set_len(committed.len() as u64 - 1)
        .unwrap();
    assert!(PlannerStoreV1::open(directory.path(), id, anchor).is_err());
}

#[test]
fn complete_frame_corruption_fails_closed() {
    let directory = private_directory();
    let anchor = anchor();
    let id = digest(b"store");
    let mut store = PlannerStoreV1::create(directory.path(), id, anchor.clone()).unwrap();
    store
        .append(
            PlannerStoreRecordKindV1::Decision,
            digest(b"operation"),
            digest(b"decision"),
            &envelope(),
        )
        .unwrap();
    drop(store);
    let path = directory.path().join("planner.log");
    let mut bytes = fs::read(&path).unwrap();
    let last = bytes.len() - 1;
    bytes[last] ^= 1;
    fs::write(path, bytes).unwrap();
    assert!(PlannerStoreV1::open(directory.path(), id, anchor).is_err());
}

#[test]
fn uncertain_anchor_outcome_fences_and_reopen_resolves_both_cases() {
    for committed in [false, true] {
        let directory = private_directory();
        let anchor = anchor();
        let id = digest(b"store");
        let failing = TestAnchor {
            fail_before_commit: !committed,
            fail_after_commit: committed,
            ..anchor.clone()
        };
        let mut store = PlannerStoreV1::create(directory.path(), id, failing).unwrap();
        assert!(matches!(
            store.append(
                PlannerStoreRecordKindV1::Decision,
                digest(b"operation"),
                digest(b"decision"),
                &envelope(),
            ),
            Err(PlannerStoreError::AnchorUnavailable)
        ));
        assert!(matches!(
            store.append(
                PlannerStoreRecordKindV1::Observation,
                digest(b"retry"),
                digest(b"decision"),
                b"must not append after uncertainty",
            ),
            Err(PlannerStoreError::Fenced)
        ));
        drop(store);
        let reopened = PlannerStoreV1::open(directory.path(), id, anchor).unwrap();
        assert_eq!(reopened.records().len(), usize::from(committed));
    }
}

#[test]
fn revocation_survives_checkpoint_and_old_backup_cannot_resurrect_selection() {
    let directory = private_directory();
    let backups = private_directory();
    let restore = private_directory();
    let anchor = anchor();
    let id = digest(b"store");
    let decision = digest(b"decision");
    let mut store = PlannerStoreV1::create(directory.path(), id, anchor.clone()).unwrap();
    store
        .append(
            PlannerStoreRecordKindV1::Decision,
            digest(b"create"),
            decision,
            &envelope(),
        )
        .unwrap();
    store
        .append(
            PlannerStoreRecordKindV1::Selected,
            digest(b"select"),
            decision,
            b"selected",
        )
        .unwrap();
    let old_backup = backups.path().join("before-revocation.bin");
    store.backup(&old_backup).unwrap();
    store
        .append(
            PlannerStoreRecordKindV1::Revoked,
            digest(b"revoke"),
            decision,
            b"owner revocation evidence",
        )
        .unwrap();
    store.checkpoint_file().unwrap();
    assert_eq!(store.selected_decision(), None);
    drop(store);
    let mut reopened = PlannerStoreV1::open(directory.path(), id, anchor.clone()).unwrap();
    assert_eq!(reopened.selected_decision(), None);
    assert!(matches!(
        reopened.append(
            PlannerStoreRecordKindV1::Selected,
            digest(b"reselect"),
            decision,
            b"selected again",
        ),
        Err(PlannerStoreError::Revoked)
    ));
    assert!(matches!(
        PlannerStoreV1::restore(restore.path(), id, &old_backup, anchor.clone()),
        Err(PlannerStoreError::StaleBackup)
    ));
    let current_backup = backups.path().join("after-revocation.bin");
    reopened.backup(&current_backup).unwrap();
    let new_restore = private_directory();
    let restored =
        PlannerStoreV1::restore(new_restore.path(), id, &current_backup, anchor).unwrap();
    assert_eq!(restored.records(), reopened.records());
    assert_eq!(restored.selected_decision(), None);
}

#[test]
fn unknown_decision_selection_and_unknown_schema_reject() {
    let directory = private_directory();
    let anchor = anchor();
    let id = digest(b"store");
    let mut store = PlannerStoreV1::create(directory.path(), id, anchor.clone()).unwrap();
    assert!(matches!(
        store.append(
            PlannerStoreRecordKindV1::Selected,
            digest(b"select"),
            digest(b"missing"),
            b"selection",
        ),
        Err(PlannerStoreError::DecisionNotRecorded)
    ));
    drop(store);
    let path = directory.path().join("planner.log");
    let mut bytes = fs::read(&path).unwrap();
    bytes[8..12].copy_from_slice(&2_u32.to_be_bytes());
    fs::write(path, bytes).unwrap();
    assert!(matches!(
        PlannerStoreV1::open(directory.path(), id, anchor),
        Err(PlannerStoreError::UnsupportedSchema)
    ));
}
