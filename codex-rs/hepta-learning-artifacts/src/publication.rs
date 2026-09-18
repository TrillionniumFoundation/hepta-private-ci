//! Withdrawal-bound staging contract for durable artifact publication.
//!
//! The crate cannot make two independent host stores atomically durable. Instead,
//! this module makes the required saga explicit and fail-closed: the validated V3
//! admission, scoped withdrawal frontier, exact V1 registry predecessor, appended
//! event, resulting registry head and durable snapshot binding are sealed into one
//! deterministic transaction digest. The host must hold its writer fence while
//! preparing, revalidating and publishing the create-only snapshot/witness.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{Digest32, StableId};

use crate::{
    ArtifactAdmissionError, ArtifactEvent, ArtifactManifest, ArtifactRegistry,
    ArtifactRegistryError, DatasetWithdrawalRegistry, ProvenanceModeV1, RegistrySnapshotReceipt,
    WithdrawalBoundArtifactAdmissionV3, validate_artifact_publication_v3,
};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactPublicationTransactionV3 {
    pub admission_digest: Digest32,
    pub withdrawal_binding_digest: Digest32,
    pub withdrawal_head_digest: Digest32,
    pub expected_registry_head_digest: Digest32,
    pub registry_event_digest: Digest32,
    pub resulting_registry_head_digest: Digest32,
    pub transaction_digest: Digest32,
}

#[derive(Clone, Debug)]
pub struct PreparedArtifactPublicationV3 {
    registry: ArtifactRegistry,
    transaction: ArtifactPublicationTransactionV3,
}

impl PreparedArtifactPublicationV3 {
    #[must_use]
    pub fn registry(&self) -> &ArtifactRegistry {
        &self.registry
    }

    #[must_use]
    pub fn transaction(&self) -> &ArtifactPublicationTransactionV3 {
        &self.transaction
    }

    #[must_use]
    pub fn snapshot_binding(&self) -> Digest32 {
        self.transaction.transaction_digest
    }

    pub fn validate_snapshot_receipt(
        &self,
        receipt: &RegistrySnapshotReceipt,
    ) -> Result<(), ArtifactPublicationError> {
        if receipt.binding != self.transaction.transaction_digest
            || receipt.head_digest != self.transaction.resulting_registry_head_digest
            || receipt.records != self.registry.records().len()
        {
            return Err(ArtifactPublicationError::SnapshotReceiptMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ArtifactPublicationError {
    Admission(ArtifactAdmissionError),
    Registry(ArtifactRegistryError),
    RegistryHeadChanged,
    UnsupportedMultiPredecessor,
    UnsupportedMultiDataset,
    RollbackProjectionMismatch,
    SnapshotReceiptMismatch,
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
            Self::Registry(error) => Some(error),
            Self::RegistryHeadChanged
            | Self::UnsupportedMultiPredecessor
            | Self::UnsupportedMultiDataset
            | Self::RollbackProjectionMismatch
            | Self::SnapshotReceiptMismatch => None,
        }
    }
}

impl From<ArtifactAdmissionError> for ArtifactPublicationError {
    fn from(value: ArtifactAdmissionError) -> Self {
        Self::Admission(value)
    }
}

impl From<ArtifactRegistryError> for ArtifactPublicationError {
    fn from(value: ArtifactRegistryError) -> Self {
        Self::Registry(value)
    }
}

/// Stage one V3-admitted artifact into the stable V1 durable registry.
///
/// The V1 registry has a single-predecessor lineage shape. A V2 manifest with
/// multiple predecessors is therefore rejected rather than silently dropping
/// lineage. The V1 support digest is the complete validated V2 manifest digest,
/// so every V2 field remains cryptographically bound by the durable V1 event.
pub fn prepare_artifact_publication_v3(
    current_registry: &ArtifactRegistry,
    expected_registry_head: Digest32,
    withdrawal_registry: &DatasetWithdrawalRegistry,
    admission: &WithdrawalBoundArtifactAdmissionV3,
    event_id: StableId,
    now: u64,
) -> Result<PreparedArtifactPublicationV3, ArtifactPublicationError> {
    let observed_registry_head = current_registry.snapshot().head_digest;
    if observed_registry_head != expected_registry_head {
        return Err(ArtifactPublicationError::RegistryHeadChanged);
    }
    validate_artifact_publication_v3(admission, withdrawal_registry, now)?;

    let v2 = &admission.validated_manifest.manifest;
    if v2.predecessor_ids.len() > 1 {
        return Err(ArtifactPublicationError::UnsupportedMultiPredecessor);
    }
    let predecessor_id = v2.predecessor_ids.first().cloned();
    if v2.rollback_predecessor.is_some() && v2.rollback_predecessor != predecessor_id {
        return Err(ArtifactPublicationError::RollbackProjectionMismatch);
    }
    let support_digest = match v2.provenance_mode {
        ProvenanceModeV1::DatasetDerived => {
            let [dataset_digest] = v2.source_dataset_digests.as_slice() else {
                return Err(ArtifactPublicationError::UnsupportedMultiDataset);
            };
            *dataset_digest
        }
        ProvenanceModeV1::DatasetIndependent => admission.validated_manifest.manifest_digest,
    };

    let manifest = ArtifactManifest {
        artifact_id: v2.artifact_id.clone(),
        kind: v2.kind,
        generation: v2.generation,
        predecessor_id,
        content_digest: v2.bytes_digest,
        objective_digest: v2.objective_class_digest,
        support_digest,
        producer_id: v2.producer_id.clone(),
        compatibility_digest: v2.compatibility_digest,
        encoded_size_bytes: v2.encoded_size_bytes,
    };
    let mut registry = current_registry.clone();
    let append = registry.append(ArtifactEvent::Register { event_id, manifest })?;
    let resulting_registry_head_digest = registry.snapshot().head_digest;
    let withdrawal_binding_digest = admission.withdrawal_binding.binding_digest();
    let transaction_digest = digest_transaction(
        admission.admission_digest,
        withdrawal_binding_digest,
        admission.withdrawal_head_digest,
        expected_registry_head,
        append.event_digest,
        resulting_registry_head_digest,
    );
    Ok(PreparedArtifactPublicationV3 {
        registry,
        transaction: ArtifactPublicationTransactionV3 {
            admission_digest: admission.admission_digest,
            withdrawal_binding_digest,
            withdrawal_head_digest: admission.withdrawal_head_digest,
            expected_registry_head_digest: expected_registry_head,
            registry_event_digest: append.event_digest,
            resulting_registry_head_digest,
            transaction_digest,
        },
    })
}

/// Revalidate both mutable frontiers immediately before the host publishes the
/// staged create-only snapshot. The caller must hold the same writer fence used
/// to publish its current registry pointer/witness.
pub fn revalidate_artifact_publication_v3(
    prepared: &PreparedArtifactPublicationV3,
    current_registry: &ArtifactRegistry,
    withdrawal_registry: &DatasetWithdrawalRegistry,
    admission: &WithdrawalBoundArtifactAdmissionV3,
    now: u64,
) -> Result<(), ArtifactPublicationError> {
    if current_registry.snapshot().head_digest
        != prepared.transaction.expected_registry_head_digest
    {
        return Err(ArtifactPublicationError::RegistryHeadChanged);
    }
    validate_artifact_publication_v3(admission, withdrawal_registry, now)?;
    if admission.admission_digest != prepared.transaction.admission_digest
        || admission.withdrawal_binding.binding_digest()
            != prepared.transaction.withdrawal_binding_digest
        || admission.withdrawal_head_digest != prepared.transaction.withdrawal_head_digest
    {
        return Err(ArtifactPublicationError::SnapshotReceiptMismatch);
    }
    Ok(())
}

fn digest_transaction(
    admission_digest: Digest32,
    withdrawal_binding_digest: Digest32,
    withdrawal_head_digest: Digest32,
    expected_registry_head_digest: Digest32,
    registry_event_digest: Digest32,
    resulting_registry_head_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.publication-transaction.v3".to_vec();
    for digest in [
        admission_digest,
        withdrawal_binding_digest,
        withdrawal_head_digest,
        expected_registry_head_digest,
        registry_event_digest,
        resulting_registry_head_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use std::fs::{File, remove_file};
    use std::time::{SystemTime, UNIX_EPOCH};

    use codex_hepta_types::Generation;

    use super::*;
    use crate::{
        ArtifactKind, CreateOnlyArtifactFile, DatasetRevocationRequest,
        DatasetWithdrawalNoticeV1, LearningArtifactManifestV2, ProvenanceModeV1,
        WithdrawalRegistryBindingV1, admit_manifest_at_withdrawal_head_v3,
        prepare_dataset_revocation, read_registry_snapshot, write_registry_snapshot,
    };

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn withdrawal_registry(scope: &str) -> DatasetWithdrawalRegistry {
        DatasetWithdrawalRegistry::new_scoped(
            WithdrawalRegistryBindingV1::new(id("withdrawal-registry"), digest(scope))
                .expect("valid binding"),
        )
        .expect("valid scoped registry")
    }

    fn manifest(dataset: Digest32) -> LearningArtifactManifestV2 {
        LearningArtifactManifestV2 {
            artifact_id: id("artifact-v3-publication"),
            kind: ArtifactKind::Model,
            generation: Generation::new(1).expect("generation"),
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: vec![dataset],
            lineage_digests: vec![digest("lineage")],
            predecessor_ids: Vec::new(),
            rollback_predecessor: None,
            bytes_digest: digest("bytes"),
            encoded_size_bytes: 5,
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
        }
    }

    fn unique_path(label: &str) -> std::path::PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock after epoch")
            .as_nanos();
        std::env::temp_dir().join(format!(
            "hepta-learning-artifacts-{label}-{}-{nanos}",
            std::process::id()
        ))
    }

    #[test]
    fn art_07_publication_transaction_survives_snapshot_reopen() {
        let withdrawal = withdrawal_registry("scope-a");
        let admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawal,
            withdrawal.snapshot().head_digest,
            manifest(digest("dataset")),
            20,
        )
        .expect("admission");
        let current = ArtifactRegistry::new();
        let prepared = prepare_artifact_publication_v3(
            &current,
            Digest32::ZERO,
            &withdrawal,
            &admission,
            id("register-v3"),
            20,
        )
        .expect("prepare");

        let path = unique_path("publication-reopen");
        let receipt = write_registry_snapshot(
            CreateOnlyArtifactFile::create(&path).expect("create snapshot"),
            prepared.registry(),
            prepared.snapshot_binding(),
        )
        .expect("write snapshot");
        prepared
            .validate_snapshot_receipt(&receipt)
            .expect("receipt bound to transaction");

        let reopened = read_registry_snapshot(File::open(&path).expect("open snapshot"), receipt)
            .expect("reopen exact snapshot");
        assert_eq!(
            reopened.snapshot().head_digest,
            prepared.transaction().resulting_registry_head_digest
        );
        remove_file(path).expect("remove test file");
    }

    #[test]
    fn art_07_publication_preserves_single_dataset_revocation_binding() {
        let dataset = digest("dataset");
        let withdrawal = withdrawal_registry("scope-a");
        let admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawal,
            withdrawal.snapshot().head_digest,
            manifest(dataset),
            20,
        )
        .expect("admission");
        let current = ArtifactRegistry::new();
        let prepared = prepare_artifact_publication_v3(
            &current,
            Digest32::ZERO,
            &withdrawal,
            &admission,
            id("register-v3"),
            20,
        )
        .expect("prepare");

        assert_eq!(
            prepared
                .registry()
                .manifest(&id("artifact-v3-publication"))
                .expect("registered manifest")
                .support_digest,
            dataset
        );
        let revocation = prepare_dataset_revocation(
            prepared.registry(),
            prepared.registry().snapshot().head_digest,
            &DatasetRevocationRequest {
                operation_id: id("revoke-dataset"),
                dataset_digest: dataset,
                source_revocation_digest: digest("source-revocation"),
                evaluator_id: id("independent-evaluator"),
            },
        )
        .expect("legacy durable registry can still identify the direct dataset target");
        assert_eq!(
            revocation.summary().direct_artifacts,
            vec![id("artifact-v3-publication")]
        );
    }

    #[test]
    fn art_07_publication_rejects_lossy_multi_dataset_projection() {
        let withdrawal = withdrawal_registry("scope-a");
        let mut candidate = manifest(digest("dataset-a"));
        candidate.source_dataset_digests.push(digest("dataset-b"));
        let admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawal,
            withdrawal.snapshot().head_digest,
            candidate,
            20,
        )
        .expect("multi-dataset V2 admission is valid");
        let current = ArtifactRegistry::new();
        assert_eq!(
            prepare_artifact_publication_v3(
                &current,
                Digest32::ZERO,
                &withdrawal,
                &admission,
                id("register-v3"),
                20,
            )
            .unwrap_err(),
            ArtifactPublicationError::UnsupportedMultiDataset
        );
    }

    #[test]
    fn art_07_publication_revalidation_closes_withdrawal_race() {
        let dataset = digest("dataset");
        let mut withdrawal = withdrawal_registry("scope-a");
        let admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawal,
            withdrawal.snapshot().head_digest,
            manifest(dataset),
            20,
        )
        .expect("admission");
        let current = ArtifactRegistry::new();
        let prepared = prepare_artifact_publication_v3(
            &current,
            Digest32::ZERO,
            &withdrawal,
            &admission,
            id("register-v3"),
            20,
        )
        .expect("prepare");
        withdrawal
            .append(DatasetWithdrawalNoticeV1 {
                notice_id: id("withdrawal-after-prepare"),
                dataset_digest: dataset,
                source_tombstone_digest: digest("tombstone"),
                authority_id: id("authority"),
                credential_chain_digest: digest("credential"),
                signing_key_digest: digest("key"),
                authority_epoch: 1,
                issued_at: 21,
            })
            .expect("withdrawal append");
        assert_eq!(
            revalidate_artifact_publication_v3(
                &prepared,
                &current,
                &withdrawal,
                &admission,
                21,
            ),
            Err(ArtifactPublicationError::Admission(
                ArtifactAdmissionError::WithdrawalHeadChanged
            ))
        );
    }
}
