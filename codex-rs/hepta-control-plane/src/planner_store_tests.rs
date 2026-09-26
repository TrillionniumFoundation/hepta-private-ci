use std::fmt::Debug;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

#[cfg(unix)]
use std::os::unix::fs::symlink;

use codex_hepta_types::Digest32;

use super::FsPlannerPersistenceV1;
use super::LOCK_FILE;
use super::PlannerCanonicalEnvelopeV1;
use super::PlannerCheckpointProposalV1;
use super::PlannerExternalAnchorV1;
use super::PlannerPersistenceV1;
use super::PlannerStoreError;
use super::PlannerStoreRecordKindV1;
use super::PlannerStoreV1;
use super::STORE_FILE;
use super::TEMP_FILE;
use crate::PlannerJournalKindV1;
use crate::PlannerJournalV1;

static NONCE: AtomicU64 = AtomicU64::new(1);

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn envelope(
    kind: PlannerStoreRecordKindV1,
    identity: &str,
    semantic: &str,
    body: &str,
) -> PlannerCanonicalEnvelopeV1 {
    must(PlannerCanonicalEnvelopeV1::new(
        kind,
        digest(identity),
        digest(semantic),
        body.as_bytes().to_vec(),
    ))
}

struct TempRoot(PathBuf);

impl TempRoot {
    fn new(label: &str) -> Self {
        let nonce = NONCE.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-planner-store-{label}-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir(&path).expect("create planner store root");
        Self(path)
    }
}

impl Drop for TempRoot {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn complete_canonical_envelopes_round_trip_and_idempotency_is_exact() {
    let root = TempRoot::new("roundtrip");
    let decision = envelope(
        PlannerStoreRecordKindV1::Decision,
        "decision-id",
        "decision-receipt",
        "complete canonical decision envelope",
    );
    let expected_body = decision.canonical_body().to_vec();
    let first = {
        let mut store = must(PlannerStoreV1::open(&root.0));
        let entry = must(store.append_envelope(decision.clone()));
        let replay = must(store.append_envelope(decision));
        assert_eq!(entry, replay);
        assert_eq!(must(store.entries()).len(), 1);
        entry
    };

    let reopened = must(PlannerStoreV1::open(&root.0));
    assert_eq!(must(reopened.entries()), &[first.clone()]);
    assert_eq!(
        must(reopened.envelope(first.identity_digest))
            .expect("stored envelope")
            .canonical_body,
        expected_body
    );
}

#[test]
fn identity_reuse_with_different_semantics_fails_closed() {
    let root = TempRoot::new("identity-conflict");
    let mut store = must(PlannerStoreV1::open(&root.0));
    must(store.append_envelope(envelope(
        PlannerStoreRecordKindV1::Decision,
        "same-id",
        "semantic-a",
        "body-a",
    )));
    assert_eq!(
        store
            .append_envelope(envelope(
                PlannerStoreRecordKindV1::Decision,
                "same-id",
                "semantic-b",
                "body-b",
            ))
            .expect_err("identity drift must reject"),
        PlannerStoreError::IdentityConflict
    );
}

#[test]
fn partial_trailing_frame_is_recovered_to_last_complete_frame() {
    let root = TempRoot::new("partial-tail");
    let committed = {
        let mut store = must(PlannerStoreV1::open(&root.0));
        must(store.append_envelope(envelope(
            PlannerStoreRecordKindV1::Decision,
            "decision-id",
            "decision",
            "decision-body",
        )));
        must(store.backup_bytes())
    };
    let mut file = OpenOptions::new()
        .append(true)
        .open(root.0.join(STORE_FILE))
        .expect("open store for partial tail fixture");
    file.write_all(b"HPS1\0\0")
        .expect("append incomplete frame prefix");
    file.sync_all().expect("sync partial tail fixture");
    drop(file);

    let reopened = must(PlannerStoreV1::open(&root.0));
    assert_eq!(must(reopened.entries()).len(), 1);
    assert_eq!(must(reopened.backup_bytes()), committed);
}

#[test]
fn concurrent_writer_is_rejected_until_owner_drops_lock() {
    let root = TempRoot::new("writer-lock");
    let owner = must(PlannerStoreV1::open(&root.0));
    assert_eq!(
        PlannerStoreV1::open(&root.0)
            .err()
            .expect("second writer must reject"),
        PlannerStoreError::Busy
    );
    drop(owner);
    must(PlannerStoreV1::open(&root.0));
}

#[test]
fn backup_restore_is_monotonic_and_cannot_remove_later_records() {
    let source_root = TempRoot::new("backup-source");
    let target_root = TempRoot::new("backup-target");
    let backup = {
        let mut source = must(PlannerStoreV1::open(&source_root.0));
        must(source.append_envelope(envelope(
            PlannerStoreRecordKindV1::Decision,
            "decision-id",
            "decision",
            "decision-body",
        )));
        must(source.append_envelope(envelope(
            PlannerStoreRecordKindV1::TerminalReceipt,
            "terminal-id",
            "terminal",
            "terminal-body",
        )));
        must(source.backup_bytes())
    };

    let mut target = must(PlannerStoreV1::open(&target_root.0));
    must(target.restore_backup(&backup));
    let older = {
        let older_root = TempRoot::new("older-backup");
        let mut older_store = must(PlannerStoreV1::open(&older_root.0));
        must(older_store.append_envelope(envelope(
            PlannerStoreRecordKindV1::Decision,
            "decision-id",
            "decision",
            "decision-body",
        )));
        must(older_store.backup_bytes())
    };
    assert_eq!(
        target
            .restore_backup(&older)
            .expect_err("older backup must not remove terminal evidence"),
        PlannerStoreError::BackupRegression
    );
    assert_eq!(must(target.entries()).len(), 2);
}

#[derive(Default)]
struct RecordingAnchor {
    proposal: Option<PlannerCheckpointProposalV1>,
}

impl PlannerExternalAnchorV1 for RecordingAnchor {
    fn anchor(
        &mut self,
        proposal: &PlannerCheckpointProposalV1,
    ) -> Result<Digest32, PlannerStoreError> {
        self.proposal = Some(proposal.clone());
        Ok(digest("external-signed-anchor"))
    }
}

#[test]
fn compaction_requires_external_anchor_and_preserves_complete_state_snapshot() {
    let root = TempRoot::new("checkpoint");
    let mut store = must(PlannerStoreV1::open(&root.0));
    must(store.append_envelope(envelope(
        PlannerStoreRecordKindV1::Decision,
        "decision-id",
        "decision",
        "decision-body",
    )));
    let previous_root = must(store.root_digest());
    let state = b"complete selected/revoked/terminal state image".to_vec();
    let state_digest = Digest32::of_bytes(&state);
    let mut anchor = RecordingAnchor::default();
    let receipt = must(store.compact_to_checkpoint(
        digest("checkpoint-id"),
        state_digest,
        state.clone(),
        &mut anchor,
    ));
    assert_eq!(receipt.previous_root_digest, previous_root);
    assert_eq!(receipt.retained_state_digest, state_digest);
    assert_eq!(must(store.entries()).len(), 1);
    assert_eq!(must(store.entries())[0].kind, PlannerStoreRecordKindV1::Checkpoint);
    let proposal = anchor.proposal.expect("anchor proposal");
    assert_eq!(proposal.previous_root_digest, previous_root);
    assert_eq!(proposal.retained_state_bytes, state);

    drop(store);
    let reopened = must(PlannerStoreV1::open(&root.0));
    assert_eq!(must(reopened.entries()).len(), 1);
    assert_eq!(must(reopened.root_digest()), receipt.checkpoint_frame_digest);
}

#[test]
fn deterministic_legacy_migration_requires_every_complete_envelope() {
    let root = TempRoot::new("migration");
    let mut legacy = PlannerJournalV1::new();
    must(legacy.append(
        PlannerJournalKindV1::Decision,
        digest("legacy-decision-id"),
        digest("legacy-decision-payload"),
    ));
    must(legacy.append(
        PlannerJournalKindV1::SelectedPlan,
        digest("legacy-selection-id"),
        digest("legacy-selection-payload"),
    ));
    let migrated = must(PlannerStoreV1::migrate_from_legacy_journal(
        &root.0,
        &legacy,
        vec![
            PlannerCanonicalEnvelopeV1::new(
                PlannerStoreRecordKindV1::Decision,
                digest("legacy-decision-id"),
                digest("legacy-decision-payload"),
                b"complete legacy decision".to_vec(),
            )
            .unwrap(),
            PlannerCanonicalEnvelopeV1::new(
                PlannerStoreRecordKindV1::SelectedPlan,
                digest("legacy-selection-id"),
                digest("legacy-selection-payload"),
                b"complete legacy selection".to_vec(),
            )
            .unwrap(),
        ],
    ));
    assert_eq!(must(migrated.entries()).len(), 2);
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FaultStage {
    Append,
    FileSync,
    TempWrite,
    TempSync,
    Rename,
    DirectorySync,
}

struct FaultPersistence {
    stage: FaultStage,
    real: FsPlannerPersistenceV1,
}

impl PlannerPersistenceV1 for FaultPersistence {
    fn append(&self, path: &Path, bytes: &[u8]) -> io::Result<()> {
        if self.stage == FaultStage::Append {
            return Err(io::Error::other("injected planner append failure"));
        }
        self.real.append(path, bytes)
    }

    fn sync_file(&self, path: &Path) -> io::Result<()> {
        if self.stage == FaultStage::FileSync {
            return Err(io::Error::other("injected planner file-sync failure"));
        }
        self.real.sync_file(path)
    }

    fn truncate(&self, path: &Path, length: u64) -> io::Result<()> {
        self.real.truncate(path, length)
    }

    fn write_temp(&self, path: &Path, bytes: &[u8]) -> io::Result<()> {
        if self.stage == FaultStage::TempWrite {
            return Err(io::Error::other("injected planner temp-write failure"));
        }
        self.real.write_temp(path, bytes)
    }

    fn sync_temp(&self, path: &Path) -> io::Result<()> {
        if self.stage == FaultStage::TempSync {
            return Err(io::Error::other("injected planner temp-sync failure"));
        }
        self.real.sync_temp(path)
    }

    fn rename(&self, from: &Path, to: &Path) -> io::Result<()> {
        if self.stage == FaultStage::Rename {
            return Err(io::Error::other("injected planner rename failure"));
        }
        self.real.rename(from, to)
    }

    fn sync_parent(&self, root: &Path) -> io::Result<()> {
        if self.stage == FaultStage::DirectorySync {
            return Err(io::Error::other(
                "injected planner directory-sync failure",
            ));
        }
        self.real.sync_parent(root)
    }
}

#[test]
fn append_failpoints_poison_the_open_handle_and_reconcile_on_reopen() {
    for stage in [FaultStage::Append, FaultStage::FileSync] {
        let root = TempRoot::new(match stage {
            FaultStage::Append => "fail-append",
            FaultStage::FileSync => "fail-sync",
            _ => unreachable!(),
        });
        drop(must(PlannerStoreV1::open(&root.0)));
        let persistence = Arc::new(FaultPersistence {
            stage,
            real: FsPlannerPersistenceV1,
        });
        let mut store = must(PlannerStoreV1::open_with_persistence(
            &root.0,
            persistence,
        ));
        assert_eq!(
            store
                .append_envelope(envelope(
                    PlannerStoreRecordKindV1::Decision,
                    "decision-id",
                    "decision",
                    "decision-body",
                ))
                .expect_err("injected append boundary must fail"),
            PlannerStoreError::Indeterminate
        );
        assert!(store.is_indeterminate());
        assert_eq!(
            store
                .entries()
                .expect_err("poisoned handle must fail closed"),
            PlannerStoreError::Indeterminate
        );
        drop(store);
        let reopened = must(PlannerStoreV1::open(&root.0));
        assert!(!reopened.is_indeterminate());
        if stage == FaultStage::Append {
            assert!(must(reopened.entries()).is_empty());
        } else {
            assert_eq!(must(reopened.entries()).len(), 1);
        }
    }
}

#[cfg(unix)]
#[test]
fn symlinked_root_lock_store_and_temp_paths_fail_closed() {
    let target = TempRoot::new("symlink-target");
    let outside = target.0.join("outside");
    File::create(&outside).expect("create symlink target");

    let root_link = std::env::temp_dir().join(format!(
        "hepta-planner-root-link-{}-{}",
        std::process::id(),
        NONCE.fetch_add(1, Ordering::Relaxed)
    ));
    symlink(&target.0, &root_link).expect("create root symlink");
    assert_eq!(
        PlannerStoreV1::open(&root_link)
            .err()
            .expect("symlinked root must reject"),
        PlannerStoreError::Symlink
    );
    fs::remove_file(&root_link).expect("remove root symlink");

    for path in [LOCK_FILE, STORE_FILE, TEMP_FILE] {
        let root = TempRoot::new(path);
        symlink(&outside, root.0.join(path)).expect("create store component symlink");
        assert_eq!(
            PlannerStoreV1::open(&root.0)
                .err()
                .expect("symlinked store component must reject"),
            PlannerStoreError::Symlink
        );
    }
}
