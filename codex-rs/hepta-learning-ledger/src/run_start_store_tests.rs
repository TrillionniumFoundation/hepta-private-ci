use std::fmt;
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::DurableRunStartStore;
use super::RunStartCheckpointOwnerV1;
use super::RunStartCheckpointV1;
use crate::RunStartAdmissionBindingV1;
use crate::RunStartAnchor;
use crate::RunStartAppendDisposition;
use crate::RunStartAuthenticationV1;
use crate::RunStartJournal;
use crate::RunStartObjectiveDispositionV1;
use crate::RunStartRecordV1;
use crate::RunStartSnapshotV1;
use crate::RunStartStoreError;

fn must<T, E: fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable ID")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn record(run_id: &str, sequence: u64) -> RunStartRecordV1 {
    let objective_semantic_bytes = format!("objective-{run_id}").into_bytes();
    let objective_function_v1_bytes = format!("{{\"objectiveId\":\"{run_id}\"}}").into_bytes();
    RunStartRecordV1 {
        authentication: RunStartAuthenticationV1 {
            issuer_id: id("issuer.objective"),
            key_epoch: 1,
            message_id: id(&format!("message.{sequence}")),
            sequence,
            expires_at_ms: 10_000 + sequence,
            scope_digest: digest("scope"),
            signed_body_digest: digest(&format!("body-{sequence}")),
            signature: [u8::try_from(sequence).unwrap_or(1); 64],
        },
        admission: RunStartAdmissionBindingV1 {
            profile_id: id("profile.objective"),
            profile_revision: 1,
            profile_digest: digest("profile"),
            supplied_source_digest: digest("source"),
            intent_digest: digest(&format!("intent-{sequence}")),
            admitted_source_digest: digest(&format!("admitted-{sequence}")),
            observed_at_unix_micros: 1_000,
            deadline_unix_micros: 20_000 + sequence,
            authority: AuthorityPosture::DENY_ALL,
        },
        disposition: RunStartObjectiveDispositionV1::Compiled,
        snapshot: RunStartSnapshotV1 {
            run_id: id(run_id),
            objective_digest: Digest32::of_bytes(&objective_semantic_bytes),
            hard_constraint_digest: digest(&format!("constraints-{sequence}")),
            preference_state_digest: digest("preferences"),
            model_tuple_digest: digest("model"),
            prompt_registry_digest: digest("prompt"),
            artifact_set_digest: digest("artifacts"),
            authority_epoch: 1,
            generation: 1,
            fence_digest: digest("fence"),
        },
        runtime_body_digest: digest(&format!("runtime-{sequence}")),
        objective_semantic_bytes,
        objective_function_v1_digest: Digest32::of_bytes(&objective_function_v1_bytes),
        objective_function_v1_bytes,
    }
}

#[derive(Clone)]
struct MemoryCheckpoint {
    checkpoint: Arc<Mutex<RunStartCheckpointV1>>,
    fail_next: Arc<AtomicBool>,
    fail_after_update_next: Arc<AtomicBool>,
}

impl MemoryCheckpoint {
    fn new(anchor: RunStartAnchor) -> Self {
        Self {
            checkpoint: Arc::new(Mutex::new(RunStartCheckpointV1 {
                anchor,
                compacted_prefix: RunStartAnchor::ZERO,
                compacted_digest: Digest32::ZERO,
            })),
            fail_next: Arc::new(AtomicBool::new(false)),
            fail_after_update_next: Arc::new(AtomicBool::new(false)),
        }
    }

    fn checkpoint(&self) -> RunStartCheckpointV1 {
        *self.checkpoint.lock().expect("checkpoint lock")
    }

    fn anchor(&self) -> RunStartAnchor {
        self.checkpoint().anchor
    }

    fn fail_next(&self) {
        self.fail_next.store(true, Ordering::SeqCst);
    }

    fn fail_after_update_next(&self) {
        self.fail_after_update_next.store(true, Ordering::SeqCst);
    }
}

impl RunStartCheckpointOwnerV1 for MemoryCheckpoint {
    fn current_checkpoint(&self) -> Result<RunStartCheckpointV1, RunStartStoreError> {
        Ok(self.checkpoint())
    }

    fn compare_and_swap(
        &self,
        expected: RunStartCheckpointV1,
        next: RunStartCheckpointV1,
    ) -> Result<(), RunStartStoreError> {
        if self.fail_next.swap(false, Ordering::SeqCst) {
            return Err(RunStartStoreError::Indeterminate);
        }
        let mut current = self
            .checkpoint
            .lock()
            .map_err(|_| RunStartStoreError::Poisoned)?;
        if *current == next {
            return Ok(());
        }
        let append_transition = next.compacted_prefix == expected.compacted_prefix
            && next.compacted_digest == expected.compacted_digest
            && next.anchor.sequence
                == expected
                    .anchor
                    .sequence
                    .checked_add(1)
                    .ok_or(RunStartStoreError::Capacity)?;
        let compaction_transition = next.anchor == expected.anchor
            && next.compacted_prefix.sequence > expected.compacted_prefix.sequence
            && !next.compacted_digest.is_zero();
        if *current != expected
            || !next.is_well_formed()
            || (!append_transition && !compaction_transition)
        {
            return Err(RunStartStoreError::RollbackDetected);
        }
        *current = next;
        if self.fail_after_update_next.swap(false, Ordering::SeqCst) {
            return Err(RunStartStoreError::Indeterminate);
        }
        Ok(())
    }
}

struct Fixture {
    root: PathBuf,
}

impl Fixture {
    fn new(label: &str) -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "hepta-run-start-store-{label}-{}-{nonce}",
            std::process::id()
        ));
        must(fs::create_dir_all(&root));
        Self { root }
    }

    fn open(
        &self,
        max_records: usize,
        checkpoint: MemoryCheckpoint,
    ) -> Result<DurableRunStartStore, RunStartStoreError> {
        DurableRunStartStore::open(
            self.root.clone(),
            digest("binding"),
            max_records,
            Box::new(checkpoint),
        )
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn rotates_at_capacity_and_reopens_one_global_chain() {
    let fixture = Fixture::new("rotate");
    let checkpoint = MemoryCheckpoint::new(RunStartAnchor::ZERO);
    let mut store = must(fixture.open(2, checkpoint.clone()));
    let first_record = record("run.1", 1);
    let first = must(store.append_run_start(Digest32::ZERO, first_record.clone()));
    let second = must(store.append_run_start(first.chain_digest, record("run.2", 2)));
    let third = must(store.append_run_start(second.chain_digest, record("run.3", 3)));
    assert_eq!(third.sequence, 3);
    assert_eq!(store.segment_count(), 2);
    assert_eq!(checkpoint.anchor(), store.head_anchor());

    let replay = must(store.append_run_start(third.chain_digest, first_record.clone()));
    assert_eq!(
        replay.disposition,
        RunStartAppendDisposition::IdempotentReplay
    );
    assert_eq!(replay.sequence, first.sequence);
    assert_eq!(replay.chain_digest, first.chain_digest);
    drop(store);

    let reopened = must(fixture.open(2, checkpoint));
    assert_eq!(
        reopened.head_anchor(),
        RunStartAnchor {
            sequence: third.sequence,
            chain_digest: third.chain_digest,
        }
    );
    assert_eq!(must(reopened.records()).len(), 3);
    assert_eq!(must(reopened.get(&id("run.1"))), Some(&first_record));
}

#[test]
fn acknowledgement_loss_reconciles_the_durable_extension() {
    let fixture = Fixture::new("ack-loss");
    let checkpoint = MemoryCheckpoint::new(RunStartAnchor::ZERO);
    let mut store = must(fixture.open(2, checkpoint.clone()));
    checkpoint.fail_next();
    assert_eq!(
        store.append_run_start(Digest32::ZERO, record("run.ack", 1)),
        Err(RunStartStoreError::Indeterminate)
    );
    assert_eq!(checkpoint.anchor(), RunStartAnchor::ZERO);
    drop(store);

    let reopened = must(fixture.open(2, checkpoint.clone()));
    assert_eq!(checkpoint.anchor(), reopened.head_anchor());
    assert_eq!(reopened.head_anchor().sequence, 1);
    assert!(must(reopened.get(&id("run.ack"))).is_some());
}

#[test]
fn local_history_behind_the_external_frontier_is_rejected() {
    let fixture = Fixture::new("rollback");
    let backup = Fixture::new("rollback-backup");
    let checkpoint = MemoryCheckpoint::new(RunStartAnchor::ZERO);
    let mut store = must(fixture.open(16, checkpoint.clone()));
    let first = must(store.append_run_start(Digest32::ZERO, record("run.1", 1)));
    must(fs::copy(
        fixture.root.join("active.bin"),
        backup.root.join("active.bin"),
    ));
    let second = must(store.append_run_start(first.chain_digest, record("run.2", 2)));
    assert_eq!(checkpoint.anchor().sequence, second.sequence);
    drop(store);

    must(fs::copy(
        backup.root.join("active.bin"),
        fixture.root.join("active.bin"),
    ));
    assert_eq!(
        fixture.open(16, checkpoint).err(),
        Some(RunStartStoreError::RollbackDetected)
    );
}

#[test]
fn removing_a_sealed_segment_never_recovers_as_empty_history() {
    let fixture = Fixture::new("missing-segment");
    let checkpoint = MemoryCheckpoint::new(RunStartAnchor::ZERO);
    let mut store = must(fixture.open(1, checkpoint.clone()));
    let first = must(store.append_run_start(Digest32::ZERO, record("run.1", 1)));
    let second = must(store.append_run_start(first.chain_digest, record("run.2", 2)));
    assert_eq!(second.sequence, 2);
    drop(store);

    let segments = fixture.root.join("segments");
    let sealed = must(fs::read_dir(&segments))
        .next()
        .expect("sealed segment")
        .expect("segment entry")
        .path();
    must(fs::remove_file(sealed));
    assert!(matches!(
        fixture.open(1, checkpoint),
        Err(RunStartStoreError::SegmentMismatch | RunStartStoreError::RollbackDetected)
    ));
}

#[test]
fn expired_prefix_compacts_to_checkpoint_bound_replay_index() {
    let fixture = Fixture::new("compact");
    let checkpoint = MemoryCheckpoint::new(RunStartAnchor::ZERO);
    let mut store = must(fixture.open(1, checkpoint.clone()));
    let first_record = record("run.compact.1", 1);
    let first = must(store.append_run_start(Digest32::ZERO, first_record.clone()));
    let second = must(store.append_run_start(first.chain_digest, record("run.compact.2", 2)));
    let third = must(store.append_run_start(second.chain_digest, record("run.compact.3", 3)));
    assert_eq!(store.sealed_segment_paths().len(), 2);

    assert_eq!(must(store.compact_expired_prefix(20_001)), 1);
    assert_eq!(store.local_checkpoint(), checkpoint.checkpoint());
    assert_eq!(store.local_checkpoint().compacted_prefix.sequence, 1);
    assert!(!store.local_checkpoint().compacted_digest.is_zero());
    assert!(must(store.get(&id("run.compact.1"))).is_none());
    assert!(must(store.get(&id("run.compact.2"))).is_some());
    assert_eq!(must(store.authentication_records()).len(), 3);

    let replay = must(store.append_run_start(third.chain_digest, first_record));
    assert_eq!(
        replay.disposition,
        RunStartAppendDisposition::IdempotentReplay
    );
    assert_eq!(replay.sequence, first.sequence);
    drop(store);

    let reopened = must(fixture.open(1, checkpoint.clone()));
    assert_eq!(reopened.head_anchor().sequence, 3);
    assert_eq!(reopened.local_checkpoint(), checkpoint.checkpoint());
    assert_eq!(must(reopened.index_entries()).len(), 3);
    assert_eq!(must(reopened.records()).len(), 2);
    assert!(must(reopened.get(&id("run.compact.1"))).is_none());
}

#[test]
fn compaction_ack_loss_reconciles_then_removes_overlapping_segment() {
    let fixture = Fixture::new("compact-ack-loss");
    let checkpoint = MemoryCheckpoint::new(RunStartAnchor::ZERO);
    let mut store = must(fixture.open(1, checkpoint.clone()));
    let first = must(store.append_run_start(Digest32::ZERO, record("run.pending.1", 1)));
    must(store.append_run_start(first.chain_digest, record("run.pending.2", 2)));
    checkpoint.fail_next();
    assert_eq!(
        store.compact_expired_prefix(20_001),
        Err(RunStartStoreError::Indeterminate)
    );
    assert_eq!(
        checkpoint.checkpoint().compacted_prefix,
        RunStartAnchor::ZERO
    );
    drop(store);

    let reopened = must(fixture.open(1, checkpoint.clone()));
    assert_eq!(reopened.local_checkpoint(), checkpoint.checkpoint());
    assert_eq!(reopened.local_checkpoint().compacted_prefix.sequence, 1);
    assert_eq!(reopened.sealed_segment_paths().len(), 0);
    assert!(must(reopened.get(&id("run.pending.1"))).is_none());
    assert!(must(reopened.get(&id("run.pending.2"))).is_some());
}

#[test]
fn committed_compaction_cannot_be_replaced_by_older_valid_summary() {
    let fixture = Fixture::new("compact-rollback");
    let backup = Fixture::new("compact-rollback-backup");
    let checkpoint = MemoryCheckpoint::new(RunStartAnchor::ZERO);
    let mut store = must(fixture.open(1, checkpoint.clone()));
    let first = must(store.append_run_start(Digest32::ZERO, record("run.rollback.1", 1)));
    let second = must(store.append_run_start(first.chain_digest, record("run.rollback.2", 2)));
    must(store.append_run_start(second.chain_digest, record("run.rollback.3", 3)));
    assert_eq!(must(store.compact_expired_prefix(20_001)), 1);
    must(fs::copy(
        fixture.root.join("compacted-v1.bin"),
        backup.root.join("compacted-v1.bin"),
    ));
    let remaining_segment = store.sealed_segment_paths()[0].to_path_buf();
    must(fs::copy(
        &remaining_segment,
        backup
            .root
            .join(remaining_segment.file_name().expect("segment name")),
    ));
    assert_eq!(must(store.compact_expired_prefix(20_002)), 1);
    drop(store);

    must(fs::copy(
        backup.root.join("compacted-v1.bin"),
        fixture.root.join("compacted-v1.bin"),
    ));
    let restored_segments = fixture.root.join("segments");
    let saved_segment = must(fs::read_dir(&backup.root))
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .find(|path| {
            path.extension().and_then(|value| value.to_str()) == Some("bin")
                && path.file_name().and_then(|value| value.to_str()) != Some("compacted-v1.bin")
        })
        .expect("saved segment");
    must(fs::copy(
        &saved_segment,
        restored_segments.join(saved_segment.file_name().expect("saved segment name")),
    ));
    assert_eq!(
        fixture.open(1, checkpoint).err(),
        Some(RunStartStoreError::RollbackDetected)
    );
}

#[test]
fn crash_after_segment_rename_without_successor_recovers_new_active_segment() {
    let fixture = Fixture::new("rename-cut");
    let checkpoint = MemoryCheckpoint::new(RunStartAnchor::ZERO);
    let mut store = must(fixture.open(1, checkpoint.clone()));
    let first = must(store.append_run_start(Digest32::ZERO, record("run.rename.1", 1)));
    drop(store);

    let active = fixture.root.join("active.bin");
    let segment_dir = fixture.root.join("segments");
    let name = super::segment_filename(
        RunStartAnchor::ZERO,
        RunStartAnchor {
            sequence: first.sequence,
            chain_digest: first.chain_digest,
        },
    )
    .expect("segment name");
    must(fs::rename(active, segment_dir.join(name)));

    let mut reopened = must(fixture.open(1, checkpoint));
    assert_eq!(reopened.head_anchor().sequence, 1);
    let second = must(reopened.append_run_start(first.chain_digest, record("run.rename.2", 2)));
    assert_eq!(second.sequence, 2);
}

#[test]
fn append_checkpoint_ack_loss_after_durable_cas_reopens_exact_result() {
    let fixture = Fixture::new("append-cas-ack-loss");
    let checkpoint = MemoryCheckpoint::new(RunStartAnchor::ZERO);
    let mut store = must(fixture.open(2, checkpoint.clone()));
    checkpoint.fail_after_update_next();
    assert_eq!(
        store.append_run_start(Digest32::ZERO, record("run.append.cas", 1)),
        Err(RunStartStoreError::Indeterminate)
    );
    assert_eq!(checkpoint.anchor().sequence, 1);
    drop(store);

    let mut reopened = must(fixture.open(2, checkpoint.clone()));
    let existing = must(reopened.get(&id("run.append.cas")))
        .cloned()
        .expect("durable append");
    let replay = must(reopened.append_run_start(checkpoint.anchor().chain_digest, existing));
    assert_eq!(
        replay.disposition,
        RunStartAppendDisposition::IdempotentReplay
    );
    assert_eq!(replay.sequence, 1);
}

#[test]
fn compaction_checkpoint_ack_loss_after_durable_cas_commits_pending_summary() {
    let fixture = Fixture::new("compact-cas-ack-loss");
    let checkpoint = MemoryCheckpoint::new(RunStartAnchor::ZERO);
    let mut store = must(fixture.open(1, checkpoint.clone()));
    let first = must(store.append_run_start(Digest32::ZERO, record("run.compact.cas.1", 1)));
    must(store.append_run_start(first.chain_digest, record("run.compact.cas.2", 2)));
    checkpoint.fail_after_update_next();
    assert_eq!(
        store.compact_expired_prefix(20_001),
        Err(RunStartStoreError::Indeterminate)
    );
    assert_eq!(checkpoint.checkpoint().compacted_prefix.sequence, 1);
    drop(store);

    let reopened = must(fixture.open(1, checkpoint.clone()));
    assert_eq!(reopened.local_checkpoint(), checkpoint.checkpoint());
    assert_eq!(reopened.local_checkpoint().compacted_prefix.sequence, 1);
    assert_eq!(reopened.sealed_segment_paths().len(), 0);
    assert!(must(reopened.get(&id("run.compact.cas.1"))).is_none());
    assert!(must(reopened.get(&id("run.compact.cas.2"))).is_some());
}

#[test]
fn checkpoint_bootstrap_is_allowed_only_for_a_pristine_known_layout() {
    let fixture = Fixture::new("checkpoint-bootstrap");
    must(fs::remove_dir_all(&fixture.root));
    assert!(must(
        DurableRunStartStore::checkpoint_initialization_allowed(&fixture.root)
    ));

    must(fs::create_dir_all(&fixture.root));
    assert!(must(
        DurableRunStartStore::checkpoint_initialization_allowed(&fixture.root)
    ));

    must(fs::create_dir_all(fixture.root.join("segments")));
    assert!(must(
        DurableRunStartStore::checkpoint_initialization_allowed(&fixture.root)
    ));

    must(fs::write(
        fixture.root.join("active.bin"),
        b"durable-history",
    ));
    assert!(!must(
        DurableRunStartStore::checkpoint_initialization_allowed(&fixture.root)
    ));
    must(fs::remove_file(fixture.root.join("active.bin")));

    must(fs::write(fixture.root.join("unknown-state"), b"unknown"));
    assert!(!must(
        DurableRunStartStore::checkpoint_initialization_allowed(&fixture.root)
    ));
}

#[test]
fn failed_rotation_poisons_writer_until_reopen() {
    let fixture = Fixture::new("rotate-poison");
    let checkpoint = MemoryCheckpoint::new(RunStartAnchor::ZERO);
    let mut store = must(fixture.open(1, checkpoint));
    let first = must(store.append_run_start(Digest32::ZERO, record("run.rotate.poison.1", 1)));
    let sealed_name = super::segment_filename(
        RunStartAnchor::ZERO,
        RunStartAnchor {
            sequence: first.sequence,
            chain_digest: first.chain_digest,
        },
    )
    .expect("sealed segment name");
    must(fs::write(
        fixture.root.join("segments").join(sealed_name),
        b"preexisting-conflict",
    ));

    assert_eq!(
        store.append_run_start(first.chain_digest, record("run.rotate.poison.2", 2)),
        Err(RunStartStoreError::SegmentMismatch)
    );
    assert_eq!(store.records(), Err(RunStartStoreError::Poisoned));
}

#[test]
fn indexed_replay_identity_survives_rotation_compaction_and_reopen() {
    let fixture = Fixture::new("indexed-replay");
    let checkpoint = MemoryCheckpoint::new(RunStartAnchor::ZERO);
    let mut store = must(fixture.open(2, checkpoint.clone()));
    let first_record = record("run.indexed.1", 1);
    let first = must(store.append_run_start(Digest32::ZERO, first_record.clone()));
    let original = must(store.index_entry(&first_record.snapshot.run_id)).cloned();
    assert!(original.is_some());
    for sequence in 2..=9 {
        let head = store.head_digest();
        must(store.append_run_start(head, record(&format!("run.indexed.{sequence}"), sequence)));
    }
    assert_eq!(must(store.index_entry(&id("run.missing"))), None);
    assert_eq!(must(store.compact_expired_prefix(30_000)), 4);
    assert!(must(store.get(&first_record.snapshot.run_id)).is_none());
    assert_eq!(
        must(store.index_entry(&first_record.snapshot.run_id)),
        original.as_ref()
    );
    drop(store);
    let mut store = must(fixture.open(2, checkpoint));
    assert_eq!(
        must(store.index_entry(&first_record.snapshot.run_id)),
        original.as_ref()
    );
    let replay = must(store.append_run_start(store.head_digest(), first_record.clone()));
    assert_eq!(replay.sequence, first.sequence);
    assert_eq!(replay.chain_digest, first.chain_digest);
    assert_eq!(
        replay.disposition,
        RunStartAppendDisposition::IdempotentReplay
    );
    let mut changed = first_record;
    changed.authentication.message_id = id("message.changed");
    assert_eq!(
        store.append_run_start(store.head_digest(), changed).err(),
        Some(RunStartStoreError::Conflict)
    );
}

#[test]
fn indexed_replay_lookup_rejects_uncertain_checkpoint_state() {
    let fixture = Fixture::new("indexed-poison");
    let checkpoint = MemoryCheckpoint::new(RunStartAnchor::ZERO);
    let mut store = must(fixture.open(2, checkpoint.clone()));
    let first = record("run.indexed.uncertain", 1);
    checkpoint.fail_next();
    assert_eq!(
        store.append_run_start(Digest32::ZERO, first.clone()).err(),
        Some(RunStartStoreError::Indeterminate)
    );
    assert_eq!(
        store.index_entry(&first.snapshot.run_id).err(),
        Some(RunStartStoreError::Poisoned)
    );
}

#[test]
fn writer_lease_survives_active_segment_release_and_handoff() {
    let fixture = Fixture::new("writer-gap");
    let checkpoint = MemoryCheckpoint::new(RunStartAnchor::ZERO);
    let mut store = must(fixture.open(1, checkpoint.clone()));
    let first_record = record("run.writer.1", 1);
    let first = must(store.append_run_start(Digest32::ZERO, first_record.clone()));
    // Reproduce the rotation cut after the active file lock is released.
    drop(store.active.take());
    assert!(matches!(
        fixture.open(1, checkpoint.clone()),
        Err(RunStartStoreError::Busy)
    ));
    drop(store);
    let mut reopened = must(fixture.open(1, checkpoint.clone()));
    assert_eq!(must(reopened.get(&id("run.writer.1"))), Some(&first_record));
    let second = must(reopened.append_run_start(first.chain_digest, record("run.writer.2", 2)));
    assert_eq!(second.sequence, 2);
    assert!(matches!(
        fixture.open(1, checkpoint),
        Err(RunStartStoreError::Busy)
    ));
}

#[test]
fn writer_lease_fences_another_process_during_rotation() {
    const CHILD_ROOT: &str = "HEPTA_RUN_START_WRITER_PROBE_ROOT";
    if let Some(root) = std::env::var_os(CHILD_ROOT) {
        let opened = DurableRunStartStore::open(
            PathBuf::from(root),
            digest("binding"),
            1,
            Box::new(MemoryCheckpoint::new(RunStartAnchor::ZERO)),
        );
        assert!(matches!(opened, Err(RunStartStoreError::Busy)));
        return;
    }
    let fixture = Fixture::new("writer-process");
    let checkpoint = MemoryCheckpoint::new(RunStartAnchor::ZERO);
    let mut store = must(fixture.open(1, checkpoint.clone()));
    let first = must(store.append_run_start(Digest32::ZERO, record("run.process.1", 1)));
    let head = store.head_anchor();
    drop(store.active.take());
    let sealed_name = must(super::segment_filename(RunStartAnchor::ZERO, head));
    must(fs::rename(
        fixture.root.join("active.bin"),
        fixture.root.join("segments").join(sealed_name),
    ));
    let output = must(
        std::process::Command::new(must(std::env::current_exe()))
            .args([
                "--exact",
                "run_start::store::tests::writer_lease_fences_another_process_during_rotation",
                "--nocapture",
            ])
            .env(CHILD_ROOT, &fixture.root)
            .output(),
    );
    assert!(
        String::from_utf8_lossy(&output.stdout).contains("running 1 test"),
        "writer probe must actually execute"
    );
    assert!(
        output.status.success(),
        "writer subprocess failed: {} {}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(!fixture.root.join("active.bin").exists());
    drop(store);
    let mut reopened = must(fixture.open(1, checkpoint));
    assert_eq!(reopened.head_anchor(), head);
    let second = must(reopened.append_run_start(first.chain_digest, record("run.process.2", 2)));
    assert_eq!(second.sequence, 2);
}

#[test]
fn non_regular_directory_writer_lease_is_rejected_before_history_mutation() {
    let fixture = Fixture::new("writer-not-regular");
    must(fs::create_dir(fixture.root.join(super::WRITER_FILE)));
    assert!(matches!(
        fixture.open(1, MemoryCheckpoint::new(RunStartAnchor::ZERO)),
        Err(RunStartStoreError::NotRegular)
    ));
    assert!(!fixture.root.join("active.bin").exists());
    assert!(!fixture.root.join("segments").exists());
}

#[test]
fn compacted_count_must_fit_authenticated_payload_before_allocation() {
    let fixture = Fixture::new("compacted-count");
    let checkpoint = MemoryCheckpoint::new(RunStartAnchor::ZERO);
    let mut store = must(fixture.open(1, checkpoint.clone()));
    let first = must(store.append_run_start(Digest32::ZERO, record("run.count.1", 1)));
    must(store.append_run_start(first.chain_digest, record("run.count.2", 2)));
    must(store.compact_expired_prefix(100_000));
    drop(store);
    let path = fixture.root.join("compacted-v1.bin");
    let original = must(fs::read(&path));
    const COUNT_OFFSET: usize = 8 + 32 + 1 + 40 + 32 + 40 + 32;
    for (count, expected) in [
        (0_u32, RunStartStoreError::Capacity),
        (4096, RunStartStoreError::Corrupt),
        (4_194_305, RunStartStoreError::Capacity),
    ] {
        let mut bytes = original.clone();
        bytes[COUNT_OFFSET..COUNT_OFFSET + 4].copy_from_slice(&count.to_be_bytes());
        let payload_len = bytes.len() - 32;
        let checksum = Digest32::of_bytes(&bytes[..payload_len]);
        bytes[payload_len..].copy_from_slice(checksum.as_array());
        must(fs::write(&path, bytes));
        let error = fixture
            .open(1, checkpoint.clone())
            .err()
            .expect("invalid summary count");
        assert_eq!(error, expected);
    }
    must(fs::write(&path, original));
    let reopened = must(fixture.open(1, checkpoint));
    assert!(must(reopened.index_entry(&id("run.count.1"))).is_some());
}
