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
