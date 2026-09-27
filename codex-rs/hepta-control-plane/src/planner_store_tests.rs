use super::*;
use std::sync::Mutex;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;

use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

struct TestAnchor {
    key: SigningKey,
    value: Mutex<Option<SignedPlannerCheckpointV1>>,
    fail: AtomicU8,
}

impl TestAnchor {
    fn new() -> Arc<Self> {
        Arc::new(Self {
            key: SigningKey::from_bytes(&[41; 32]),
            value: Mutex::new(None),
            fail: AtomicU8::new(0),
        })
    }
}

impl PlannerAnchorV1 for TestAnchor {
    fn current(&self, _: Digest32) -> Result<Option<SignedPlannerCheckpointV1>, PlannerStoreError> {
        Ok(self.value.lock().expect("test anchor lock").clone())
    }

    fn compare_exchange(
        &self,
        expected: Option<PlannerCheckpointV1>,
        next: PlannerCheckpointV1,
    ) -> Result<SignedPlannerCheckpointV1, PlannerStoreError> {
        let failure = self.fail.swap(0, Ordering::SeqCst);
        if failure == 1 {
            return Err(PlannerStoreError::AnchorUnavailable);
        }
        let mut value = self.value.lock().expect("test anchor lock");
        if value.as_ref().map(|signed| signed.checkpoint) != expected {
            return Err(PlannerStoreError::AnchorMismatch);
        }
        let signed = SignedPlannerCheckpointV1 {
            checkpoint: next,
            signature: self.key.sign(next.digest().as_array()).to_bytes(),
        };
        *value = Some(signed.clone());
        if failure == 2 {
            return Err(PlannerStoreError::AnchorUnavailable);
        }
        Ok(signed)
    }
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn open(path: &Path, anchor: &Arc<TestAnchor>) -> Result<PlannerStoreV1, PlannerStoreError> {
    PlannerStoreV1::open(path, digest(b"store"), anchor.key.verifying_key(), anchor.clone())
}

fn create(path: &Path, anchor: &Arc<TestAnchor>) -> PlannerStoreV1 {
    PlannerStoreV1::create(path, digest(b"store"), anchor.key.verifying_key(), anchor.clone())
        .expect("create bounded test store")
}

#[test]
fn full_envelope_survives_reopen_and_equal_replay_is_idempotent() {
    let directory = tempfile::tempdir().expect("temporary directory");
    let anchor = TestAnchor::new();
    let mut store = create(directory.path(), &anchor);
    let key = digest(b"decision");
    let body = b"version=1; complete canonical decision envelope fixture";
    assert!(!store.append(key, body).expect("append").idempotent);
    assert!(store.append(key, body).expect("equal replay").idempotent);
    assert!(matches!(store.append(key, b"different"), Err(PlannerStoreError::IdentityConflict)));
    drop(store);
    let store = open(directory.path(), &anchor).expect("reopen");
    assert_eq!(store.get(key).expect("read"), Some(body.as_slice()));
}

#[test]
fn writer_lock_excludes_another_handle() {
    let directory = tempfile::tempdir().expect("temporary directory");
    let anchor = TestAnchor::new();
    let store = create(directory.path(), &anchor);
    assert!(matches!(open(directory.path(), &anchor), Err(PlannerStoreError::Locked)));
    drop(store);
    assert!(open(directory.path(), &anchor).is_ok());
}

#[test]
fn every_partial_unacknowledged_frame_recovers_to_the_acknowledged_prefix() {
    let directory = tempfile::tempdir().expect("temporary directory");
    let anchor = TestAnchor::new();
    let mut store = create(directory.path(), &anchor);
    store.append(digest(b"stable"), b"stable envelope").expect("append");
    let checkpoint = store.checkpoint().expect("checkpoint");
    let original = store.committed_bytes;
    drop(store);
    let (encoded, _) = frame(checkpoint.root, 2, digest(b"pending"), b"pending envelope");
    for cut in 1..=encoded.len() {
        let mut file = OpenOptions::new().append(true)
            .open(generation_path(directory.path(), 1)).expect("fault file");
        file.write_all(&encoded[..cut]).expect("partial frame");
        file.sync_all().expect("partial durability");
        drop(file);
        let recovered = open(directory.path(), &anchor).expect("recover unacknowledged suffix");
        assert_eq!(recovered.committed_bytes, original);
        assert_eq!(recovered.get(digest(b"pending")).expect("read"), None);
        assert_eq!(recovered.file.metadata().expect("metadata").len(), original);
        drop(recovered);
    }
}

#[test]
fn acknowledged_truncation_is_never_silently_repaired() {
    let directory = tempfile::tempdir().expect("temporary directory");
    let anchor = TestAnchor::new();
    let mut store = create(directory.path(), &anchor);
    store.append(digest(b"decision"), b"body").expect("append");
    let length = store.committed_bytes;
    drop(store);
    open_regular(&generation_path(directory.path(), 1)).expect("file")
        .set_len(length - 1).expect("fault injection");
    assert!(matches!(open(directory.path(), &anchor), Err(PlannerStoreError::RollbackOrTruncation)));
}

#[test]
fn acknowledged_body_corruption_fails_checksum_validation() {
    let directory = tempfile::tempdir().expect("temporary directory");
    let anchor = TestAnchor::new();
    let mut store = create(directory.path(), &anchor);
    store.append(digest(b"decision"), b"body").expect("append");
    drop(store);
    let mut file = open_regular(&generation_path(directory.path(), 1)).expect("file");
    file.seek(SeekFrom::Start(HEADER_BYTES as u64 + 44)).expect("seek body");
    file.write_all(b"X").expect("corruption");
    file.sync_all().expect("sync");
    drop(file);
    assert!(matches!(open(directory.path(), &anchor), Err(PlannerStoreError::Invalid("frame checksum"))));
}

#[test]
fn unavailable_anchor_poisoning_requires_reopen_and_does_not_publish() {
    let directory = tempfile::tempdir().expect("temporary directory");
    let anchor = TestAnchor::new();
    let mut store = create(directory.path(), &anchor);
    anchor.fail.store(1, Ordering::SeqCst);
    assert!(matches!(store.append(digest(b"decision"), b"body"), Err(PlannerStoreError::AnchorUnavailable)));
    assert!(matches!(store.get(digest(b"decision")), Err(PlannerStoreError::Poisoned)));
    drop(store);
    let mut store = open(directory.path(), &anchor).expect("reconcile old anchor");
    assert_eq!(store.get(digest(b"decision")).expect("read"), None);
    assert!(!store.append(digest(b"decision"), b"body").expect("retry").idempotent);
}

#[test]
fn lost_reply_after_anchor_commit_reconciles_as_one_successful_write() {
    let directory = tempfile::tempdir().expect("temporary directory");
    let anchor = TestAnchor::new();
    let mut store = create(directory.path(), &anchor);
    anchor.fail.store(2, Ordering::SeqCst);
    assert!(store.append(digest(b"decision"), b"body").is_err());
    drop(store);
    let mut store = open(directory.path(), &anchor).expect("reconcile committed anchor");
    let receipt = store.append(digest(b"decision"), b"body").expect("equal replay");
    assert!(receipt.idempotent);
    assert_eq!(receipt.sequence, 1);
}

#[test]
fn pinned_signature_key_is_required_on_reopen() {
    let directory = tempfile::tempdir().expect("temporary directory");
    let anchor = TestAnchor::new();
    drop(create(directory.path(), &anchor));
    let wrong = SigningKey::from_bytes(&[42; 32]).verifying_key();
    assert!(matches!(
        PlannerStoreV1::open(directory.path(), digest(b"store"), wrong, anchor),
        Err(PlannerStoreError::InvalidSignature)
    ));
}

#[test]
fn old_signed_backup_cannot_roll_back_a_newer_frontier() {
    let directory = tempfile::tempdir().expect("temporary directory");
    let restored = tempfile::tempdir().expect("restore directory");
    let anchor = TestAnchor::new();
    let mut store = create(directory.path(), &anchor);
    store.append(digest(b"decision"), b"body").expect("append");
    let backup = store.backup().expect("backup");
    store.append(digest(b"revocation"), b"revoke decision").expect("revoke");
    assert!(matches!(
        PlannerStoreV1::restore_current(restored.path(), &backup, anchor.key.verifying_key(), anchor.clone()),
        Err(PlannerStoreError::AnchorMismatch)
    ));
}

#[test]
fn compaction_and_retention_preserve_complete_history_and_identities() {
    let directory = tempfile::tempdir().expect("temporary directory");
    let anchor = TestAnchor::new();
    let mut store = create(directory.path(), &anchor);
    store.append(digest(b"decision"), b"complete body").expect("decision");
    store.append(digest(b"revocation"), b"revocation envelope").expect("revocation");
    assert_eq!(store.compact().expect("compact").generation, 2);
    assert_eq!(store.retain_generations(1).expect("retention"), 1);
    assert!(!generation_path(directory.path(), 1).exists());
    drop(store);
    let mut store = open(directory.path(), &anchor).expect("reopen");
    assert_eq!(store.get(digest(b"decision")).expect("read"), Some(b"complete body".as_slice()));
    assert_eq!(store.get(digest(b"revocation")).expect("read"), Some(b"revocation envelope".as_slice()));
    assert!(store.append(digest(b"decision"), b"complete body").expect("replay").idempotent);
}

#[test]
fn current_backup_restores_complete_bodies() {
    let directory = tempfile::tempdir().expect("temporary directory");
    let destination = tempfile::tempdir().expect("restore directory");
    let anchor = TestAnchor::new();
    let mut store = create(directory.path(), &anchor);
    store.append(digest(b"decision"), b"body").expect("append");
    let backup = store.backup().expect("backup");
    drop(store);
    let restored = PlannerStoreV1::restore_current(
        destination.path(), &backup, anchor.key.verifying_key(), anchor.clone(),
    ).expect("restore current");
    assert_eq!(restored.get(digest(b"decision")).expect("read"), Some(b"body".as_slice()));
}

#[test]
fn uncommitted_compaction_temporary_file_never_selects_a_generation() {
    let directory = tempfile::tempdir().expect("temporary directory");
    let anchor = TestAnchor::new();
    let mut store = create(directory.path(), &anchor);
    store.append(digest(b"decision"), b"body").expect("append");
    drop(store);
    fs::write(directory.path().join("generation.pending"), b"partial rewrite").expect("crash fixture");
    let mut store = open(directory.path(), &anchor).expect("predecessor remains selected");
    assert_eq!(store.checkpoint().expect("checkpoint").generation, 1);
    store.compact().expect("retry rewrite");
    assert_eq!(store.get(digest(b"decision")).expect("read"), Some(b"body".as_slice()));
}

#[test]
fn envelope_limit_rejects_before_persistence() {
    let directory = tempfile::tempdir().expect("temporary directory");
    let anchor = TestAnchor::new();
    let mut store = create(directory.path(), &anchor);
    let before = store.checkpoint().expect("checkpoint");
    assert!(matches!(
        store.append(digest(b"oversize"), &vec![0; MAX_PLANNER_ENVELOPE_BYTES + 1]),
        Err(PlannerStoreError::LimitExceeded)
    ));
    assert_eq!(store.checkpoint().expect("unchanged"), before);
}

#[test]
fn operating_system_lock_excludes_a_separate_process() {
    let directory = tempfile::tempdir().expect("temporary directory");
    let anchor = TestAnchor::new();
    let _store = create(directory.path(), &anchor);
    let status = std::process::Command::new(std::env::current_exe().expect("test executable"))
        .args(["--exact", "planner_store::tests::subprocess_lock_probe", "--nocapture"])
        .env("HEPTA_PLANNER_LOCK_PROBE", directory.path())
        .status().expect("run child lock probe");
    assert!(status.success());
}

#[test]
fn subprocess_lock_probe() {
    let Some(path) = std::env::var_os("HEPTA_PLANNER_LOCK_PROBE") else { return };
    assert!(matches!(lock_directory(Path::new(&path)), Err(PlannerStoreError::Locked)));
}
