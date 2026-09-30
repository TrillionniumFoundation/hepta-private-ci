use super::*;
use crate::ArtifactAdmissionError;
use crate::ArtifactClosureError;
use crate::DatasetWithdrawalRegistry;
use crate::DatasetWithdrawalScopeV1;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;
use crate::validate_artifact_publication_v3;
use pretty_assertions::assert_eq;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static COUNTER: AtomicU64 = AtomicU64::new(0);

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        let process = std::process::id();
        let sequence = COUNTER.fetch_add(1, Ordering::Relaxed);
        let time = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .fixture("fixture clock")
            .as_nanos();
        let path =
            std::env::temp_dir().join(format!("hepta-admission-{process}-{time}-{sequence}"));
        fs::create_dir(&path).fixture("create fixture directory");
        Self(path)
    }

    fn open(&self) -> File {
        File::open(self.0.join("admission.bin")).fixture("open admission")
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn id(raw: &str) -> StableId {
    StableId::new(raw).fixture("fixture identifier")
}

fn digest(raw: &str) -> Digest32 {
    Digest32::of_bytes(raw.as_bytes())
}

fn fixture() -> (
    DatasetWithdrawalRegistry,
    WithdrawalBoundArtifactAdmissionV3,
) {
    let registry = DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
        authority_domain_id: id("dataset-authority"),
        registry_id: id("withdrawal-registry"),
        scope_id: id("tenant"),
    });
    let manifest = LearningArtifactManifestV2 {
        artifact_id: id("artifact"),
        kind: ArtifactKind::Model,
        generation: Generation::new(3).fixture("fixture generation"),
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![digest("dataset-b"), digest("dataset-a")],
        lineage_digests: vec![digest("lineage-b"), digest("lineage-a")],
        predecessor_ids: vec![id("parent-b"), id("parent-a")],
        rollback_predecessor: Some(id("parent-a")),
        bytes_digest: digest("payload"),
        encoded_size_bytes: 7,
        training_code_digest: digest("training-code"),
        runtime_tuple_digest: digest("runtime-tuple"),
        device_profile_digest: digest("device-profile"),
        objective_class_digest: digest("objective-class"),
        compatibility_digest: digest("compatibility"),
        schema_profile_digest: digest("schema-profile"),
        normalization_digest: digest("normalization"),
        producer_id: id("producer"),
        created_at: 10,
        expires_at: 100,
    };
    let admission = admit_manifest_at_withdrawal_head_v3(
        &registry,
        registry.head_digest(),
        manifest,
        /*now*/ 20,
    )
    .fixture("admit fixture");
    (registry, admission)
}

#[test]
fn entire_normalized_admission_round_trips_with_each_independent_pin() {
    let directory = Directory::new();
    let (_, admission) = fixture();
    let receipt = write_artifact_admission_beneath(&directory.0, "admission.bin", &admission)
        .fixture("persist complete admission");
    assert_eq!(
        read_artifact_admission(directory.open(), receipt)
            .fixture("recover receipt-pinned admission"),
        admission
    );
    assert_eq!(
        read_artifact_admission_by_digest(directory.open(), admission.admission_digest)
            .fixture("recover admission-pinned bytes"),
        admission
    );
    assert_eq!(
        read_artifact_admission_by_manifest_digest(
            directory.open(),
            admission.validated_manifest.manifest_digest,
        )
        .fixture("recover parent manifest-pinned bytes"),
        admission
    );
}

#[test]
fn historical_recovery_retains_expired_manifest_without_publication_authority() {
    let directory = Directory::new();
    let (registry, admission) = fixture();
    let receipt = write_artifact_admission_beneath(&directory.0, "admission.bin", &admission)
        .fixture("persist historical admission");
    let recovered = read_artifact_admission(directory.open(), receipt).fixture("recover history");
    assert_eq!(recovered, admission);
    assert_eq!(
        validate_artifact_publication_v3(&recovered, &registry, /*now*/ 101),
        Err(ArtifactAdmissionError::Manifest(
            ArtifactClosureError::ManifestTimeWindow
        ))
    );
}

#[test]
fn invalid_metadata_is_rejected_before_creating_an_orphan() {
    let directory = Directory::new();
    let (_, admission) = fixture();
    let mut invalid = vec![admission.clone(); 5];
    invalid[0].admission_digest = digest("wrong-admission");
    invalid[1].validated_manifest.manifest_digest = digest("wrong-manifest");
    invalid[2]
        .validated_manifest
        .manifest
        .source_dataset_digests
        .reverse();
    invalid[3].withdrawal_scope_digest = Digest32::ZERO;
    invalid[4].withdrawal_head_digest = Digest32::ZERO;
    for candidate in invalid {
        assert_eq!(
            write_artifact_admission_beneath(&directory.0, "admission.bin", &candidate),
            Err(ArtifactStorageError::Semantic)
        );
        assert!(!directory.0.join("admission.bin").exists());
    }
    assert_eq!(
        write_artifact_admission_beneath(&directory.0, "../escape.bin", &admission),
        Err(ArtifactStorageError::InvalidPath)
    );
    let receipt = write_artifact_admission_beneath(&directory.0, "admission.bin", &admission)
        .fixture("initial write");
    assert_eq!(
        write_artifact_admission_beneath(&directory.0, "admission.bin", &admission),
        Err(ArtifactStorageError::AlreadyExists)
    );
    assert_eq!(
        read_artifact_admission(directory.open(), receipt).fixture("retained file"),
        admission
    );
}

#[test]
fn every_receipt_field_and_independent_semantic_commitment_is_checked() {
    let directory = Directory::new();
    let (_, admission) = fixture();
    let receipt = write_artifact_admission_beneath(&directory.0, "admission.bin", &admission)
        .fixture("persist admission");
    let wrong = digest("wrong-independent-pin");
    let mut invalid = vec![receipt; 6];
    invalid[0].manifest_digest = wrong;
    invalid[1].admission_digest = wrong;
    invalid[2].withdrawal_scope_digest = wrong;
    invalid[3].withdrawal_head_digest = wrong;
    invalid[4].file_digest = wrong;
    invalid[5].encoded_bytes += 1;
    for candidate in invalid {
        assert_eq!(
            read_artifact_admission(directory.open(), candidate),
            Err(ArtifactStorageError::Corrupt)
        );
    }
    assert_eq!(
        read_artifact_admission_by_digest(directory.open(), wrong),
        Err(ArtifactStorageError::Corrupt)
    );
    assert_eq!(
        read_artifact_admission_by_manifest_digest(directory.open(), wrong),
        Err(ArtifactStorageError::Corrupt)
    );
}

#[test]
fn malformed_and_noncanonical_bytes_reject_even_with_recomputed_file_hash() {
    let directory = Directory::new();
    let (_, admission) = fixture();
    let canonical = encode_artifact_admission(&admission).fixture("canonical fixture");
    let kind_offset = MAGIC.len()
        + 4
        + admission
            .validated_manifest
            .manifest
            .artifact_id
            .as_str()
            .len();
    let provenance_offset = kind_offset + 1 + 8;
    let dataset_count_offset = provenance_offset + 1;
    let dataset_offset = dataset_count_offset + 4;
    let mut malformed = vec![canonical.clone(); 10];
    malformed[0][0] ^= 1;
    malformed[1][kind_offset] = 255;
    malformed[2][provenance_offset] = 255;
    malformed[3][MAGIC.len() + 4] = 255;
    malformed[4].pop();
    malformed[5].push(0);
    malformed[6][dataset_count_offset..dataset_offset].copy_from_slice(&65_u32.to_be_bytes());
    let authority_offset = canonical.len() - 1;
    malformed[7][authority_offset] = 1;
    malformed[8][authority_offset - 1] = 1;
    for offset in 0..32 {
        malformed[9].swap(dataset_offset + offset, dataset_offset + 32 + offset);
    }
    for bytes in malformed {
        fs::write(directory.0.join("admission.bin"), &bytes).fixture("write suspect bytes");
        let suspect_receipt = receipt(&admission, &bytes);
        assert_eq!(
            read_artifact_admission(directory.open(), suspect_receipt),
            Err(ArtifactStorageError::Corrupt)
        );
        assert_eq!(
            read_artifact_admission_by_digest(directory.open(), admission.admission_digest),
            Err(ArtifactStorageError::Corrupt)
        );
    }
}

#[test]
fn forged_semantic_payload_and_sparse_oversized_file_are_rejected() {
    let directory = Directory::new();
    let (registry, admission) = fixture();
    let mut manifest = admission.validated_manifest.manifest.clone();
    manifest.training_code_digest = digest("substituted-training-code");
    let substitution = admit_manifest_at_withdrawal_head_v3(
        &registry,
        registry.head_digest(),
        manifest,
        /*now*/ 20,
    )
    .fixture("self-consistent untrusted substitution");
    write_artifact_admission_beneath(&directory.0, "admission.bin", &substitution)
        .fixture("persist substituted file");
    assert_eq!(
        read_artifact_admission_by_digest(directory.open(), admission.admission_digest),
        Err(ArtifactStorageError::Corrupt)
    );
    assert_eq!(
        read_artifact_admission_by_manifest_digest(
            directory.open(),
            admission.validated_manifest.manifest_digest
        ),
        Err(ArtifactStorageError::Corrupt)
    );
    fs::OpenOptions::new()
        .write(true)
        .open(directory.0.join("admission.bin"))
        .fixture("open sparse fixture")
        .set_len((MAX_ARTIFACT_ADMISSION_BYTES + 1) as u64)
        .fixture("extend sparse fixture");
    assert_eq!(
        read_artifact_admission_by_digest(directory.open(), admission.admission_digest),
        Err(ArtifactStorageError::Capacity)
    );
    let mut expected = receipt(
        &admission,
        &encode_artifact_admission(&admission).fixture("canonical bytes"),
    );
    assert_eq!(
        read_artifact_admission(directory.open(), expected),
        Err(ArtifactStorageError::Capacity)
    );
    expected.encoded_bytes = MAX_ARTIFACT_ADMISSION_BYTES + 1;
    assert_eq!(
        read_artifact_admission(directory.open(), expected),
        Err(ArtifactStorageError::InvalidReceipt)
    );
}
