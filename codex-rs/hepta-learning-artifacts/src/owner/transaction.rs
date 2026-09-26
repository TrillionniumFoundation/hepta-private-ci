use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::DatasetWithdrawalRegistry;
use crate::RegistrySnapshotReceipt;
use crate::DatasetWithdrawalSnapshotReceiptV1;

use super::capability_validation::LearningArtifactHostAccessPolicyV1;
use super::capability_validation::push_id;
use crate::LearningArtifactPublishRequestV1;

pub const LEARNING_ARTIFACT_HOST_SCHEMA_VERSION_V1: u32 = 1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningArtifactShutdownRequestV1 {
    pub shutdown_id: StableId,
    pub reason_digest: Digest32,
    pub requested_at: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningArtifactBackupRequestV1 {
    pub backup_id: StableId,
    pub destination_witness_digest: Digest32,
    pub requested_at: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningArtifactBackupManifestV1 {
    pub backup_id: StableId,
    pub schema_version: u32,
    pub storage_binding: Digest32,
    pub registry_receipt: RegistrySnapshotReceipt,
    pub withdrawal_receipt: DatasetWithdrawalSnapshotReceiptV1,
    pub access_policy_digest: Digest32,
    pub destination_witness_digest: Digest32,
    pub prepared_at: u64,
    pub manifest_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl LearningArtifactBackupManifestV1 {
    #[must_use]
    pub fn canonical_bytes_without_digest(&self) -> Vec<u8> {
        let mut bytes = b"hepta.learning-artifacts.backup-manifest.v1".to_vec();
        push_id(&mut bytes, &self.backup_id);
        bytes.extend_from_slice(&self.schema_version.to_be_bytes());
        bytes.extend_from_slice(self.storage_binding.as_array());
        encode_registry_receipt(&mut bytes, self.registry_receipt);
        encode_withdrawal_receipt(&mut bytes, self.withdrawal_receipt);
        bytes.extend_from_slice(self.access_policy_digest.as_array());
        bytes.extend_from_slice(self.destination_witness_digest.as_array());
        bytes.extend_from_slice(&self.prepared_at.to_be_bytes());
        bytes
    }

    #[must_use]
    pub fn verify_digest(&self) -> bool {
        !self.manifest_digest.is_zero()
            && Digest32::of_bytes(&self.canonical_bytes_without_digest()) == self.manifest_digest
            && self.authority == AuthorityPosture::DENY_ALL
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningArtifactHostSchemaMigrationRequestV1 {
    pub migration_id: StableId,
    pub from_version: u32,
    pub to_version: u32,
    pub migration_digest: Digest32,
    pub requested_at: u64,
}

pub trait LearningArtifactHostSchemaMigrationV1: Send + Sync {
    fn from_version(&self) -> u32;
    fn to_version(&self) -> u32;
    fn migration_digest(&self) -> Digest32;
    fn apply(
        &self,
        control_root: &std::path::Path,
    ) -> Result<(), crate::DirectoryDurabilityError>;
}

#[must_use]
pub fn digest_learning_artifact_publish_request_v1(
    request: &LearningArtifactPublishRequestV1,
) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.host-publish-request.v1".to_vec();
    push_id(&mut bytes, &request.operation_id);
    bytes.extend_from_slice(request.admission.admission_digest.as_array());
    bytes.extend_from_slice(request.admission.withdrawal_scope_digest.as_array());
    bytes.extend_from_slice(request.admission.withdrawal_head_digest.as_array());
    let payload_digest = Digest32::of_bytes(&request.payload);
    bytes.extend_from_slice(payload_digest.as_array());
    bytes.extend_from_slice(&(request.payload.len() as u64).to_be_bytes());
    bytes.extend_from_slice(request.signed_current_head.withdrawal_scope_digest.as_array());
    bytes.extend_from_slice(request.signed_current_head.binding.as_array());
    push_id(
        &mut bytes,
        &request.signed_current_head.witness.registry_id,
    );
    bytes.extend_from_slice(
        &request
            .signed_current_head
            .witness
            .generation
            .get()
            .to_be_bytes(),
    );
    bytes.extend_from_slice(
        request
            .signed_current_head
            .witness
            .head_digest
            .as_array(),
    );
    bytes.extend_from_slice(
        request
            .signed_current_head
            .witness
            .predecessor_head_digest
            .as_array(),
    );
    bytes.extend_from_slice(
        &request
            .signed_current_head
            .witness
            .authority_epoch
            .to_be_bytes(),
    );
    push_id(
        &mut bytes,
        &request.signed_current_head.witness.signer_id,
    );
    bytes.extend_from_slice(
        request
            .signed_current_head
            .witness
            .signing_key_digest
            .as_array(),
    );
    bytes.extend_from_slice(
        &request
            .signed_current_head
            .witness
            .issued_at
            .to_be_bytes(),
    );
    bytes.extend_from_slice(
        &request
            .signed_current_head
            .witness
            .expires_at
            .to_be_bytes(),
    );
    bytes.extend_from_slice(&request.signed_current_head.signature);
    bytes.extend_from_slice(request.expected_registry_predecessor_head.as_array());
    bytes.extend_from_slice(&request.now.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[must_use]
pub fn digest_learning_artifact_current_view_request_v1(now: u64) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.host-current-view-request.v1".to_vec();
    bytes.extend_from_slice(&now.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[must_use]
pub fn digest_learning_artifact_withdrawal_frontier_v1(
    registry: &DatasetWithdrawalRegistry,
) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.host-withdrawal-frontier.v1".to_vec();
    match registry.scope_digest() {
        Some(scope) => bytes.extend_from_slice(scope.as_array()),
        None => bytes.extend_from_slice(Digest32::ZERO.as_array()),
    }
    bytes.extend_from_slice(registry.head_digest().as_array());
    bytes.extend_from_slice(&(registry.snapshot().records().len() as u64).to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[must_use]
pub fn digest_learning_artifact_access_policy_v1(
    policy: &LearningArtifactHostAccessPolicyV1,
) -> Digest32 {
    policy.digest()
}

#[must_use]
pub fn digest_learning_artifact_shutdown_request_v1(
    request: &LearningArtifactShutdownRequestV1,
) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.host-shutdown-request.v1".to_vec();
    push_id(&mut bytes, &request.shutdown_id);
    bytes.extend_from_slice(request.reason_digest.as_array());
    bytes.extend_from_slice(&request.requested_at.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[must_use]
pub fn digest_learning_artifact_backup_request_v1(
    request: &LearningArtifactBackupRequestV1,
) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.host-backup-request.v1".to_vec();
    push_id(&mut bytes, &request.backup_id);
    bytes.extend_from_slice(request.destination_witness_digest.as_array());
    bytes.extend_from_slice(&request.requested_at.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[must_use]
pub fn digest_learning_artifact_schema_migration_request_v1(
    request: &LearningArtifactHostSchemaMigrationRequestV1,
) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.host-schema-migration-request.v1".to_vec();
    push_id(&mut bytes, &request.migration_id);
    bytes.extend_from_slice(&request.from_version.to_be_bytes());
    bytes.extend_from_slice(&request.to_version.to_be_bytes());
    bytes.extend_from_slice(request.migration_digest.as_array());
    bytes.extend_from_slice(&request.requested_at.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

pub(super) fn encode_registry_receipt(bytes: &mut Vec<u8>, receipt: RegistrySnapshotReceipt) {
    bytes.extend_from_slice(receipt.binding.as_array());
    bytes.extend_from_slice(receipt.head_digest.as_array());
    bytes.extend_from_slice(receipt.file_digest.as_array());
    bytes.extend_from_slice(&(receipt.records as u64).to_be_bytes());
    bytes.extend_from_slice(&(receipt.encoded_bytes as u64).to_be_bytes());
}

pub(super) fn encode_withdrawal_receipt(
    bytes: &mut Vec<u8>,
    receipt: DatasetWithdrawalSnapshotReceiptV1,
) {
    bytes.extend_from_slice(receipt.binding.as_array());
    bytes.extend_from_slice(receipt.scope_digest.as_array());
    bytes.extend_from_slice(receipt.head_digest.as_array());
    bytes.extend_from_slice(receipt.file_digest.as_array());
    bytes.extend_from_slice(&(receipt.records as u64).to_be_bytes());
    bytes.extend_from_slice(&(receipt.encoded_bytes as u64).to_be_bytes());
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shutdown_request_digest_binds_time_and_reason() {
        let request = LearningArtifactShutdownRequestV1 {
            shutdown_id: StableId::new("shutdown".to_owned()).expect("id"),
            reason_digest: Digest32::of_bytes(b"maintenance"),
            requested_at: 10,
        };
        let mut changed = request.clone();
        changed.requested_at += 1;
        assert_ne!(
            digest_learning_artifact_shutdown_request_v1(&request),
            digest_learning_artifact_shutdown_request_v1(&changed)
        );
    }
}
