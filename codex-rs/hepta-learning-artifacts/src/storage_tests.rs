use super::*;
use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Barrier;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static COUNTER: AtomicU64 = AtomicU64::new(0);

struct TestFile(PathBuf);

impl TestFile {
    fn new() -> Self {
        let sequence = COUNTER.fetch_add(1, Ordering::Relaxed);
        let process = std::process::id();
        let time = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        Self(std::env::temp_dir().join(format!("hepta-artifact-{process}-{time}-{sequence}")))
    }

    fn create(&self) -> Result<CreateOnlyArtifactFile, ArtifactStorageError> {
        CreateOnlyArtifactFile::create(&self.0)
    }

    fn open(&self) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&self.0)
            .unwrap()
    }
}

impl Drop for TestFile {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn register(registry: &mut ArtifactRegistry, name: &str, predecessor: Option<&str>, bytes: &[u8]) {
    registry
        .append(ArtifactEvent::Register {
            event_id: id(&format!("register-{name}")),
            manifest: ArtifactManifest {
                artifact_id: id(name),
                kind: ArtifactKind::Policy,
                generation: Generation::new(if predecessor.is_some() { 2 } else { 1 }).unwrap(),
                predecessor_id: predecessor.map(id),
                content_digest: Digest32::of_bytes(bytes),
                objective_digest: Digest32::of_bytes(b"objective"),
                support_digest: Digest32::of_bytes(b"dataset"),
                producer_id: id("generator"),
                compatibility_digest: Digest32::of_bytes(b"compatibility"),
                encoded_size_bytes: bytes.len() as u64,
            },
        })
        .unwrap();
}

fn binding() -> Digest32 {
    Digest32::of_bytes(b"host-authenticated-scope-fixture-not-a-credential")
}

#[test]
fn snapshot_reopens_exact_history_and_revoked_ancestors() {
    let mut registry = ArtifactRegistry::new();
    register(&mut registry, "old", None, b"old");
    register(&mut registry, "new", Some("old"), b"new");
    registry
        .append(ArtifactEvent::Revoke(StateChange {
            event_id: id("revoke"),
            artifact_id: id("old"),
            evaluator_id: id("independent"),
            reason_digest: Digest32::of_bytes(b"revoked-dataset"),
        }))
        .unwrap();
    let file = TestFile::new();
    let receipt = write_registry_snapshot(file.create().unwrap(), &registry, binding()).unwrap();
    let recovered = read_registry_snapshot(file.open(), receipt).unwrap();
    assert_eq!(recovered.snapshot(), registry.snapshot());
    assert!(!recovered.is_eligible(&id("new")));
    assert!(!recovered.is_eligible(&id("old")));
}

#[test]
fn payload_rejects_wrong_bytes_without_reusing_its_created_target() {
    let mut registry = ArtifactRegistry::new();
    register(&mut registry, "policy", None, b"policy-v1");

    let rejected = TestFile::new();
    assert_eq!(
        write_candidate_payload(
            rejected.create().unwrap(),
            &registry,
            &id("policy"),
            b"wrong",
        ),
        Err(ArtifactStorageError::PayloadMismatch)
    );
    assert_eq!(fs::metadata(&rejected.0).unwrap().len(), 0);

    let file = TestFile::new();
    write_candidate_payload(
        file.create().unwrap(),
        &registry,
        &id("policy"),
        b"policy-v1",
    )
    .unwrap();
    assert_eq!(
        read_candidate_payload(file.open(), &registry, &id("policy")).unwrap(),
        b"policy-v1"
    );
}

#[test]
fn existing_nonempty_file_is_never_reopened_for_writing() {
    let registry = ArtifactRegistry::new();
    let file = TestFile::new();
    write_registry_snapshot(file.create().unwrap(), &registry, binding()).unwrap();
    let before = fs::read(&file.0).unwrap();
    assert_eq!(
        file.create().unwrap_err(),
        ArtifactStorageError::AlreadyExists
    );
    assert_eq!(before, fs::read(&file.0).unwrap());
}

#[test]
fn create_only_capability_debug_is_opaque() {
    let file = TestFile::new();
    let created = file.create().unwrap();
    assert_eq!(format!("{created:?}"), "CreateOnlyArtifactFile(<opaque>)");
    write_registry_snapshot(created, &ArtifactRegistry::new(), binding()).unwrap();
}

#[cfg(unix)]
#[test]
fn created_target_permissions_are_never_wider_than_owner_read_write() {
    use std::os::unix::fs::PermissionsExt;

    let file = TestFile::new();
    let created = file.create().unwrap();
    let mode = fs::metadata(&file.0).unwrap().permissions().mode() & 0o777;
    assert_eq!(mode & !0o600, 0);
    write_registry_snapshot(created, &ArtifactRegistry::new(), binding()).unwrap();
}

#[test]
fn existing_empty_and_truncated_files_are_never_adopted() {
    let empty = TestFile::new();
    fs::write(&empty.0, b"").unwrap();
    assert_eq!(
        empty.create().unwrap_err(),
        ArtifactStorageError::AlreadyExists
    );
    assert_eq!(fs::read(&empty.0).unwrap(), b"");

    let truncated = TestFile::new();
    fs::write(&truncated.0, b"old-acknowledged-snapshot").unwrap();
    fs::write(&truncated.0, b"").unwrap();
    assert_eq!(
        truncated.create().unwrap_err(),
        ArtifactStorageError::AlreadyExists
    );
    assert_eq!(fs::read(&truncated.0).unwrap(), b"");
}

#[cfg(unix)]
#[test]
fn existing_symlinks_are_never_followed_for_creation() {
    use std::os::unix::fs::symlink;

    let victim = TestFile::new();
    fs::write(&victim.0, b"victim").unwrap();
    let linked = TestFile::new();
    symlink(&victim.0, &linked.0).unwrap();
    assert_eq!(
        linked.create().unwrap_err(),
        ArtifactStorageError::AlreadyExists
    );
    assert_eq!(fs::read(&victim.0).unwrap(), b"victim");

    let absent = TestFile::new();
    let dangling = TestFile::new();
    symlink(&absent.0, &dangling.0).unwrap();
    assert_eq!(
        dangling.create().unwrap_err(),
        ArtifactStorageError::AlreadyExists
    );
    assert!(!absent.0.exists());
}

#[test]
fn concurrent_creation_has_exactly_one_winner() {
    let file = TestFile::new();
    let barrier = Arc::new(Barrier::new(8));
    let mut workers = Vec::new();
    for _ in 0..8 {
        let path = file.0.clone();
        let barrier = Arc::clone(&barrier);
        workers.push(std::thread::spawn(move || {
            barrier.wait();
            CreateOnlyArtifactFile::create(path)
        }));
    }

    let mut winner = None;
    let mut existing = 0;
    for worker in workers {
        match worker.join().unwrap() {
            Ok(file) => {
                assert!(winner.replace(file).is_none());
            }
            Err(ArtifactStorageError::AlreadyExists) => existing += 1,
            Err(error) => panic!("unexpected create-only error: {error:?}"),
        }
    }
    assert_eq!(existing, 7);

    let receipt =
        write_registry_snapshot(winner.unwrap(), &ArtifactRegistry::new(), binding()).unwrap();
    assert_eq!(
        read_registry_snapshot(file.open(), receipt)
            .unwrap()
            .snapshot(),
        ArtifactRegistry::new().snapshot()
    );
}

#[test]
fn bytes_appearing_after_atomic_creation_are_indeterminate() {
    let file = TestFile::new();
    let created = file.create().unwrap();
    fs::write(&file.0, b"interference").unwrap();
    assert_eq!(
        write_registry_snapshot(created, &ArtifactRegistry::new(), binding()),
        Err(ArtifactStorageError::Indeterminate)
    );
    assert_eq!(fs::read(&file.0).unwrap(), b"interference");
}

#[test]
fn every_truncation_and_wrong_external_witness_rejects_without_repair() {
    let mut registry = ArtifactRegistry::new();
    register(&mut registry, "policy", None, b"policy");
    let file = TestFile::new();
    let receipt = write_registry_snapshot(file.create().unwrap(), &registry, binding()).unwrap();
    let full = fs::read(&file.0).unwrap();
    for cut in 0..full.len() {
        fs::write(&file.0, &full[..cut]).unwrap();
        assert!(read_registry_snapshot(file.open(), receipt).is_err());
        assert_eq!(fs::read(&file.0).unwrap(), &full[..cut]);
    }
    fs::write(&file.0, &full).unwrap();
    let wrong = RegistrySnapshotReceipt {
        head_digest: Digest32::of_bytes(b"wrong"),
        ..receipt
    };
    assert!(read_registry_snapshot(file.open(), wrong).is_err());
    assert_eq!(fs::read(&file.0).unwrap(), full);
}

#[test]
fn noncanonical_encoding_rejects_even_with_rehashed_file_receipt() {
    let registry = ArtifactRegistry::new();
    let file = TestFile::new();
    let mut receipt =
        write_registry_snapshot(file.create().unwrap(), &registry, binding()).unwrap();
    let altered = format!("HEPTAR01\n{}\n00\n", binding()).into_bytes();
    receipt.file_digest = Digest32::of_bytes(&altered);
    receipt.encoded_bytes = altered.len();
    fs::write(&file.0, altered).unwrap();
    assert!(read_registry_snapshot(file.open(), receipt).is_err());
}

#[test]
fn revoked_payload_cannot_be_loaded_from_current_registry() {
    let mut registry = ArtifactRegistry::new();
    register(&mut registry, "policy", None, b"policy");
    let file = TestFile::new();
    write_candidate_payload(file.create().unwrap(), &registry, &id("policy"), b"policy").unwrap();
    registry
        .append(ArtifactEvent::Revoke(StateChange {
            event_id: id("revoke"),
            artifact_id: id("policy"),
            evaluator_id: id("independent"),
            reason_digest: Digest32::of_bytes(b"reason"),
        }))
        .unwrap();
    assert_eq!(
        read_candidate_payload(file.open(), &registry, &id("policy")),
        Err(ArtifactStorageError::Unavailable)
    );
}

#[test]
fn payload_corruption_and_invalid_receipt_reject() {
    let mut registry = ArtifactRegistry::new();
    register(&mut registry, "policy", None, b"policy");
    let file = TestFile::new();
    write_candidate_payload(file.create().unwrap(), &registry, &id("policy"), b"policy").unwrap();
    fs::write(&file.0, b"tamper").unwrap();
    assert_eq!(
        read_candidate_payload(file.open(), &registry, &id("policy")),
        Err(ArtifactStorageError::PayloadMismatch)
    );
    let invalid = RegistrySnapshotReceipt {
        binding: Digest32::ZERO,
        head_digest: Digest32::ZERO,
        file_digest: Digest32::ZERO,
        records: 0,
        encoded_bytes: 0,
    };
    assert!(matches!(
        read_registry_snapshot(file.open(), invalid),
        Err(ArtifactStorageError::InvalidReceipt)
    ));
}

#[test]
fn zero_binding_leaves_created_file_empty_for_host_reconciliation() {
    let file = TestFile::new();
    assert_eq!(
        write_registry_snapshot(
            file.create().unwrap(),
            &ArtifactRegistry::new(),
            Digest32::ZERO,
        ),
        Err(ArtifactStorageError::InvalidBinding)
    );
    assert_eq!(fs::metadata(&file.0).unwrap().len(), 0);
}
