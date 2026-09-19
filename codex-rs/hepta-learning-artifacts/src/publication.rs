//! Atomic publication contract across admission and durable artifact state.
//!
//! The crate owns validation and the immutable commit marker. The product host
//! owns exactly one final visibility operation: atomically replacing its
//! authenticated current-pointer with the digest/path of a fully durable commit.
//! Staged files and commit markers are never current merely because they exist.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::str::FromStr;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ArtifactAdmissionError;
use crate::ArtifactLifecycleJournalV2;
use crate::ArtifactLifecycleSnapshotReceiptV2;
use crate::ArtifactRegistry;
use crate::ArtifactStorageError;
use crate::CreateOnlyArtifactFile;
use crate::DatasetWithdrawalRegistry;
use crate::DatasetWithdrawalSnapshotReceiptV1;
use crate::RegistrySnapshotReceipt;
use crate::WithdrawalBoundArtifactAdmissionV3;
use crate::storage::read_bounded;
use crate::storage::write_new;
use crate::validate_artifact_publication_v3;

const COMMIT_MAGIC: &str = "HEPTAP01";
const MAX_COMMIT_BYTES: usize = 8 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactPublicationCommitV1 {
    pub registry_id: StableId,
    pub scope_digest: Digest32,
    pub store_binding: Digest32,
    pub artifact_id: StableId,
    pub artifact_generation: Generation,
    pub predecessor_publication_digest: Digest32,
    pub registry_head_digest: Digest32,
    pub registry_snapshot_file_digest: Digest32,
    pub withdrawal_registry_binding_digest: Digest32,
    pub withdrawal_head_digest: Digest32,
    pub withdrawal_snapshot_file_digest: Digest32,
    pub lifecycle_head_digest: Digest32,
    pub lifecycle_snapshot_file_digest: Digest32,
    pub admission_digest: Digest32,
    pub committed_at: u64,
    pub commit_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ArtifactPublicationCommitReceiptV1 {
    pub binding: Digest32,
    pub commit_digest: Digest32,
    pub file_digest: Digest32,
    pub encoded_bytes: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ArtifactPublicationError {
    Admission(ArtifactAdmissionError),
    InvalidScope,
    InvalidTime,
    StoreBindingMismatch,
    RegistrySnapshotMismatch,
    WithdrawalSnapshotMismatch,
    LifecycleSnapshotMismatch,
    RegistryManifestMismatch,
    AuthorityGrant,
    DigestMismatch,
}

impl fmt::Display for ArtifactPublicationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ArtifactPublicationError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Admission(error) => Some(error),
            Self::InvalidScope
            | Self::InvalidTime
            | Self::StoreBindingMismatch
            | Self::RegistrySnapshotMismatch
            | Self::WithdrawalSnapshotMismatch
            | Self::LifecycleSnapshotMismatch
            | Self::RegistryManifestMismatch
            | Self::AuthorityGrant
            | Self::DigestMismatch => None,
        }
    }
}

impl From<ArtifactAdmissionError> for ArtifactPublicationError {
    fn from(value: ArtifactAdmissionError) -> Self {
        Self::Admission(value)
    }
}

#[allow(clippy::too_many_arguments)]
pub fn prepare_artifact_publication_v1(
    registry_id: StableId,
    scope_digest: Digest32,
    predecessor_publication_digest: Digest32,
    registry: &ArtifactRegistry,
    registry_receipt: RegistrySnapshotReceipt,
    withdrawal_registry: &DatasetWithdrawalRegistry,
    withdrawal_receipt: DatasetWithdrawalSnapshotReceiptV1,
    lifecycle_journal: &ArtifactLifecycleJournalV2,
    lifecycle_receipt: ArtifactLifecycleSnapshotReceiptV2,
    admission: &WithdrawalBoundArtifactAdmissionV3,
    committed_at: u64,
) -> Result<ArtifactPublicationCommitV1, ArtifactPublicationError> {
    if scope_digest.is_zero() {
        return Err(ArtifactPublicationError::InvalidScope);
    }
    if committed_at < admission.admitted_at {
        return Err(ArtifactPublicationError::InvalidTime);
    }
    if admission.authority.grants_any() || admission.validated_manifest.authority.grants_any() {
        return Err(ArtifactPublicationError::AuthorityGrant);
    }
    validate_artifact_publication_v3(admission, withdrawal_registry, committed_at)?;

    if registry_receipt.binding.is_zero()
        || registry_receipt.binding != withdrawal_receipt.binding
        || registry_receipt.binding != lifecycle_receipt.binding
    {
        return Err(ArtifactPublicationError::StoreBindingMismatch);
    }
    let registry_snapshot = registry.snapshot();
    if registry_receipt.head_digest != registry_snapshot.head_digest
        || registry_receipt.records != registry.records().len()
        || registry_receipt.file_digest.is_zero()
    {
        return Err(ArtifactPublicationError::RegistrySnapshotMismatch);
    }
    let withdrawal_snapshot = withdrawal_registry.snapshot();
    if withdrawal_receipt.registry_binding_digest != withdrawal_registry.binding_digest()
        || withdrawal_receipt.registry_binding_digest
            != admission.withdrawal_registry_binding_digest
        || withdrawal_receipt.head_digest != withdrawal_snapshot.head_digest
        || withdrawal_receipt.records != withdrawal_snapshot.records().len()
        || withdrawal_receipt.file_digest.is_zero()
    {
        return Err(ArtifactPublicationError::WithdrawalSnapshotMismatch);
    }
    if lifecycle_receipt.head_digest != lifecycle_journal.head_digest()
        || lifecycle_receipt.records != lifecycle_journal.records().len()
        || lifecycle_receipt.file_digest.is_zero()
    {
        return Err(ArtifactPublicationError::LifecycleSnapshotMismatch);
    }

    let v2 = &admission.validated_manifest.manifest;
    let v1 = registry
        .manifest(&v2.artifact_id)
        .ok_or(ArtifactPublicationError::RegistryManifestMismatch)?;
    if !registry.is_eligible(&v2.artifact_id)
        || v1.kind != v2.kind
        || v1.generation != v2.generation
        || v1.content_digest != v2.bytes_digest
        || v1.objective_digest != v2.objective_class_digest
        || v1.producer_id != v2.producer_id
        || v1.compatibility_digest != v2.compatibility_digest
        || v1.encoded_size_bytes != v2.encoded_size_bytes
    {
        return Err(ArtifactPublicationError::RegistryManifestMismatch);
    }

    let mut commit = ArtifactPublicationCommitV1 {
        registry_id,
        scope_digest,
        store_binding: registry_receipt.binding,
        artifact_id: v2.artifact_id.clone(),
        artifact_generation: v2.generation,
        predecessor_publication_digest,
        registry_head_digest: registry_receipt.head_digest,
        registry_snapshot_file_digest: registry_receipt.file_digest,
        withdrawal_registry_binding_digest: withdrawal_receipt.registry_binding_digest,
        withdrawal_head_digest: withdrawal_receipt.head_digest,
        withdrawal_snapshot_file_digest: withdrawal_receipt.file_digest,
        lifecycle_head_digest: lifecycle_receipt.head_digest,
        lifecycle_snapshot_file_digest: lifecycle_receipt.file_digest,
        admission_digest: admission.admission_digest,
        committed_at,
        commit_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    commit.commit_digest = digest_commit(&commit);
    Ok(commit)
}

pub fn verify_artifact_publication_commit_v1(
    commit: &ArtifactPublicationCommitV1,
    expected_predecessor_publication_digest: Digest32,
    current_withdrawal_registry: &DatasetWithdrawalRegistry,
    current_lifecycle_journal: &ArtifactLifecycleJournalV2,
) -> Result<(), ArtifactPublicationError> {
    if commit.scope_digest.is_zero()
        || commit.store_binding.is_zero()
        || commit.registry_snapshot_file_digest.is_zero()
        || commit.withdrawal_snapshot_file_digest.is_zero()
        || commit.lifecycle_snapshot_file_digest.is_zero()
        || commit.admission_digest.is_zero()
        || commit.authority.grants_any()
    {
        return Err(ArtifactPublicationError::DigestMismatch);
    }
    if commit.predecessor_publication_digest != expected_predecessor_publication_digest {
        return Err(ArtifactPublicationError::DigestMismatch);
    }
    if commit.withdrawal_registry_binding_digest != current_withdrawal_registry.binding_digest()
        || commit.withdrawal_head_digest != current_withdrawal_registry.snapshot().head_digest
    {
        return Err(ArtifactPublicationError::WithdrawalSnapshotMismatch);
    }
    if commit.lifecycle_head_digest != current_lifecycle_journal.head_digest() {
        return Err(ArtifactPublicationError::LifecycleSnapshotMismatch);
    }
    if digest_commit(commit) != commit.commit_digest {
        return Err(ArtifactPublicationError::DigestMismatch);
    }
    Ok(())
}

pub fn write_artifact_publication_commit(
    file: CreateOnlyArtifactFile,
    commit: &ArtifactPublicationCommitV1,
) -> Result<ArtifactPublicationCommitReceiptV1, ArtifactStorageError> {
    if commit.store_binding.is_zero()
        || commit.commit_digest.is_zero()
        || commit.authority.grants_any()
        || digest_commit(commit) != commit.commit_digest
    {
        return Err(ArtifactStorageError::Semantic);
    }
    let bytes = encode_commit(commit)?;
    let receipt = ArtifactPublicationCommitReceiptV1 {
        binding: commit.store_binding,
        commit_digest: commit.commit_digest,
        file_digest: Digest32::of_bytes(&bytes),
        encoded_bytes: bytes.len(),
    };
    write_new(file, &bytes)?;
    Ok(receipt)
}

pub fn read_artifact_publication_commit(
    file: File,
    expected: ArtifactPublicationCommitReceiptV1,
) -> Result<ArtifactPublicationCommitV1, ArtifactStorageError> {
    if expected.binding.is_zero()
        || expected.commit_digest.is_zero()
        || expected.file_digest.is_zero()
        || expected.encoded_bytes == 0
        || expected.encoded_bytes > MAX_COMMIT_BYTES
    {
        return Err(ArtifactStorageError::InvalidReceipt);
    }
    let bytes = read_bounded(
        file,
        MAX_COMMIT_BYTES,
        expected.encoded_bytes as u64,
        ArtifactStorageError::Corrupt,
    )?;
    if Digest32::of_bytes(&bytes) != expected.file_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    let commit = decode_commit(&bytes, expected.binding)?;
    if commit.commit_digest != expected.commit_digest
        || digest_commit(&commit) != commit.commit_digest
        || encode_commit(&commit)? != bytes
    {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(commit)
}

fn digest_commit(commit: &ArtifactPublicationCommitV1) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.publication-commit.v1".to_vec();
    push_id(&mut bytes, &commit.registry_id);
    for digest in [commit.scope_digest, commit.store_binding] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &commit.artifact_id);
    bytes.extend_from_slice(&commit.artifact_generation.get().to_be_bytes());
    for digest in [
        commit.predecessor_publication_digest,
        commit.registry_head_digest,
        commit.registry_snapshot_file_digest,
        commit.withdrawal_registry_binding_digest,
        commit.withdrawal_head_digest,
        commit.withdrawal_snapshot_file_digest,
        commit.lifecycle_head_digest,
        commit.lifecycle_snapshot_file_digest,
        commit.admission_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&commit.committed_at.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn encode_commit(commit: &ArtifactPublicationCommitV1) -> Result<Vec<u8>, ArtifactStorageError> {
    let text = format!(
        "{COMMIT_MAGIC}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n",
        commit.store_binding,
        commit.registry_id,
        commit.scope_digest,
        commit.artifact_id,
        commit.artifact_generation.get(),
        commit.predecessor_publication_digest,
        commit.registry_head_digest,
        commit.registry_snapshot_file_digest,
        commit.withdrawal_registry_binding_digest,
        commit.withdrawal_head_digest,
        commit.withdrawal_snapshot_file_digest,
        commit.lifecycle_head_digest,
        commit.lifecycle_snapshot_file_digest,
        commit.admission_digest,
        commit.committed_at,
        commit.commit_digest,
    );
    if text.len() > MAX_COMMIT_BYTES {
        return Err(ArtifactStorageError::Capacity);
    }
    Ok(text.into_bytes())
}

fn decode_commit(
    bytes: &[u8],
    expected_binding: Digest32,
) -> Result<ArtifactPublicationCommitV1, ArtifactStorageError> {
    let text = std::str::from_utf8(bytes).map_err(|_| ArtifactStorageError::Corrupt)?;
    let fields: Vec<_> = text.lines().collect();
    if fields.len() != 17
        || fields[0] != COMMIT_MAGIC
        || parse_digest(fields[1])? != expected_binding
    {
        return Err(ArtifactStorageError::Corrupt);
    }
    let mut commit = ArtifactPublicationCommitV1 {
        store_binding: expected_binding,
        registry_id: parse_id(fields[2])?,
        scope_digest: parse_digest(fields[3])?,
        artifact_id: parse_id(fields[4])?,
        artifact_generation: Generation::new(parse_u64(fields[5])?)
            .map_err(|_| ArtifactStorageError::Corrupt)?,
        predecessor_publication_digest: parse_digest(fields[6])?,
        registry_head_digest: parse_digest(fields[7])?,
        registry_snapshot_file_digest: parse_digest(fields[8])?,
        withdrawal_registry_binding_digest: parse_digest(fields[9])?,
        withdrawal_head_digest: parse_digest(fields[10])?,
        withdrawal_snapshot_file_digest: parse_digest(fields[11])?,
        lifecycle_head_digest: parse_digest(fields[12])?,
        lifecycle_snapshot_file_digest: parse_digest(fields[13])?,
        admission_digest: parse_digest(fields[14])?,
        committed_at: parse_u64(fields[15])?,
        commit_digest: parse_digest(fields[16])?,
        authority: AuthorityPosture::DENY_ALL,
    };
    let encoded_digest = commit.commit_digest;
    commit.commit_digest = Digest32::ZERO;
    commit.commit_digest = digest_commit(&commit);
    if commit.commit_digest != encoded_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(commit)
}

fn parse_id(value: &str) -> Result<StableId, ArtifactStorageError> {
    StableId::new(value.to_owned()).map_err(|_| ArtifactStorageError::Corrupt)
}

fn parse_digest(value: &str) -> Result<Digest32, ArtifactStorageError> {
    Digest32::from_str(value).map_err(|_| ArtifactStorageError::Corrupt)
}

fn parse_u64(value: &str) -> Result<u64, ArtifactStorageError> {
    value
        .parse::<u64>()
        .map_err(|_| ArtifactStorageError::Corrupt)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use std::fs::File;
    use std::path::Path;
    use std::path::PathBuf;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    use codex_hepta_types::Digest32;

    use super::*;
    use crate::ArtifactEvent;
    use crate::ArtifactKind;
    use crate::ArtifactLifecycleEventV1;
    use crate::ArtifactLifecycleStateV1;
    use crate::ArtifactManifest;
    use crate::DatasetWithdrawalRegistryBindingV1;
    use crate::LearningArtifactManifestV2;
    use crate::LifecycleActorEvidenceV2;
    use crate::LifecycleActorRoleV2;
    use crate::ProvenanceModeV1;
    use crate::admit_manifest_at_withdrawal_head_v3;
    use crate::write_artifact_lifecycle_snapshot;
    use crate::write_dataset_withdrawal_snapshot;
    use crate::write_registry_snapshot;

    static NEXT: AtomicU64 = AtomicU64::new(0);

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid test id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    struct Fixture {
        dir: PathBuf,
    }

    impl Fixture {
        fn new() -> Self {
            let serial = NEXT.fetch_add(1, Ordering::Relaxed);
            let dir = std::env::temp_dir()
                .join(format!("hepta-publication-{}-{serial}", std::process::id()));
            std::fs::create_dir(&dir).expect("fixture dir");
            Self { dir }
        }

        fn path(&self, name: &str) -> PathBuf {
            self.dir.join(name)
        }

        fn create(&self, name: &str) -> CreateOnlyArtifactFile {
            CreateOnlyArtifactFile::create(self.path(name)).expect("create-only file")
        }

        fn open(&self, name: &str) -> File {
            File::open(self.path(name)).expect("open fixture file")
        }
    }

    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.dir);
        }
    }

    fn publishable_state(
        fixture: &Fixture,
    ) -> (
        ArtifactRegistry,
        RegistrySnapshotReceipt,
        DatasetWithdrawalRegistry,
        DatasetWithdrawalSnapshotReceiptV1,
        ArtifactLifecycleJournalV2,
        ArtifactLifecycleSnapshotReceiptV2,
        WithdrawalBoundArtifactAdmissionV3,
    ) {
        let store_binding = digest("store-binding");
        let dataset = digest("dataset");
        let v2 = LearningArtifactManifestV2 {
            artifact_id: id("artifact"),
            kind: ArtifactKind::Model,
            generation: Generation::new(1).expect("generation"),
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: vec![dataset],
            lineage_digests: vec![digest("lineage")],
            predecessor_ids: Vec::new(),
            rollback_predecessor: None,
            bytes_digest: digest("artifact-bytes"),
            encoded_size_bytes: 512,
            training_code_digest: digest("training-code"),
            runtime_tuple_digest: digest("runtime"),
            device_profile_digest: digest("device"),
            objective_class_digest: digest("objective"),
            compatibility_digest: digest("compatibility"),
            schema_profile_digest: digest("schema"),
            normalization_digest: digest("normalization"),
            producer_id: id("producer"),
            created_at: 10,
            expires_at: 100,
        };
        let withdrawal = DatasetWithdrawalRegistry::new(DatasetWithdrawalRegistryBindingV1 {
            registry_id: id("withdrawals"),
            scope_digest: digest("tenant-a"),
            authority_id: id("dataset-owner"),
        })
        .expect("withdrawal registry");
        let admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawal,
            withdrawal.snapshot().head_digest,
            v2.clone(),
            20,
        )
        .expect("admission");

        let mut registry = ArtifactRegistry::new();
        registry
            .append(ArtifactEvent::Register {
                event_id: id("register-artifact"),
                manifest: ArtifactManifest {
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
                },
            })
            .expect("registry append");
        let registry_receipt =
            write_registry_snapshot(fixture.create("registry"), &registry, store_binding)
                .expect("registry snapshot");

        let withdrawal_receipt = write_dataset_withdrawal_snapshot(
            fixture.create("withdrawal"),
            &withdrawal,
            store_binding,
        )
        .expect("withdrawal snapshot");

        let actor = LifecycleActorEvidenceV2 {
            actor_id: id("producer"),
            credential_digest: digest("producer-credential"),
            role: LifecycleActorRoleV2::Producer,
            authority_epoch: 1,
            verified_at: 10,
            expires_at: 100,
        };
        let mut lifecycle = ArtifactLifecycleJournalV2::new();
        lifecycle
            .append(
                Digest32::ZERO,
                &id("producer"),
                actor.clone(),
                ArtifactLifecycleEventV1 {
                    event_id: id("trained"),
                    artifact_id: id("artifact"),
                    prior_state: ArtifactLifecycleStateV1::Proposed,
                    next_state: ArtifactLifecycleStateV1::Trained,
                    actor_id: actor.actor_id.clone(),
                    actor_credential_digest: actor.credential_digest,
                    evidence_digest: admission.validated_manifest.manifest_digest,
                    authority_epoch: actor.authority_epoch,
                    occurred_at: 20,
                },
                20,
            )
            .expect("lifecycle append");
        let lifecycle_receipt = write_artifact_lifecycle_snapshot(
            fixture.create("lifecycle"),
            &lifecycle,
            store_binding,
        )
        .expect("lifecycle snapshot");

        (
            registry,
            registry_receipt,
            withdrawal,
            withdrawal_receipt,
            lifecycle,
            lifecycle_receipt,
            admission,
        )
    }

    fn read_pointer(path: &Path) -> String {
        std::fs::read_to_string(path).expect("read current pointer")
    }

    #[test]
    fn publication_commit_binds_all_durable_frontiers() {
        let fixture = Fixture::new();
        let (
            registry,
            registry_receipt,
            withdrawal,
            withdrawal_receipt,
            lifecycle,
            lifecycle_receipt,
            admission,
        ) = publishable_state(&fixture);
        let commit = prepare_artifact_publication_v1(
            id("learning-artifacts"),
            digest("tenant-a"),
            Digest32::ZERO,
            &registry,
            registry_receipt,
            &withdrawal,
            withdrawal_receipt,
            &lifecycle,
            lifecycle_receipt,
            &admission,
            20,
        )
        .expect("prepare publication");
        let receipt = write_artifact_publication_commit(fixture.create("commit"), &commit)
            .expect("write commit");
        let reopened =
            read_artifact_publication_commit(fixture.open("commit"), receipt).expect("read commit");
        assert_eq!(reopened, commit);
        verify_artifact_publication_commit_v1(&reopened, Digest32::ZERO, &withdrawal, &lifecycle)
            .expect("commit remains current");
    }

    #[test]
    fn crash_before_current_pointer_publish_keeps_previous_generation_visible() {
        let fixture = Fixture::new();
        let current = fixture.path("CURRENT");
        std::fs::write(&current, "previous-commit\n").expect("seed current pointer");

        let (
            registry,
            registry_receipt,
            withdrawal,
            withdrawal_receipt,
            lifecycle,
            lifecycle_receipt,
            admission,
        ) = publishable_state(&fixture);
        let commit = prepare_artifact_publication_v1(
            id("learning-artifacts"),
            digest("tenant-a"),
            digest("previous-commit"),
            &registry,
            registry_receipt,
            &withdrawal,
            withdrawal_receipt,
            &lifecycle,
            lifecycle_receipt,
            &admission,
            20,
        )
        .expect("prepare publication");
        write_artifact_publication_commit(fixture.create("commit"), &commit)
            .expect("write staged commit");

        assert_eq!(read_pointer(&current), "previous-commit\n");

        let next = fixture.path("CURRENT.next");
        std::fs::write(&next, format!("{}\n", commit.commit_digest)).expect("write next pointer");
        std::fs::rename(&next, &current).expect("atomic pointer replace");
        assert_eq!(
            read_pointer(&current),
            format!("{}\n", commit.commit_digest)
        );
    }
}
