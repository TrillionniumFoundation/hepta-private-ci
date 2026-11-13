use std::fs::OpenOptions;
use std::io::Write;

use pretty_assertions::assert_eq;
use tempfile::tempdir;

use super::*;

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn path(root: &tempfile::TempDir, name: &str) -> PathBuf {
    root.path().join(name)
}

#[test]
fn full_decision_envelope_round_trips_and_replays_idempotently() {
    let root = tempdir().expect("temporary store root");
    let store_path = path(&root, "planner.store");
    let identity = digest("decision-operation");
    let payload = br#"{"schema":"decision.v1","candidate":"work","complete":true}"#;
    let head = {
        let mut store = PlannerStoreV1::open(&store_path, PlannerStoreOptionsV1::default())
            .expect("open planner store");
        let first = store
            .append_decision_envelope(identity, payload)
            .expect("append full decision envelope");
        let replay = store
            .append_decision_envelope(identity, payload)
            .expect("idempotent replay");
        assert_eq!(first, replay);
        assert_eq!(store.records().len(), 1);
        first.record_digest()
    };
    let reopened = PlannerStoreV1::open(&store_path, PlannerStoreOptionsV1::default())
        .expect("reopen planner store");
    assert_eq!(reopened.records().len(), 1);
    assert_eq!(reopened.records()[0].payload(), payload);
    assert_eq!(reopened.head_digest(), head);
    assert_eq!(reopened.recovered_tail_bytes(), 0);
}

#[test]
fn second_writer_is_rejected_and_stale_lock_is_recovered() {
    let root = tempdir().expect("temporary store root");
    let store_path = path(&root, "planner.store");
    let first = PlannerStoreV1::open(&store_path, PlannerStoreOptionsV1::default())
        .expect("first writer");
    assert!(matches!(
        PlannerStoreV1::open(&store_path, PlannerStoreOptionsV1::default()),
        Err(PlannerStoreError::WriterBusy)
    ));
    drop(first);
    let reopened = PlannerStoreV1::open(&store_path, PlannerStoreOptionsV1::default())
        .expect("writer after clean release");
    drop(reopened);

    let stale_lock = lock_path(&store_path);
    std::fs::write(&stale_lock, "4294967294:1").expect("write stale lock");
    let recovered = PlannerStoreV1::open(&store_path, PlannerStoreOptionsV1::default())
        .expect("recover dead-process lock");
    drop(recovered);
}

#[test]
fn partial_tail_is_truncated_to_last_complete_frame() {
    let root = tempdir().expect("temporary store root");
    let store_path = path(&root, "planner.store");
    let valid_len = {
        let mut store = PlannerStoreV1::open(&store_path, PlannerStoreOptionsV1::default())
            .expect("open planner store");
        store
            .append_decision_envelope(digest("decision"), b"complete-envelope")
            .expect("append envelope");
        std::fs::metadata(&store_path).expect("metadata").len()
    };
    let mut file = OpenOptions::new()
        .append(true)
        .open(&store_path)
        .expect("append partial tail");
    file.write_all(&23_u32.to_be_bytes())
        .expect("partial frame length");
    file.write_all(b"cut-before-frame-completes")
        .expect("partial body");
    file.sync_all().expect("persist partial tail");

    let reopened = PlannerStoreV1::open(&store_path, PlannerStoreOptionsV1::default())
        .expect("recover complete prefix");
    assert!(reopened.recovered_tail_bytes() > 0);
    assert_eq!(reopened.records().len(), 1);
    assert_eq!(
        std::fs::metadata(&store_path).expect("metadata").len(),
        valid_len
    );
}

#[test]
fn complete_tampering_fails_closed_instead_of_truncating() {
    let root = tempdir().expect("temporary store root");
    let store_path = path(&root, "planner.store");
    {
        let mut store = PlannerStoreV1::open(&store_path, PlannerStoreOptionsV1::default())
            .expect("open planner store");
        store
            .append_decision_envelope(digest("decision"), b"complete-envelope")
            .expect("append envelope");
    }
    let mut bytes = std::fs::read(&store_path).expect("read store");
    let last = bytes.last_mut().expect("payload byte");
    *last ^= 0x55;
    std::fs::write(&store_path, bytes).expect("persist tampering");
    assert!(matches!(
        PlannerStoreV1::open(&store_path, PlannerStoreOptionsV1::default()),
        Err(PlannerStoreError::CorruptFrame)
    ));
}

#[test]
fn identity_conflict_and_post_write_failpoint_poison_the_live_handle() {
    let root = tempdir().expect("temporary store root");
    let store_path = path(&root, "planner.store");
    let identity = digest("same-operation");
    {
        let mut store = PlannerStoreV1::open(&store_path, PlannerStoreOptionsV1::default())
            .expect("open planner store");
        store
            .append_decision_envelope(identity, b"first")
            .expect("first envelope");
        assert!(matches!(
            store.append_decision_envelope(identity, b"different"),
            Err(PlannerStoreError::IdentityConflict)
        ));
    }

    let fail_path = path(&root, "failpoint.store");
    let mut store = PlannerStoreV1::open(
        &fail_path,
        PlannerStoreOptionsV1 {
            failpoint: PlannerStoreFailpointV1::AfterAppendBeforeSync,
            ..PlannerStoreOptionsV1::default()
        },
    )
    .expect("open failpoint store");
    assert!(matches!(
        store.append_decision_envelope(digest("injected"), b"complete-frame"),
        Err(PlannerStoreError::InjectedFailure(
            PlannerStoreFailpointV1::AfterAppendBeforeSync
        ))
    ));
    assert!(matches!(
        store.compact(),
        Err(PlannerStoreError::PoisonedAfterFailedDurabilityBoundary)
    ));
    drop(store);
    let reopened = PlannerStoreV1::open(&fail_path, PlannerStoreOptionsV1::default())
        .expect("reopen after injected crash boundary");
    assert_eq!(reopened.records().len(), 1);
}

#[test]
fn backup_restore_compaction_rotation_and_external_checkpoint_preserve_lineage() {
    let root = tempdir().expect("temporary store root");
    let store_path = path(&root, "planner.store");
    let backup_path = path(&root, "planner.backup");
    let archive_path = path(&root, "planner.archive");
    let mut store = PlannerStoreV1::open(&store_path, PlannerStoreOptionsV1::default())
        .expect("open planner store");
    store
        .append_decision_envelope(digest("decision"), b"full decision")
        .expect("decision envelope");
    store
        .append_effect_terminal_envelope(digest("terminal"), b"terminal receipt")
        .expect("terminal envelope");
    store
        .record_external_checkpoint(
            digest("checkpoint"),
            digest("external-anchor"),
            digest("signer"),
            digest("signature"),
        )
        .expect("external checkpoint");
    let checkpoint_head = store.head_digest();
    store.compact().expect("compact");
    assert_eq!(store.head_digest(), checkpoint_head);
    store.backup_to(&backup_path).expect("backup");
    store
        .append_reconciliation_envelope(digest("reconcile"), b"reconciled")
        .expect("post-backup record");
    store
        .restore_from_backup(&backup_path)
        .expect("restore exact backup");
    assert_eq!(store.head_digest(), checkpoint_head);
    let anchor = store
        .rotate_to_archive(
            &archive_path,
            digest("rotation"),
            digest("retention-anchor"),
        )
        .expect("archive rotation");
    assert_eq!(anchor.kind(), PlannerStoreRecordKindV1::RotationAnchor);
    assert_eq!(store.records(), std::slice::from_ref(&anchor));
    assert!(archive_path.exists());
}

#[test]
fn legacy_v0_envelopes_migrate_in_order_with_full_payloads() {
    let root = tempdir().expect("temporary store root");
    let store_path = path(&root, "planner.store");
    let migrated = PlannerStoreV1::migrate_legacy_v0(
        &store_path,
        &[
            PlannerStoreLegacyEnvelopeV0 {
                kind: PlannerStoreRecordKindV1::SnapshotEnvelope,
                identity_digest: digest("snapshot"),
                canonical_payload: b"snapshot body".to_vec(),
            },
            PlannerStoreLegacyEnvelopeV0 {
                kind: PlannerStoreRecordKindV1::DecisionEnvelope,
                identity_digest: digest("decision"),
                canonical_payload: b"decision body".to_vec(),
            },
        ],
        PlannerStoreOptionsV1::default(),
    )
    .expect("migrate v0 envelopes");
    assert_eq!(migrated.records().len(), 2);
    assert_eq!(migrated.records()[0].payload(), b"snapshot body");
    assert_eq!(migrated.records()[1].payload(), b"decision body");
}
