use super::*;
use std::fs::File;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

use crate::ArtifactKind;
use crate::ArtifactManifest;
use crate::ArtifactStorageError;
use crate::CreateOnlyArtifactFile;
use crate::read_candidate_payload;
use crate::read_registry_snapshot;
use crate::write_candidate_payload;
use crate::write_registry_snapshot;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn dataset() -> Digest32 {
    Digest32::of_bytes(b"explicit-dataset-snapshot")
}

fn notice() -> DatasetRevocationRequest {
    DatasetRevocationRequest {
        operation_id: id("source-operation-1"),
        dataset_digest: dataset(),
        source_revocation_digest: Digest32::of_bytes(b"independent-source-notice-fixture"),
        evaluator_id: id("evaluator"),
    }
}

fn register(
    registry: &mut ArtifactRegistry,
    name: &str,
    parent: Option<&str>,
    support: Digest32,
    producer: &str,
) {
    registry
        .append(ArtifactEvent::Register {
            event_id: id(&format!("register-{name}")),
            manifest: ArtifactManifest {
                artifact_id: id(name),
                kind: ArtifactKind::Policy,
                generation: Generation::new(if parent.is_some() { 2 } else { 1 }).unwrap(),
                predecessor_id: parent.map(id),
                content_digest: Digest32::of_bytes(name.as_bytes()),
                objective_digest: Digest32::of_bytes(b"objective"),
                support_digest: support,
                producer_id: id(producer),
                compatibility_digest: Digest32::of_bytes(b"compatibility"),
                encoded_size_bytes: name.len() as u64,
            },
        })
        .unwrap();
}

fn head(registry: &ArtifactRegistry) -> Digest32 {
    registry
        .records()
        .last()
        .map_or(Digest32::ZERO, |r| r.chain_digest)
}

#[test]
fn batch_revokes_direct_targets_and_blocks_descendants_without_mutating_input() {
    let mut registry = ArtifactRegistry::new();
    register(
        &mut registry,
        "a",
        /*parent*/ None,
        dataset(),
        "generator",
    );
    register(
        &mut registry,
        "b",
        /*parent*/ None,
        dataset(),
        "generator",
    );
    register(
        &mut registry,
        "child",
        Some("a"),
        Digest32::of_bytes(b"other"),
        "generator",
    );
    register(
        &mut registry,
        "unrelated",
        /*parent*/ None,
        Digest32::of_bytes(b"other"),
        "generator",
    );
    let before = registry.snapshot();
    let prepared = prepare_dataset_revocation(&registry, head(&registry), &notice()).unwrap();
    assert_eq!(registry.snapshot(), before);
    assert_eq!(prepared.summary().direct_artifacts, vec![id("a"), id("b")]);
    assert_eq!(prepared.summary().appended, 2);
    assert_eq!(prepared.summary().authority, AuthorityPosture::DENY_ALL);
    for name in ["a", "b", "child"] {
        assert!(!prepared.registry().is_eligible(&id(name)));
    }
    assert!(prepared.registry().is_eligible(&id("unrelated")));
}

#[test]
fn stale_snapshot_missing_dataset_and_empty_notice_reject() {
    let mut registry = ArtifactRegistry::new();
    register(
        &mut registry,
        "a",
        /*parent*/ None,
        dataset(),
        "generator",
    );
    let before = registry.snapshot();
    assert_eq!(
        prepare_dataset_revocation(&registry, Digest32::ZERO, &notice()).unwrap_err(),
        DatasetRevocationError::StaleSnapshot
    );
    let mut request = notice();
    request.dataset_digest = Digest32::of_bytes(b"absent");
    assert_eq!(
        prepare_dataset_revocation(&registry, head(&registry), &request).unwrap_err(),
        DatasetRevocationError::NoMatchingArtifacts
    );
    request.source_revocation_digest = Digest32::ZERO;
    assert_eq!(
        prepare_dataset_revocation(&registry, head(&registry), &request).unwrap_err(),
        DatasetRevocationError::EmptyDigest
    );
    assert_eq!(registry.snapshot(), before);
}

#[test]
fn identical_retry_reuses_existing_events_and_history() {
    let mut registry = ArtifactRegistry::new();
    register(
        &mut registry,
        "a",
        /*parent*/ None,
        dataset(),
        "generator",
    );
    let first = prepare_dataset_revocation(&registry, head(&registry), &notice()).unwrap();
    let retry =
        prepare_dataset_revocation(first.registry(), head(first.registry()), &notice()).unwrap();
    assert_eq!(retry.registry().snapshot(), first.registry().snapshot());
    assert_eq!(retry.summary().appended, 0);
    assert_eq!(retry.summary().replayed, 1);
    assert_eq!(
        retry.summary().request_digest,
        first.summary().request_digest
    );
}

#[test]
fn changed_notice_or_evaluator_under_same_operation_conflicts() {
    let mut registry = ArtifactRegistry::new();
    register(
        &mut registry,
        "a",
        /*parent*/ None,
        dataset(),
        "generator",
    );
    let first = prepare_dataset_revocation(&registry, head(&registry), &notice()).unwrap();
    let before = first.registry().snapshot();
    for field in ["notice", "evaluator"] {
        let mut request = notice();
        if field == "notice" {
            request.source_revocation_digest = Digest32::of_bytes(b"changed-notice");
        } else {
            request.evaluator_id = id("different-evaluator");
        }
        assert!(matches!(
            prepare_dataset_revocation(first.registry(), head(first.registry()), &request),
            Err(DatasetRevocationError::Registry(
                ArtifactRegistryError::IdentityConflict(_)
            ))
        ));
        assert_eq!(first.registry().snapshot(), before);
    }
}

#[test]
fn later_target_role_collision_discards_entire_preparation() {
    let mut registry = ArtifactRegistry::new();
    register(
        &mut registry,
        "a",
        /*parent*/ None,
        dataset(),
        "generator",
    );
    register(
        &mut registry,
        "z",
        /*parent*/ None,
        dataset(),
        "evaluator",
    );
    let before = registry.snapshot();
    assert!(matches!(
        prepare_dataset_revocation(&registry, head(&registry), &notice()),
        Err(DatasetRevocationError::Registry(
            ArtifactRegistryError::ProducerSelfEvaluates(_)
        ))
    ));
    assert_eq!(registry.snapshot(), before);
    assert!(registry.is_eligible(&id("a")));
}

#[test]
fn quarantined_targets_revoke_and_previously_revoked_targets_are_reported() {
    let mut registry = ArtifactRegistry::new();
    register(
        &mut registry,
        "a",
        /*parent*/ None,
        dataset(),
        "generator",
    );
    register(
        &mut registry,
        "b",
        /*parent*/ None,
        dataset(),
        "generator",
    );
    let change = |artifact: &str| StateChange {
        event_id: id(&format!("prior-{artifact}")),
        artifact_id: id(artifact),
        evaluator_id: id("other-evaluator"),
        reason_digest: Digest32::of_bytes(b"prior-reason"),
    };
    registry
        .append(ArtifactEvent::Quarantine(change("a")))
        .unwrap();
    registry.append(ArtifactEvent::Revoke(change("b"))).unwrap();
    let prepared = prepare_dataset_revocation(&registry, head(&registry), &notice()).unwrap();
    assert_eq!(prepared.summary().appended, 1);
    assert_eq!(prepared.summary().already_revoked, 1);
    assert_eq!(
        prepared.registry().state(&id("a")),
        Some(ArtifactState::Revoked)
    );
    assert_eq!(
        prepared.registry().state(&id("b")),
        Some(ArtifactState::Revoked)
    );
}

#[test]
fn target_quota_rejects_without_partial_registry_mutation() {
    let mut registry = ArtifactRegistry::new();
    for index in 0..=MAX_DIRECT_TARGETS {
        register(
            &mut registry,
            &format!("artifact-{index}"),
            /*parent*/ None,
            dataset(),
            "generator",
        );
    }
    let before = registry.snapshot();
    assert_eq!(
        prepare_dataset_revocation(&registry, head(&registry), &notice()).unwrap_err(),
        DatasetRevocationError::Capacity
    );
    assert_eq!(registry.snapshot(), before);
}

struct Files(PathBuf);

impl Files {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-dataset-revoke-{}-{serial}",
            std::process::id()
        ));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn create(&self, name: &str) -> CreateOnlyArtifactFile {
        CreateOnlyArtifactFile::create(self.0.join(name)).unwrap()
    }

    fn read(&self, name: &str) -> File {
        File::open(self.0.join(name)).unwrap()
    }
}

impl Drop for Files {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[test]
fn persisted_batch_reopens_and_blocks_candidate_but_keeps_clean_rollback() {
    let files = Files::new();
    let binding = Digest32::of_bytes(b"authorized-registry-scope-fixture");
    let mut registry = ArtifactRegistry::new();
    register(
        &mut registry,
        "baseline",
        /*parent*/ None,
        Digest32::of_bytes(b"clean-dataset"),
        "generator",
    );
    register(
        &mut registry,
        "candidate",
        Some("baseline"),
        dataset(),
        "generator",
    );
    write_candidate_payload(
        files.create("baseline"),
        &registry,
        &id("baseline"),
        b"baseline",
    )
    .unwrap();
    write_candidate_payload(
        files.create("candidate"),
        &registry,
        &id("candidate"),
        b"candidate",
    )
    .unwrap();
    let old_witness = write_registry_snapshot(files.create("old"), &registry, binding).unwrap();
    let prepared = prepare_dataset_revocation(&registry, head(&registry), &notice()).unwrap();
    let current_witness =
        write_registry_snapshot(files.create("current"), prepared.registry(), binding).unwrap();
    assert_eq!(
        read_registry_snapshot(files.read("old"), old_witness)
            .unwrap()
            .snapshot(),
        registry.snapshot()
    );
    assert!(read_registry_snapshot(files.read("old"), current_witness).is_err());
    let current = read_registry_snapshot(files.read("current"), current_witness).unwrap();
    assert_eq!(current.snapshot(), prepared.registry().snapshot());
    assert_eq!(
        read_candidate_payload(files.read("candidate"), &current, &id("candidate")),
        Err(ArtifactStorageError::Unavailable)
    );
    assert_eq!(
        read_candidate_payload(files.read("baseline"), &current, &id("baseline")).unwrap(),
        b"baseline"
    );
    let retry = prepare_dataset_revocation(&current, head(&current), &notice()).unwrap();
    assert_eq!(retry.registry().snapshot(), current.snapshot());
}
