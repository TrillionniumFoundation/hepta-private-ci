use std::fmt::Debug;
use std::fs;
use std::fs::File;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::*;
use crate::ArtifactEvent;
use crate::ArtifactKind;
use crate::ArtifactRegistry;
use crate::ArtifactState;
use crate::CreateOnlyArtifactFile;
use crate::StateChange;
use crate::write_candidate_payload;
use crate::write_registry_snapshot;

static NEXT_DIRECTORY: AtomicU64 = AtomicU64::new(0);

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected test fixture error: {error:?}"),
    }
}

struct TestDirectory(PathBuf);

impl TestDirectory {
    fn new(label: &str) -> Self {
        let sequence = NEXT_DIRECTORY.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-pinned-{label}-{}-{sequence}",
            std::process::id()
        ));
        must(fs::create_dir(&path));
        Self(path)
    }

    fn path(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }
}

impl Drop for TestDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn manifest(
    artifact_id: &str,
    generation: u64,
    predecessor_id: Option<&str>,
    payload: &[u8],
) -> ArtifactManifest {
    ArtifactManifest {
        artifact_id: id(artifact_id),
        kind: ArtifactKind::Policy,
        generation: must(Generation::new(generation)),
        predecessor_id: predecessor_id.map(id),
        content_digest: Digest32::of_bytes(payload),
        objective_digest: Digest32::of_bytes(b"objective-v1"),
        support_digest: Digest32::of_bytes(b"support-v1"),
        producer_id: id("producer"),
        compatibility_digest: Digest32::of_bytes(b"runtime-compatibility-v1"),
        encoded_size_bytes: payload.len() as u64,
    }
}

fn register(registry: &mut ArtifactRegistry, event_id: &str, manifest: ArtifactManifest) {
    must(registry.append(ArtifactEvent::Register {
        event_id: id(event_id),
        manifest,
    }));
}

fn binding() -> Digest32 {
    Digest32::of_bytes(b"independently-retained-host-epoch-v1")
}

fn write_payload(
    directory: &TestDirectory,
    registry: &ArtifactRegistry,
    manifest: &ArtifactManifest,
    bytes: &[u8],
) {
    must(write_candidate_payload(
        must(CreateOnlyArtifactFile::create(directory.path("payload"))),
        registry,
        &manifest.artifact_id,
        bytes,
    ));
}

fn write_snapshot(
    directory: &TestDirectory,
    registry: &ArtifactRegistry,
) -> RegistrySnapshotReceipt {
    must(write_registry_snapshot(
        must(CreateOnlyArtifactFile::create(directory.path("snapshot"))),
        registry,
        binding(),
    ))
}

fn load(
    directory: &TestDirectory,
    registry_receipt: RegistrySnapshotReceipt,
    manifest: ArtifactManifest,
) -> Result<LoadedPinnedCandidate, PinnedCandidateLoadError> {
    load_pinned_candidate(
        must(File::open(directory.path("snapshot"))),
        must(File::open(directory.path("payload"))),
        PinnedCandidateSpec {
            registry_receipt,
            manifest,
        },
    )
}

#[test]
fn loads_exact_pinned_manifest_and_payload() {
    let directory = TestDirectory::new("valid");
    let bytes = b"policy-v1";
    let expected_manifest = manifest("policy", 1, None, bytes);
    let mut registry = ArtifactRegistry::new();
    register(&mut registry, "register-policy", expected_manifest.clone());
    write_payload(&directory, &registry, &expected_manifest, bytes);
    let receipt = write_snapshot(&directory, &registry);

    let expected = PinnedCandidateSpec {
        registry_receipt: receipt,
        manifest: expected_manifest,
    };
    let loaded = must(load(
        &directory,
        expected.registry_receipt,
        expected.manifest.clone(),
    ));
    let (actual_spec, actual_bytes) = loaded.into_parts();
    assert_eq!(actual_spec, expected);
    assert_eq!(actual_bytes, bytes);
}

#[test]
fn wrong_epoch_binding_is_rejected() {
    let directory = TestDirectory::new("epoch");
    let bytes = b"policy-v1";
    let expected_manifest = manifest("policy", 1, None, bytes);
    let mut registry = ArtifactRegistry::new();
    register(&mut registry, "register-policy", expected_manifest.clone());
    write_payload(&directory, &registry, &expected_manifest, bytes);
    let mut receipt = write_snapshot(&directory, &registry);
    receipt.binding = Digest32::of_bytes(b"wrong-host-epoch");

    assert!(matches!(
        load(&directory, receipt, expected_manifest),
        Err(PinnedCandidateLoadError::Storage(
            ArtifactStorageError::Corrupt
        ))
    ));
}

#[test]
fn objective_and_compatibility_drift_are_pin_mismatches() {
    let directory = TestDirectory::new("manifest-drift");
    let bytes = b"policy-v1";
    let expected_manifest = manifest("policy", 1, None, bytes);
    let mut registry = ArtifactRegistry::new();
    register(&mut registry, "register-policy", expected_manifest.clone());
    write_payload(&directory, &registry, &expected_manifest, bytes);
    let receipt = write_snapshot(&directory, &registry);

    let mut wrong_objective = expected_manifest.clone();
    wrong_objective.objective_digest = Digest32::of_bytes(b"objective-v2");
    assert!(matches!(
        load(&directory, receipt, wrong_objective),
        Err(PinnedCandidateLoadError::PinMismatch)
    ));

    let mut wrong_compatibility = expected_manifest;
    wrong_compatibility.compatibility_digest = Digest32::of_bytes(b"runtime-compatibility-v2");
    assert!(matches!(
        load(&directory, receipt, wrong_compatibility),
        Err(PinnedCandidateLoadError::PinMismatch)
    ));
}

#[test]
fn revoked_ancestor_blocks_loading() {
    let directory = TestDirectory::new("ancestor-revoked");
    let bytes = b"policy-v2";
    let predecessor = manifest("policy-v1", 1, None, b"policy-v1");
    let expected_manifest = manifest("policy-v2", 2, Some("policy-v1"), bytes);
    let mut registry = ArtifactRegistry::new();
    register(&mut registry, "register-v1", predecessor);
    register(&mut registry, "register-v2", expected_manifest.clone());
    write_payload(&directory, &registry, &expected_manifest, bytes);
    must(registry.append(ArtifactEvent::Revoke(StateChange {
        event_id: id("revoke-v1"),
        artifact_id: id("policy-v1"),
        evaluator_id: id("independent-evaluator"),
        reason_digest: Digest32::of_bytes(b"revocation-reason"),
    })));
    let receipt = write_snapshot(&directory, &registry);

    assert_eq!(
        registry.state(&id("policy-v1")),
        Some(ArtifactState::Revoked)
    );
    assert!(matches!(
        load(&directory, receipt, expected_manifest),
        Err(PinnedCandidateLoadError::Storage(
            ArtifactStorageError::Unavailable
        ))
    ));
}

#[test]
fn quarantined_candidate_blocks_loading() {
    let directory = TestDirectory::new("quarantined");
    let bytes = b"policy-v1";
    let expected_manifest = manifest("policy", 1, None, bytes);
    let mut registry = ArtifactRegistry::new();
    register(&mut registry, "register-policy", expected_manifest.clone());
    write_payload(&directory, &registry, &expected_manifest, bytes);
    must(registry.append(ArtifactEvent::Quarantine(StateChange {
        event_id: id("quarantine-policy"),
        artifact_id: expected_manifest.artifact_id.clone(),
        evaluator_id: id("independent-evaluator"),
        reason_digest: Digest32::of_bytes(b"quarantine-reason"),
    })));
    let receipt = write_snapshot(&directory, &registry);

    assert!(matches!(
        load(&directory, receipt, expected_manifest),
        Err(PinnedCandidateLoadError::Storage(
            ArtifactStorageError::Unavailable
        ))
    ));
}

#[test]
fn tampered_payload_is_rejected() {
    let directory = TestDirectory::new("payload-tamper");
    let bytes = b"policy-v1";
    let expected_manifest = manifest("policy", 1, None, bytes);
    let mut registry = ArtifactRegistry::new();
    register(&mut registry, "register-policy", expected_manifest.clone());
    write_payload(&directory, &registry, &expected_manifest, bytes);
    let receipt = write_snapshot(&directory, &registry);
    must(fs::write(directory.path("payload"), b"tampered!"));

    assert!(matches!(
        load(&directory, receipt, expected_manifest),
        Err(PinnedCandidateLoadError::Storage(
            ArtifactStorageError::PayloadMismatch
        ))
    ));
}

fn write_view(
    directory: &TestDirectory,
    registry: &ArtifactRegistry,
    name: &str,
) -> (File, RegistrySnapshotReceipt) {
    let receipt = must(write_registry_snapshot(
        must(CreateOnlyArtifactFile::create(directory.path(name))),
        registry,
        binding(),
    ));
    (must(File::open(directory.path(name))), receipt)
}

#[test]
fn cached_consumer_observes_revocation_before_use_and_cannot_revive_from_backup() {
    let directory = TestDirectory::new("cached-revoke");
    let bytes = b"cached-policy";
    let selected = manifest("policy", 1, None, bytes);
    let mut registry = ArtifactRegistry::new();
    register(&mut registry, "register", selected.clone());
    write_payload(&directory, &registry, &selected, bytes);
    let original = write_snapshot(&directory, &registry);
    let mut cached = RevalidatingCandidate::new(must(load(&directory, original, selected)));
    let (file, current) = write_view(&directory, &registry, "current");
    assert_eq!(
        must(cached.with_current(file, current, <[u8]>::to_vec)),
        bytes
    );
    must(registry.append(ArtifactEvent::Revoke(StateChange {
        event_id: id("revoke"),
        artifact_id: id("policy"),
        evaluator_id: id("external-observer"),
        reason_digest: Digest32::of_bytes(b"withdrawn"),
    })));
    let (file, current) = write_view(&directory, &registry, "revoked");
    assert_eq!(
        cached.with_current(file, current, |_| panic!("revoked bytes reached consumer")),
        Err::<(), _>(PinnedCandidateLoadError::Ineligible)
    );
    assert_eq!(
        cached.with_current(
            must(File::open(directory.path("snapshot"))),
            original,
            |_| panic!("backup revived consumer")
        ),
        Err::<(), _>(PinnedCandidateLoadError::Unavailable)
    );
}

#[test]
fn cached_consumer_rejects_longer_fork_and_backwards_frontier() {
    for fork in [false, true] {
        let directory = TestDirectory::new("cached-history");
        let selected = manifest("policy", 1, None, b"value");
        let mut registry = ArtifactRegistry::new();
        register(&mut registry, "register", selected.clone());
        write_payload(&directory, &registry, &selected, b"value");
        let old = write_snapshot(&directory, &registry);
        let mut cached = RevalidatingCandidate::new(must(load(&directory, old, selected.clone())));
        register(&mut registry, "other", manifest("other", 1, None, b"other"));
        let (file, current) = write_view(&directory, &registry, "extended");
        must(cached.with_current(file, current, |_| ()));
        let (file, receipt) = if fork {
            let mut forked = ArtifactRegistry::new();
            register(&mut forked, "different-event", selected);
            register(&mut forked, "fork-2", manifest("fork-2", 1, None, b"two"));
            register(&mut forked, "fork-3", manifest("fork-3", 1, None, b"three"));
            write_view(&directory, &forked, "fork")
        } else {
            (must(File::open(directory.path("snapshot"))), old)
        };
        assert_eq!(
            cached.with_current(file, receipt, |_| panic!("bad history consumed")),
            Err::<(), _>(PinnedCandidateLoadError::FrontierMismatch)
        );
    }
}

#[test]
fn cached_consumer_rejects_new_scope_and_corrupt_current_file_without_calling_consumer() {
    for scope_change in [false, true] {
        let directory = TestDirectory::new("cached-corrupt");
        let selected = manifest("policy", 1, None, b"value");
        let mut registry = ArtifactRegistry::new();
        register(&mut registry, "register", selected.clone());
        write_payload(&directory, &registry, &selected, b"value");
        let old = write_snapshot(&directory, &registry);
        let mut cached = RevalidatingCandidate::new(must(load(&directory, old, selected)));
        let (file, mut current) = write_view(&directory, &registry, "current");
        if scope_change {
            current.binding = Digest32::of_bytes(b"different-host");
        } else {
            must(fs::write(directory.path("current"), b"truncated"));
        }
        assert!(
            cached
                .with_current(file, current, |_| panic!("invalid view consumed"))
                .is_err()
        );
        assert_eq!(
            cached.with_current(must(File::open(directory.path("snapshot"))), old, |_| ()),
            Err(PinnedCandidateLoadError::Unavailable)
        );
    }
}
