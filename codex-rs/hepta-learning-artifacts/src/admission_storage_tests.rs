use super::*;

use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

use crate::DatasetWithdrawalRegistry;
use crate::DatasetWithdrawalScopeV1;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;

static NEXT_DIRECTORY: AtomicU64 = AtomicU64::new(0);

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        let serial = NEXT_DIRECTORY.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-artifact-admission-storage-{}-{serial}",
            std::process::id()
        ));
        fs::create_dir(&root).fixture("create admission fixture");
        Self(root)
    }

    fn open(&self) -> File {
        File::open(self.0.join("admission")).fixture("open sidecar")
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    StableId::new(value).fixture("valid identity")
}

fn registry() -> DatasetWithdrawalRegistry {
    DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
        authority_domain_id: id("dataset-authority"),
        registry_id: id("withdrawal-registry"),
        scope_id: id("tenant-a"),
    })
}

fn manifest() -> LearningArtifactManifestV2 {
    LearningArtifactManifestV2 {
        artifact_id: id("model-multi-source"),
        kind: ArtifactKind::Model,
        generation: Generation::new(3).fixture("valid generation"),
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![
            digest("dataset-a"),
            digest("dataset-b"),
            digest("dataset-c"),
        ],
        lineage_digests: vec![digest("lineage-a"), digest("lineage-b")],
        predecessor_ids: vec![id("parent-b"), id("-")],
        rollback_predecessor: Some(id("-")),
        bytes_digest: digest("payload"),
        encoded_size_bytes: 7,
        training_code_digest: digest("training"),
        runtime_tuple_digest: digest("runtime"),
        device_profile_digest: digest("device"),
        objective_class_digest: digest("objective"),
        compatibility_digest: digest("compatibility"),
        schema_profile_digest: digest("schema"),
        normalization_digest: digest("normalization"),
        producer_id: id("producer"),
        created_at: 10,
        expires_at: 100,
    }
}

fn admit(manifest: LearningArtifactManifestV2) -> WithdrawalBoundArtifactAdmissionV3 {
    let registry = registry();
    admit_manifest_at_withdrawal_head_v3(&registry, registry.head_digest(), manifest, 20)
        .fixture("admit full manifest")
}

fn read_bound(
    file: File,
    admission: &WithdrawalBoundArtifactAdmissionV3,
) -> Result<
    (
        WithdrawalBoundArtifactAdmissionV3,
        ArtifactAdmissionSnapshotReceiptV3,
    ),
    ArtifactStorageError,
> {
    read_artifact_admission_snapshot_bound(
        file,
        digest("binding"),
        admission.withdrawal_scope_digest,
        admission.validated_manifest.manifest_digest,
        admission.admission_digest,
    )
}

#[test]
fn complete_multi_source_admission_round_trips_and_survives_historical_expiry() {
    let directory = Directory::new();
    let expected = admit(manifest());
    let receipt = write_artifact_admission_snapshot_beneath(
        &directory.0,
        "admission",
        &expected,
        digest("binding"),
    )
    .fixture("persist complete sidecar");
    assert_eq!(
        receipt,
        admission_snapshot_receipt_v3(&expected, digest("binding")).fixture("independent receipt")
    );
    assert_eq!(
        read_artifact_admission_snapshot(directory.open(), receipt).fixture("exact sidecar"),
        expected
    );
    assert_eq!(
        read_bound(directory.open(), &expected).fixture("independent semantic pins"),
        (expected.clone(), receipt)
    );
    assert!(verify_artifact_admission_v3(&expected, expected.withdrawal_head_digest, 101).is_err());
    assert_eq!(
        read_artifact_admission_snapshot(directory.open(), receipt)
            .fixture("historical provenance"),
        expected
    );
    assert_eq!(
        write_artifact_admission_snapshot_beneath(
            &directory.0,
            "admission",
            &expected,
            digest("binding")
        ),
        Err(ArtifactStorageError::AlreadyExists)
    );
}

#[test]
fn maximum_manifest_closure_remains_bounded_and_recoverable() {
    let directory = Directory::new();
    let mut value = manifest();
    value.artifact_id = id(&"a".repeat(128));
    value.producer_id = id(&"p".repeat(128));
    value.source_dataset_digests = (0..MAX_DATASET_INPUTS)
        .map(|n| digest(&format!("dataset-{n}")))
        .collect();
    value.lineage_digests = (0..MAX_LINEAGE_DIGESTS)
        .map(|n| digest(&format!("lineage-{n}")))
        .collect();
    value.predecessor_ids = (0..MAX_PREDECESSORS)
        .map(|n| id(&format!("parent-{n:03}-{}", "x".repeat(116))))
        .collect();
    value.rollback_predecessor = value.predecessor_ids.first().cloned();
    let expected = admit(value);
    let receipt = write_artifact_admission_snapshot_beneath(
        &directory.0,
        "admission",
        &expected,
        digest("binding"),
    )
    .fixture("maximum sidecar");
    assert!(receipt.encoded_bytes < MAX_ARTIFACT_ADMISSION_SNAPSHOT_BYTES);
    assert_eq!(
        read_bound(directory.open(), &expected).fixture("maximum read"),
        (expected, receipt)
    );
}

#[test]
fn dataset_independent_admission_preserves_empty_sources_and_optional_predecessor() {
    let directory = Directory::new();
    let mut value = manifest();
    value.provenance_mode = ProvenanceModeV1::DatasetIndependent;
    value.source_dataset_digests.clear();
    value.predecessor_ids.clear();
    value.rollback_predecessor = None;
    let expected = admit(value);
    let receipt = write_artifact_admission_snapshot_beneath(
        &directory.0,
        "admission",
        &expected,
        digest("binding"),
    )
    .fixture("independent sidecar");
    assert_eq!(
        read_bound(directory.open(), &expected).fixture("independent recovery"),
        (expected, receipt)
    );
}

#[test]
fn rejected_admission_never_creates_a_validation_orphan() {
    let directory = Directory::new();
    let valid = admit(manifest());
    let mut wrong_identity = valid.clone();
    wrong_identity.validated_manifest.manifest.producer_id = id("other-producer");
    let mut expired_at_admission = valid.clone();
    expired_at_admission.admitted_at = 101;
    let mut oversize = valid.clone();
    oversize.validated_manifest.manifest.lineage_digests =
        vec![digest("lineage"); MAX_LINEAGE_DIGESTS + 1];
    let mut unsorted = valid.clone();
    unsorted
        .validated_manifest
        .manifest
        .source_dataset_digests
        .reverse();
    for (index, value) in [wrong_identity, expired_at_admission, oversize, unsorted]
        .iter()
        .enumerate()
    {
        let name = format!("rejected-{index}");
        assert!(
            write_artifact_admission_snapshot_beneath(
                &directory.0,
                &name,
                value,
                digest("binding")
            )
            .is_err()
        );
        assert!(!directory.0.join(name).exists());
    }
    assert_eq!(
        write_artifact_admission_snapshot_beneath(
            &directory.0,
            "zero-binding",
            &valid,
            Digest32::ZERO
        ),
        Err(ArtifactStorageError::InvalidBinding)
    );
    assert!(!directory.0.join("zero-binding").exists());
}

#[test]
fn sidecar_recovery_rejects_identity_drift_wrong_pins_and_noncanonical_bytes() {
    let directory = Directory::new();
    let expected = admit(manifest());
    let original =
        encode_admission_snapshot_v3(&expected, digest("binding")).fixture("canonical bytes");
    let text = String::from_utf8(original.clone()).fixture("canonical text");
    let mut truncated = original.clone();
    truncated.pop();
    let mutated = [
        truncated,
        text.replace('\n', "\r\n").into_bytes(),
        format!("{text}unknown-field\n").into_bytes(),
        text.replacen("\n20\n", "\n020\n", 1).into_bytes(),
        text.replace("\nproducer\n", "\nother-producer\n")
            .into_bytes(),
        text.replace("\nDENY_ALL\n", "\nALLOW_ALL\n").into_bytes(),
    ];
    for bytes in mutated {
        fs::write(directory.0.join("admission"), bytes).fixture("tamper sidecar");
        assert!(read_bound(directory.open(), &expected).is_err());
    }
    fs::write(directory.0.join("admission"), original).fixture("restore sidecar");
    for pins in [
        [
            digest("wrong-binding"),
            expected.withdrawal_scope_digest,
            expected.validated_manifest.manifest_digest,
            expected.admission_digest,
        ],
        [
            digest("binding"),
            digest("wrong-scope"),
            expected.validated_manifest.manifest_digest,
            expected.admission_digest,
        ],
        [
            digest("binding"),
            expected.withdrawal_scope_digest,
            digest("wrong-manifest"),
            expected.admission_digest,
        ],
        [
            digest("binding"),
            expected.withdrawal_scope_digest,
            expected.validated_manifest.manifest_digest,
            digest("wrong-admission"),
        ],
    ] {
        assert!(
            read_artifact_admission_snapshot_bound(
                directory.open(),
                pins[0],
                pins[1],
                pins[2],
                pins[3]
            )
            .is_err()
        );
    }
}

#[test]
fn hostile_collection_counts_and_oversized_file_are_rejected_before_allocation() {
    let directory = Directory::new();
    let expected = admit(manifest());
    let original = String::from_utf8(
        encode_admission_snapshot_v3(&expected, digest("binding")).fixture("bytes"),
    )
    .fixture("text");
    let source_count = expected
        .validated_manifest
        .manifest
        .source_dataset_digests
        .len();
    let lineage_count = expected.validated_manifest.manifest.lineage_digests.len();
    for count_index in [11, 12 + source_count, 13 + source_count + lineage_count] {
        let mut lines: Vec<_> = original.lines().collect();
        lines[count_index] = "18446744073709551615";
        fs::write(
            directory.0.join("admission"),
            format!("{}\n", lines.join("\n")),
        )
        .fixture("hostile count");
        assert_eq!(
            read_bound(directory.open(), &expected),
            Err(ArtifactStorageError::Capacity)
        );
    }
    fs::write(
        directory.0.join("admission"),
        vec![b'x'; MAX_ARTIFACT_ADMISSION_SNAPSHOT_BYTES + 1],
    )
    .fixture("oversized file");
    assert_eq!(
        read_bound(directory.open(), &expected),
        Err(ArtifactStorageError::Capacity)
    );
}

#[test]
fn sidecar_reader_respects_active_writer_locks_and_rejects_tampering() {
    let directory = Directory::new();
    let expected = admit(manifest());
    let receipt = write_artifact_admission_snapshot_beneath(
        &directory.0,
        "admission",
        &expected,
        digest("binding"),
    )
    .fixture("sidecar");
    let held = OpenOptions::new()
        .read(true)
        .write(true)
        .open(directory.0.join("admission"))
        .fixture("writer handle");
    held.try_lock().fixture("writer lock");
    assert_eq!(
        read_artifact_admission_snapshot(directory.open(), receipt),
        Err(ArtifactStorageError::Busy)
    );
    assert_eq!(
        read_bound(directory.open(), &expected),
        Err(ArtifactStorageError::Busy)
    );
    held.unlock().fixture("release lock");
    drop(held);
    let mut wrong_receipt = receipt;
    wrong_receipt.file_digest = digest("wrong-file");
    assert_eq!(
        read_artifact_admission_snapshot(directory.open(), wrong_receipt),
        Err(ArtifactStorageError::Corrupt)
    );
    fs::write(directory.0.join("admission"), b"tampered").fixture("truncate sidecar");
    assert_eq!(
        read_artifact_admission_snapshot(directory.open(), receipt),
        Err(ArtifactStorageError::Corrupt)
    );
}

#[test]
fn compatibility_projection_checks_objective_support_identity_and_all_representable_fields() {
    let admission = admit(manifest());
    let v2 = &admission.validated_manifest.manifest;
    let projected = ArtifactManifest {
        artifact_id: v2.artifact_id.clone(),
        kind: v2.kind,
        generation: v2.generation,
        predecessor_id: None,
        content_digest: v2.bytes_digest,
        objective_digest: v2.objective_class_digest,
        support_digest: admission.validated_manifest.manifest_digest,
        producer_id: v2.producer_id.clone(),
        compatibility_digest: v2.compatibility_digest,
        encoded_size_bytes: v2.encoded_size_bytes,
    };
    assert_eq!(
        validate_admission_registry_projection_v3(&projected, &admission),
        Ok(())
    );
    let mut wrong_objective = projected.clone();
    wrong_objective.objective_digest = digest("wrong-objective");
    let mut wrong_support = projected.clone();
    wrong_support.support_digest = digest("wrong-support");
    let mut wrong_predecessor = projected.clone();
    wrong_predecessor.predecessor_id = Some(id("parent-b"));
    let mut wrong_producer = projected.clone();
    wrong_producer.producer_id = id("wrong-producer");
    let mut wrong_artifact = projected;
    wrong_artifact.artifact_id = id("wrong-artifact");
    for value in [
        wrong_objective,
        wrong_support,
        wrong_predecessor,
        wrong_producer,
        wrong_artifact,
    ] {
        assert_eq!(
            validate_admission_registry_projection_v3(&value, &admission),
            Err(ArtifactStorageError::Semantic)
        );
    }
}

#[cfg(unix)]
#[test]
fn sidecar_writers_reject_symlinks_and_lexical_escape() {
    use std::os::unix::fs::symlink;

    let directory = Directory::new();
    let valid = admit(manifest());
    fs::create_dir(directory.0.join("real")).fixture("real directory");
    symlink(directory.0.join("real"), directory.0.join("alias")).fixture("symlink ancestor");
    symlink(directory.0.join("missing"), directory.0.join("admission"))
        .fixture("dangling final symlink");
    assert_eq!(
        write_artifact_admission_snapshot_beneath(
            &directory.0,
            "alias/sidecar",
            &valid,
            digest("binding")
        ),
        Err(ArtifactStorageError::PathEscape)
    );
    assert_eq!(
        write_artifact_admission_snapshot_beneath(
            &directory.0,
            "admission",
            &valid,
            digest("binding")
        ),
        Err(ArtifactStorageError::AlreadyExists)
    );
    assert_eq!(
        write_artifact_admission_snapshot_beneath(
            &directory.0,
            "../escape",
            &valid,
            digest("binding")
        ),
        Err(ArtifactStorageError::InvalidPath)
    );
    assert!(!directory.0.join("real/sidecar").exists());
}
