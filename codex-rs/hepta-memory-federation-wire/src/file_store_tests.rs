use std::fs::DirBuilder;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::symlink;
use std::process::Command;
use std::process::Stdio;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::*;
use crate::*;

static NEXT_DIRECTORY: AtomicU64 = AtomicU64::new(0);
const NOW: u64 = 8_000_000;
const CHILD_EXIT: i32 = 73;

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        let nonce = NEXT_DIRECTORY.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-federation-store-{}-{nonce}",
            std::process::id()
        ));
        DirBuilder::new()
            .mode(0o700)
            .create(&path)
            .expect("private directory");
        Self(path)
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn open(directory: &Path) -> FileFederationRecoveryStoreV1 {
    FileFederationRecoveryStoreV1::open(directory, 1024 * 1024).expect("open store")
}

#[test]
fn reopen_preserves_the_committed_snapshot() {
    let directory = Directory::new();
    let mut store = open(&directory.0);
    assert_eq!(store.load().expect("empty"), None);
    store.store(b"first").expect("persist first");
    store.store(b"second").expect("replace");
    drop(store);
    assert_eq!(
        open(&directory.0).load().expect("reopen"),
        Some(b"second".to_vec())
    );
}

#[test]
fn second_writer_is_fenced_without_deleting_the_lock_inode() {
    let directory = Directory::new();
    let store = open(&directory.0);
    assert!(matches!(
        FileFederationRecoveryStoreV1::open(&directory.0, 100),
        Err(FederationRecoveryError::StoreLocked)
    ));
    let inode = fs::metadata(directory.0.join(LOCK))
        .expect("lock metadata")
        .ino();
    drop(store);
    let _store = open(&directory.0);
    assert_eq!(
        fs::metadata(directory.0.join(LOCK))
            .expect("same lock")
            .ino(),
        inode
    );
}

#[test]
fn byte_limit_rejection_does_not_replace_the_old_snapshot() {
    let directory = Directory::new();
    let mut store = FileFederationRecoveryStoreV1::open(&directory.0, 4).expect("small store");
    store.store(b"old").expect("old value");
    assert_eq!(
        store.store(b"large"),
        Err(FederationRecoveryError::StoreCapacityExceeded)
    );
    assert_eq!(store.load().expect("old remains"), Some(b"old".to_vec()));
    fs::write(directory.0.join(SNAPSHOT), b"oversized").expect("fixture corruption");
    assert_eq!(
        store.load(),
        Err(FederationRecoveryError::StoreCapacityExceeded)
    );
}

#[test]
fn pre_rename_failure_is_retryable_and_keeps_the_prior_snapshot() {
    let directory = Directory::new();
    let mut store = open(&directory.0);
    store.store(b"old").expect("old value");
    store.fail_at = Some(FailurePoint::BeforeRename);
    assert_eq!(
        store.store(b"new"),
        Err(FederationRecoveryError::StoreUnavailable)
    );
    assert_eq!(store.load().expect("old remains"), Some(b"old".to_vec()));
    store.fail_at = None;
    store.store(b"retry").expect("retry succeeds");
}

#[test]
fn ambiguous_commit_poison_fences_stale_retry_until_reopen() {
    let directory = Directory::new();
    let mut store = open(&directory.0);
    store.store(b"old").expect("old value");
    store.fail_at = Some(FailurePoint::AfterRename);
    assert_eq!(
        store.store(b"new"),
        Err(FederationRecoveryError::StoreIndeterminate)
    );
    assert_eq!(
        store.store(b"stale"),
        Err(FederationRecoveryError::StoreIndeterminate)
    );
    assert_eq!(
        store.load(),
        Err(FederationRecoveryError::StoreIndeterminate)
    );
    drop(store);
    assert_eq!(
        open(&directory.0).load().expect("recover visible commit"),
        Some(b"new".to_vec())
    );
}

#[test]
fn symlink_and_directory_replacement_fail_closed() {
    let directory = Directory::new();
    let link = directory.0.join("alias");
    symlink(&directory.0, &link).expect("directory symlink");
    assert!(matches!(
        FileFederationRecoveryStoreV1::open(&link, 100),
        Err(FederationRecoveryError::StoreInvalidPath)
    ));
    fs::remove_file(link).expect("remove symlink");
    let mut store = open(&directory.0);
    symlink(directory.0.join(LOCK), directory.0.join(SNAPSHOT)).expect("snapshot symlink");
    assert_eq!(store.load(), Err(FederationRecoveryError::StoreInvalidPath));
    fs::remove_file(directory.0.join(SNAPSHOT)).expect("remove snapshot symlink");
    fs::remove_file(directory.0.join(LOCK)).expect("replace locked path");
    assert_eq!(
        store.store(b"new"),
        Err(FederationRecoveryError::StoreInvalidPath)
    );
}

#[test]
fn incomplete_staging_is_discarded_only_under_the_exclusive_lock() {
    let directory = Directory::new();
    let mut store = open(&directory.0);
    store.store(b"committed").expect("old value");
    drop(store);
    let mut pending = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(directory.0.join(PENDING))
        .expect("stale staging");
    pending
        .write_all(b"incomplete")
        .expect("partial staging bytes");
    drop(pending);
    let mut store = open(&directory.0);
    assert!(!directory.0.join(PENDING).exists());
    assert_eq!(
        store.load().expect("load prior commit"),
        Some(b"committed".to_vec())
    );
}

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("identity")
}

fn limits() -> FederationRecoveryLimitsV1 {
    FederationRecoveryLimitsV1 {
        replay_capacity: 32,
        replay_per_peer_capacity: 8,
        attempt_capacity: 32,
        attempt_per_peer_capacity: 8,
    }
}

fn credentials() -> PeerCredentialRegistryV1 {
    let mut registry = PeerCredentialRegistryV1::new();
    for (sender, receiver, key, byte) in [
        ("peer-a", "peer-b", "key-a-b", 41),
        ("peer-b", "peer-a", "key-b-a", 42),
    ] {
        registry
            .enroll(
                PeerCredentialV1::new(
                    id(sender),
                    id(receiver),
                    id(key),
                    1,
                    NOW - 100,
                    NOW + 100_000,
                    [byte; FEDERATION_MAC_KEY_BYTES],
                )
                .expect("credential"),
            )
            .expect("enroll");
    }
    registry
}

fn query() -> FederationQueryMessageV1 {
    FederationQueryMessageV1 {
        query_id: id("process-query"),
        query_binding_digest: Digest32::of_bytes(b"process-query"),
        scope_digest: Digest32::of_bytes(b"scope"),
        purpose_digest: Digest32::of_bytes(b"purpose"),
        generation_vector_digest: Digest32::of_bytes(b"generation"),
        maximum_results: 4,
    }
}

fn frame(message: FederationWireMessageV1, nonce: u8) -> Vec<u8> {
    let registry = credentials();
    let credential = registry
        .require_current(&id("peer-a"), &id("peer-b"), &id("key-a-b"), 1, NOW)
        .expect("current");
    let frame = AuthenticatedFederationFrameV1::seal(
        credential,
        NOW,
        NOW + 20_000,
        FederationNonceV1::from_bytes([nonce; FEDERATION_NONCE_BYTES]),
        message,
    )
    .expect("seal");
    let (schemas, codec) = registered_codec_v1().expect("codec");
    encode_registered_frame_v1(&schemas, &codec, &frame).expect("encode")
}

fn host(directory: &Path, now: u64) -> FederationWireHostV1<FileFederationRecoveryStoreV1> {
    let mut host = FederationWireHostV1::open(
        id("peer-b"),
        credentials(),
        32,
        8,
        limits(),
        open(directory),
        now,
    )
    .expect("open real file-backed host");
    host.bind_outbound_credential(
        id("peer-a"),
        FederationOutboundCredentialV1::new(id("key-b-a"), 1).expect("selector"),
    )
    .expect("bind");
    host
}

// Invoked by the parent test in a real child process. exit() deliberately skips
// Rust destructors: all durable state must already precede the exposed reply.
#[test]
fn recovery_process_worker() {
    let Some(directory) = std::env::var_os("HEPTA_FEDERATION_RECOVERY_TEST_DIRECTORY") else {
        return;
    };
    let mut host = host(Path::new(&directory), NOW);
    let request = query();
    assert!(matches!(
        host.admit(
            &id("peer-a"),
            &frame(FederationWireMessageV1::Query(request.clone()), 31),
            NOW + 1
        )
        .expect("admit query"),
        FederationHostAdmissionV1::Query(_)
    ));
    let cancel = FederationCancelMessageV1 {
        query_id: request.query_id,
        query_binding_digest: request.query_binding_digest,
        cancellation_id: id("process-cancel"),
        reason: FederationCancellationReasonV1::CallerCancelled,
    };
    assert!(matches!(
        host.admit(
            &id("peer-a"),
            &frame(FederationWireMessageV1::Cancel(cancel), 32),
            NOW + 2
        )
        .expect("durable cancellation before ACK"),
        FederationHostAdmissionV1::Reply(_)
    ));
    std::process::exit(CHILD_EXIT);
}

#[test]
fn real_process_restart_preserves_host_replay_and_cancellation_fences() {
    let directory = Directory::new();
    let mut child = Command::new(std::env::current_exe().expect("test executable"))
        .args([
            "--exact",
            "file_store::tests::recovery_process_worker",
            "--nocapture",
        ])
        .env("HEPTA_FEDERATION_RECOVERY_TEST_DIRECTORY", &directory.0)
        .stdout(Stdio::null())
        .stderr(Stdio::inherit())
        .spawn()
        .expect("child process");
    let deadline = Instant::now() + Duration::from_secs(20);
    let status = loop {
        if let Some(status) = child.try_wait().expect("observe child") {
            break status;
        }
        if Instant::now() >= deadline {
            child.kill().expect("stop hung recovery fixture");
            let _ = child.wait();
            panic!("recovery fixture exceeded bounded process deadline");
        }
        std::thread::sleep(Duration::from_millis(10));
    };
    assert_eq!(status.code(), Some(CHILD_EXIT));
    let mut host = host(&directory.0, NOW + 3);
    assert!(matches!(
        host.admit(
            &id("peer-a"),
            &frame(FederationWireMessageV1::Query(query()), 31),
            NOW + 4
        ),
        Err(FederationHostError::Recovery(
            FederationRecoveryError::Replay
        ))
    ));
    let mut recovery = DurableFederationStateV1::restore(
        id("peer-b"),
        limits(),
        NOW + 4,
        &host.recovery_snapshot().expect("recovered snapshot"),
    )
    .expect("restore");
    assert_eq!(
        recovery.observe_terminal(
            &id("peer-a"),
            &query().query_id,
            query().query_binding_digest,
            Digest32::of_bytes(b"late"),
            NOW + 5
        ),
        Err(FederationRecoveryError::Cancelled)
    );
    assert_eq!(host.local_peer_id().as_str(), "peer-b");
}
