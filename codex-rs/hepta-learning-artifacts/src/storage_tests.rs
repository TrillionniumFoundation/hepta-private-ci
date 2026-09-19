use super::*;
use crate::test_support::FixtureValue;
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
            .fixture("test fixture")
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
            .fixture("test fixture")
    }
}

impl Drop for TestFile {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).fixture("test fixture")
}

fn register(registry: &mut ArtifactRegistry, name: &str, predecessor: Option<&str>, bytes: &[u8]) {
    registry
        .append(ArtifactEvent::Register {
            event_id: id(&format!("register-{name}")),
            manifest: ArtifactManifest {
                artifact_id: id(name),
                kind: ArtifactKind::Policy,
                generation: Generation::new(if predecessor.is_some() { 2 } else { 1 })
                    .fixture("test fixture"),
                predecessor_id: predecessor.map(id),
                content_digest: Digest32::of_bytes(bytes),
                objective_digest: Digest32::of_bytes(b"objective"),
                support_digest: Digest32::of_bytes(b"dataset"),
                producer_id: id("generator"),
                compatibility_digest: Digest32::of_bytes(b"compatibility"),
                encoded_size_bytes: bytes.len() as u64,
            },
        })
        .fixture("test fixture");
}

fn binding() -> Digest32 {
    Digest32::of_bytes(b"host-authenticated-scope-fixture-not-a-credential")
}

fn head_witness() -> RegistryHeadWitnessV1 {
    RegistryHeadWitnessV1 {
        registry_id: id("artifact-registry"),
        generation: Generation::new(2).fixture("test fixture"),
        head_digest: Digest32::of_bytes(b"current-head"),
        predecessor_head_digest: Digest32::ZERO,
        authority_epoch: 3,
        signer_id: id("artifact-owner"),
        signing_key_digest: Digest32::of_bytes(b"signing-key"),
        issued_at: 10,
        expires_at: 100,
    }
}

fn head_requirement(now: u64) -> RegistryHeadRequirementV1 {
    RegistryHeadRequirementV1 {
        registry_id: id("artifact-registry"),
        minimum_generation: Generation::new(1).fixture("test fixture"),
        expected_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 2,
        now,
    }
}

#[test]
fn current_head_witness_round_trips_only_with_current_requirement() {
    let file = TestFile::new();
    let witness = head_witness();
    let receipt = write_registry_head_witness(
        file.create().fixture("test fixture"),
        &witness,
        &head_requirement(20),
        binding(),
    )
    .fixture("test fixture");
    assert_eq!(
        read_registry_head_witness(file.open(), receipt, &head_requirement(20))
            .fixture("test fixture"),
        witness
    );
    assert_eq!(
        read_registry_head_witness(
            file.open(),
            receipt,
            &RegistryHeadRequirementV1 {
                expected_predecessor_head_digest: Digest32::of_bytes(b"new-predecessor"),
                ..head_requirement(20)
            },
        )
        .unwrap_err(),
        ArtifactStorageError::HeadWitnessMismatch
    );
}

#[test]
fn current_head_witness_rejects_stale_or_tampered_receipts() {
    let file = TestFile::new();
    let witness = head_witness();
    let receipt = write_registry_head_witness(
        file.create().fixture("test fixture"),
        &witness,
        &head_requirement(20),
        binding(),
    )
    .fixture("test fixture");
    let mut tampered = receipt;
    tampered.file_digest = Digest32::of_bytes(b"tampered");
    assert_eq!(
        read_registry_head_witness(file.open(), tampered, &head_requirement(20)).unwrap_err(),
        ArtifactStorageError::Corrupt
    );
    assert_eq!(
        read_registry_head_witness(file.open(), receipt, &head_requirement(101)).unwrap_err(),
        ArtifactStorageError::HeadWitnessMismatch
    );
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
        .fixture("test fixture");
    let file = TestFile::new();
    let receipt =
        write_registry_snapshot(file.create().fixture("test fixture"), &registry, binding())
            .fixture("test fixture");
    let recovered = read_registry_snapshot(file.open(), receipt).fixture("test fixture");
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
            rejected.create().fixture("test fixture"),
            &registry,
            &id("policy"),
            b"wrong",
        ),
        Err(ArtifactStorageError::PayloadMismatch)
    );
    assert_eq!(fs::metadata(&rejected.0).fixture("test fixture").len(), 0);

    let file = TestFile::new();
    write_candidate_payload(
        file.create().fixture("test fixture"),
        &registry,
        &id("policy"),
        b"policy-v1",
    )
    .fixture("test fixture");
    assert_eq!(
        read_candidate_payload(file.open(), &registry, &id("policy")).fixture("test fixture"),
        b"policy-v1"
    );
}

#[test]
fn existing_nonempty_file_is_never_reopened_for_writing() {
    let registry = ArtifactRegistry::new();
    let file = TestFile::new();
    write_registry_snapshot(file.create().fixture("test fixture"), &registry, binding())
        .fixture("test fixture");
    let before = fs::read(&file.0).fixture("test fixture");
    assert_eq!(
        file.create().unwrap_err(),
        ArtifactStorageError::AlreadyExists
    );
    assert_eq!(before, fs::read(&file.0).fixture("test fixture"));
}

#[test]
fn create_only_capability_debug_is_opaque() {
    let file = TestFile::new();
    let created = file.create().fixture("test fixture");
    assert_eq!(format!("{created:?}"), "CreateOnlyArtifactFile(<opaque>)");
    write_registry_snapshot(created, &ArtifactRegistry::new(), binding()).fixture("test fixture");
}

#[cfg(unix)]
#[test]
fn created_target_permissions_are_never_wider_than_owner_read_write() {
    use std::os::unix::fs::PermissionsExt;

    let file = TestFile::new();
    let created = file.create().fixture("test fixture");
    let mode = fs::metadata(&file.0)
        .fixture("test fixture")
        .permissions()
        .mode()
        & 0o777;
    assert_eq!(mode & !0o600, 0);
    write_registry_snapshot(created, &ArtifactRegistry::new(), binding()).fixture("test fixture");
}

#[test]
fn existing_empty_and_truncated_files_are_never_adopted() {
    let empty = TestFile::new();
    fs::write(&empty.0, b"").fixture("test fixture");
    assert_eq!(
        empty.create().unwrap_err(),
        ArtifactStorageError::AlreadyExists
    );
    assert_eq!(fs::read(&empty.0).fixture("test fixture"), b"");

    let truncated = TestFile::new();
    fs::write(&truncated.0, b"old-acknowledged-snapshot").fixture("test fixture");
    fs::write(&truncated.0, b"").fixture("test fixture");
    assert_eq!(
        truncated.create().unwrap_err(),
        ArtifactStorageError::AlreadyExists
    );
    assert_eq!(fs::read(&truncated.0).fixture("test fixture"), b"");
}

#[cfg(unix)]
#[test]
fn existing_symlinks_are_never_followed_for_creation() {
    use std::os::unix::fs::symlink;

    let victim = TestFile::new();
    fs::write(&victim.0, b"victim").fixture("test fixture");
    let linked = TestFile::new();
    symlink(&victim.0, &linked.0).fixture("test fixture");
    assert_eq!(
        linked.create().unwrap_err(),
        ArtifactStorageError::AlreadyExists
    );
    assert_eq!(fs::read(&victim.0).fixture("test fixture"), b"victim");

    let absent = TestFile::new();
    let dangling = TestFile::new();
    symlink(&absent.0, &dangling.0).fixture("test fixture");
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
        match worker.join().fixture("test fixture") {
            Ok(file) => {
                assert!(winner.replace(file).is_none());
            }
            Err(ArtifactStorageError::AlreadyExists) => existing += 1,
            Err(error) => panic!("unexpected create-only error: {error:?}"),
        }
    }
    assert_eq!(existing, 7);

    let receipt = write_registry_snapshot(
        winner.fixture("test fixture"),
        &ArtifactRegistry::new(),
        binding(),
    )
    .fixture("test fixture");
    assert_eq!(
        read_registry_snapshot(file.open(), receipt)
            .fixture("test fixture")
            .snapshot(),
        ArtifactRegistry::new().snapshot()
    );
}

#[test]
fn bytes_appearing_after_atomic_creation_are_indeterminate() {
    let file = TestFile::new();
    let created = file.create().fixture("test fixture");
    fs::write(&file.0, b"interference").fixture("test fixture");
    assert_eq!(
        write_registry_snapshot(created, &ArtifactRegistry::new(), binding()),
        Err(ArtifactStorageError::Indeterminate)
    );
    assert_eq!(fs::read(&file.0).fixture("test fixture"), b"interference");
}

#[test]
fn every_truncation_and_wrong_external_witness_rejects_without_repair() {
    let mut registry = ArtifactRegistry::new();
    register(&mut registry, "policy", None, b"policy");
    let file = TestFile::new();
    let receipt =
        write_registry_snapshot(file.create().fixture("test fixture"), &registry, binding())
            .fixture("test fixture");
    let full = fs::read(&file.0).fixture("test fixture");
    for cut in 0..full.len() {
        fs::write(&file.0, &full[..cut]).fixture("test fixture");
        assert!(read_registry_snapshot(file.open(), receipt).is_err());
        assert_eq!(fs::read(&file.0).fixture("test fixture"), &full[..cut]);
    }
    fs::write(&file.0, &full).fixture("test fixture");
    let wrong = RegistrySnapshotReceipt {
        head_digest: Digest32::of_bytes(b"wrong"),
        ..receipt
    };
    assert!(read_registry_snapshot(file.open(), wrong).is_err());
    assert_eq!(fs::read(&file.0).fixture("test fixture"), full);
}

#[test]
fn noncanonical_encoding_rejects_even_with_rehashed_file_receipt() {
    let registry = ArtifactRegistry::new();
    let file = TestFile::new();
    let mut receipt =
        write_registry_snapshot(file.create().fixture("test fixture"), &registry, binding())
            .fixture("test fixture");
    let altered = format!("HEPTAR01\n{}\n00\n", binding()).into_bytes();
    receipt.file_digest = Digest32::of_bytes(&altered);
    receipt.encoded_bytes = altered.len();
    fs::write(&file.0, altered).fixture("test fixture");
    assert!(read_registry_snapshot(file.open(), receipt).is_err());
}

#[test]
fn revoked_payload_cannot_be_loaded_from_current_registry() {
    let mut registry = ArtifactRegistry::new();
    register(&mut registry, "policy", None, b"policy");
    let file = TestFile::new();
    write_candidate_payload(
        file.create().fixture("test fixture"),
        &registry,
        &id("policy"),
        b"policy",
    )
    .fixture("test fixture");
    registry
        .append(ArtifactEvent::Revoke(StateChange {
            event_id: id("revoke"),
            artifact_id: id("policy"),
            evaluator_id: id("independent"),
            reason_digest: Digest32::of_bytes(b"reason"),
        }))
        .fixture("test fixture");
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
    write_candidate_payload(
        file.create().fixture("test fixture"),
        &registry,
        &id("policy"),
        b"policy",
    )
    .fixture("test fixture");
    fs::write(&file.0, b"tamper").fixture("test fixture");
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
            file.create().fixture("test fixture"),
            &ArtifactRegistry::new(),
            Digest32::ZERO,
        ),
        Err(ArtifactStorageError::InvalidBinding)
    );
    assert_eq!(fs::metadata(&file.0).fixture("test fixture").len(), 0);
}

#[test]
fn contained_write_rejects_escape_and_validates_before_create() {
    let root = TestFile::new();
    fs::create_dir(&root.0).fixture("test fixture");
    let mut registry = ArtifactRegistry::new();
    register(&mut registry, "policy", None, b"policy-v1");

    assert_eq!(
        CreateOnlyArtifactFile::create_beneath_trusted_root(&root.0, "../escape").err(),
        Some(ArtifactStorageError::InvalidPath)
    );

    let rejected = PathBuf::from("rejected-payload");
    assert_eq!(
        write_candidate_payload_beneath(&root.0, &rejected, &registry, &id("policy"), b"wrong",),
        Err(ArtifactStorageError::PayloadMismatch)
    );
    assert!(!root.0.join(&rejected).exists());

    let accepted = PathBuf::from("accepted-payload");
    assert_eq!(
        write_candidate_payload_beneath(
            &root.0,
            &accepted,
            &registry,
            &id("policy"),
            b"policy-v1",
        )
        .fixture("test fixture"),
        Digest32::of_bytes(b"policy-v1")
    );
    assert_eq!(
        fs::read(root.0.join(accepted)).fixture("test fixture"),
        b"policy-v1"
    );
    fs::remove_dir_all(&root.0).fixture("test fixture");
}

#[cfg(unix)]
#[test]
fn contained_write_rejects_symlink_ancestor() {
    use std::os::unix::fs::symlink;

    let root = TestFile::new();
    fs::create_dir(&root.0).fixture("test fixture");
    let real = root.0.join("real");
    fs::create_dir(&real).fixture("test fixture");
    symlink(&real, root.0.join("alias")).fixture("test fixture");

    assert_eq!(
        CreateOnlyArtifactFile::create_beneath_trusted_root(&root.0, "alias/payload").err(),
        Some(ArtifactStorageError::PathEscape)
    );
    assert!(!real.join("payload").exists());
    fs::remove_dir_all(&root.0).fixture("test fixture");
}
