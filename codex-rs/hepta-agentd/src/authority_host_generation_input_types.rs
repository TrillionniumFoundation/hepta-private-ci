//! Complete protected-host data for the existing generation factories. These
//! structs decode public records, never a verified selection, owner or token.

use std::path::PathBuf;

use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactOwnerTrustV1;
use codex_hepta_learning_artifacts::ArtifactSelectionTrustV1;
use codex_hepta_learning_artifacts::DatasetWithdrawalSnapshotReceiptV1;
use codex_hepta_learning_artifacts::RegistryHeadWitnessV1;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_learning_artifacts::SignedArtifactWriterLeaseV1;
use codex_hepta_learning_artifacts::SignedCurrentArtifactHeadV1;
use codex_hepta_learning_artifacts::TrustedArtifactSelectorV1;
use codex_hepta_learning_artifacts::TrustedArtifactSignerV1;
use codex_hepta_neuron::CellGenerationConfigV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;

use super::invalid;
use crate::AgentdError;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct GenerationDeploymentFile {
    pub(super) schema_version: u32,
    pub(super) purpose: String,
    pub(super) artifacts: ArtifactFile,
    pub(super) consumer: ConsumerFile,
    pub(super) selection: SelectionFile,
    pub(super) target: TargetFile,
    pub(super) operation: OperationFile,
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum OperationFile {
    Fresh { operation_id: String, signed: SignedFinalUseGrant },
    Recover { operation_id: String, intent_digest: [u8; 32] },
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ArtifactFile {
    pub(super) state_directory: PathBuf,
    pub(super) trust: OwnerTrustFile,
    pub(super) writer_lease: WriterLeaseFile,
    pub(super) required_current_head: CurrentHeadFile,
    pub(super) withdrawal_snapshot: WithdrawalSnapshotFile,
    pub(super) storage_binding: [u8; 32],
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OwnerTrustFile {
    registry_id: String,
    withdrawal_scope_digest: [u8; 32],
    minimum_registry_generation: u64,
    genesis_predecessor_head_digest: [u8; 32],
    minimum_authority_epoch: u64,
    writer_signers: Vec<SignerFile>,
    head_signers: Vec<SignerFile>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SignerFile {
    signer_id: String,
    verifying_key: [u8; 32],
    minimum_authority_epoch: u64,
    maximum_authority_epoch: u64,
    valid_from: u64,
    expires_at: u64,
    revoked_at: Option<u64>,
}

impl SignerFile {
    fn original(self) -> Result<TrustedArtifactSignerV1, AgentdError> {
        Ok(TrustedArtifactSignerV1 {
            signer_id: StableId::new(self.signer_id).map_err(invalid)?,
            verifying_key: self.verifying_key,
            minimum_authority_epoch: self.minimum_authority_epoch,
            maximum_authority_epoch: self.maximum_authority_epoch,
            valid_from: self.valid_from,
            expires_at: self.expires_at,
            revoked_at: self.revoked_at,
        })
    }
}

impl OwnerTrustFile {
    pub(super) fn original(self) -> Result<ArtifactOwnerTrustV1, AgentdError> {
        Ok(ArtifactOwnerTrustV1 {
            registry_id: StableId::new(self.registry_id).map_err(invalid)?,
            withdrawal_scope_digest: Digest32::from_array(self.withdrawal_scope_digest),
            minimum_registry_generation: Generation::new(self.minimum_registry_generation).map_err(invalid)?,
            genesis_predecessor_head_digest: Digest32::from_array(self.genesis_predecessor_head_digest),
            minimum_authority_epoch: self.minimum_authority_epoch,
            writer_signers: self.writer_signers.into_iter().map(SignerFile::original).collect::<Result<_, _>>()?,
            head_signers: self.head_signers.into_iter().map(SignerFile::original).collect::<Result<_, _>>()?,
        })
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct WriterLeaseFile {
    lease_id: String,
    producer_id: String,
    registry_id: String,
    withdrawal_scope_digest: [u8; 32],
    signer_id: String,
    signing_key_digest: [u8; 32],
    authority_epoch: u64,
    lease_generation: u64,
    issued_at: u64,
    expires_at: u64,
    signature: Vec<u8>,
}

impl WriterLeaseFile {
    pub(super) fn original(self) -> Result<SignedArtifactWriterLeaseV1, AgentdError> {
        Ok(SignedArtifactWriterLeaseV1 {
            lease_id: StableId::new(self.lease_id).map_err(invalid)?,
            producer_id: StableId::new(self.producer_id).map_err(invalid)?,
            registry_id: StableId::new(self.registry_id).map_err(invalid)?,
            withdrawal_scope_digest: Digest32::from_array(self.withdrawal_scope_digest),
            signer_id: StableId::new(self.signer_id).map_err(invalid)?,
            signing_key_digest: Digest32::from_array(self.signing_key_digest),
            authority_epoch: self.authority_epoch,
            lease_generation: self.lease_generation,
            issued_at: self.issued_at,
            expires_at: self.expires_at,
            signature: signature(self.signature)?,
        })
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WitnessFile {
    registry_id: String,
    generation: u64,
    head_digest: [u8; 32],
    predecessor_head_digest: [u8; 32],
    authority_epoch: u64,
    signer_id: String,
    signing_key_digest: [u8; 32],
    issued_at: u64,
    expires_at: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CurrentHeadFile {
    withdrawal_scope_digest: [u8; 32],
    binding: [u8; 32],
    witness: WitnessFile,
    signature: Vec<u8>,
}

impl CurrentHeadFile {
    pub(super) fn original(self) -> Result<SignedCurrentArtifactHeadV1, AgentdError> {
        let w = self.witness;
        Ok(SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: Digest32::from_array(self.withdrawal_scope_digest),
            binding: Digest32::from_array(self.binding),
            witness: RegistryHeadWitnessV1 {
                registry_id: StableId::new(w.registry_id).map_err(invalid)?,
                generation: Generation::new(w.generation).map_err(invalid)?,
                head_digest: Digest32::from_array(w.head_digest),
                predecessor_head_digest: Digest32::from_array(w.predecessor_head_digest),
                authority_epoch: w.authority_epoch,
                signer_id: StableId::new(w.signer_id).map_err(invalid)?,
                signing_key_digest: Digest32::from_array(w.signing_key_digest),
                issued_at: w.issued_at,
                expires_at: w.expires_at,
            },
            signature: signature(self.signature)?,
        })
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct WithdrawalSnapshotFile {
    binding: [u8; 32],
    scope_digest: [u8; 32],
    head_digest: [u8; 32],
    file_digest: [u8; 32],
    records: usize,
    encoded_bytes: usize,
}

impl WithdrawalSnapshotFile {
    pub(super) fn original(self) -> DatasetWithdrawalSnapshotReceiptV1 {
        DatasetWithdrawalSnapshotReceiptV1 {
            binding: Digest32::from_array(self.binding),
            scope_digest: Digest32::from_array(self.scope_digest),
            head_digest: Digest32::from_array(self.head_digest),
            file_digest: Digest32::from_array(self.file_digest),
            records: self.records,
            encoded_bytes: self.encoded_bytes,
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ConsumerFile {
    pub(super) state_directory: PathBuf,
    pub(super) owner_id: String,
    pub(super) trust_model: ConsumerTrustModel,
    pub(super) required_external_frontier: FinalUseFrontier,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum ConsumerTrustModel {
    SingleCurrentIssuer,
    CurrentIssuerKeyRing,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SelectionTrustFile {
    registry_id: String,
    withdrawal_scope_digest: [u8; 32],
    minimum_authority_epoch: u64,
    selectors: Vec<SelectorFile>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SelectorFile {
    selector_id: String,
    verifying_key: [u8; 32],
    minimum_authority_epoch: u64,
    maximum_authority_epoch: u64,
    valid_from: u64,
    expires_at: u64,
    revoked_at: Option<u64>,
}

impl SelectionTrustFile {
    pub(super) fn original(self) -> Result<ArtifactSelectionTrustV1, AgentdError> {
        let selectors = self.selectors.into_iter().map(|v| {
            Ok(TrustedArtifactSelectorV1 {
                selector_id: StableId::new(v.selector_id).map_err(invalid)?,
                verifying_key: v.verifying_key,
                minimum_authority_epoch: v.minimum_authority_epoch,
                maximum_authority_epoch: v.maximum_authority_epoch,
                valid_from: v.valid_from,
                expires_at: v.expires_at,
                revoked_at: v.revoked_at,
            })
        }).collect::<Result<Vec<_>, AgentdError>>()?;
        Ok(ArtifactSelectionTrustV1 {
            registry_id: StableId::new(self.registry_id).map_err(invalid)?,
            withdrawal_scope_digest: Digest32::from_array(self.withdrawal_scope_digest),
            minimum_authority_epoch: self.minimum_authority_epoch,
            selectors,
        })
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SelectionFile {
    pub(super) trust: SelectionTrustFile,
    pub(super) signed: SelectionRecordFile,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SelectionRecordFile {
    selection_id: String,
    artifact_id: String,
    registry_id: String,
    withdrawal_scope_digest: [u8; 32],
    registry_head_digest: [u8; 32],
    current_witness_digest: [u8; 32],
    current_trust_digest: [u8; 32],
    artifact_kind: String,
    artifact_generation: u64,
    predecessor_id: Option<String>,
    content_digest: [u8; 32],
    objective_digest: [u8; 32],
    support_digest: [u8; 32],
    compatibility_digest: [u8; 32],
    encoded_size_bytes: u64,
    selector_id: String,
    selector_credential_digest: [u8; 32],
    signing_key_digest: [u8; 32],
    authority_epoch: u64,
    issued_at: u64,
    expires_at: u64,
    signature: Vec<u8>,
}

impl SelectionRecordFile {
    pub(super) fn original(self) -> Result<SignedArtifactSelectionV1, AgentdError> {
        if self.artifact_kind != "model" {
            return Err(invalid("an original Model selection is required"));
        }
        Ok(SignedArtifactSelectionV1 {
            selection_id: StableId::new(self.selection_id).map_err(invalid)?,
            artifact_id: StableId::new(self.artifact_id).map_err(invalid)?,
            registry_id: StableId::new(self.registry_id).map_err(invalid)?,
            withdrawal_scope_digest: Digest32::from_array(self.withdrawal_scope_digest),
            registry_head_digest: Digest32::from_array(self.registry_head_digest),
            current_witness_digest: Digest32::from_array(self.current_witness_digest),
            current_trust_digest: Digest32::from_array(self.current_trust_digest),
            artifact_kind: ArtifactKind::Model,
            artifact_generation: Generation::new(self.artifact_generation).map_err(invalid)?,
            predecessor_id: self.predecessor_id.map(StableId::new).transpose().map_err(invalid)?,
            content_digest: Digest32::from_array(self.content_digest),
            objective_digest: Digest32::from_array(self.objective_digest),
            support_digest: Digest32::from_array(self.support_digest),
            compatibility_digest: Digest32::from_array(self.compatibility_digest),
            encoded_size_bytes: self.encoded_size_bytes,
            selector_id: StableId::new(self.selector_id).map_err(invalid)?,
            selector_credential_digest: Digest32::from_array(self.selector_credential_digest),
            signing_key_digest: Digest32::from_array(self.signing_key_digest),
            authority_epoch: self.authority_epoch,
            issued_at: self.issued_at,
            expires_at: self.expires_at,
            signature: signature(self.signature)?,
        })
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct TargetFile {
    pub(super) configuration: CellGenerationConfigV2,
    pub(super) maximum_records: u64,
    pub(super) maximum_witness_records: usize,
}

fn signature(bytes: Vec<u8>) -> Result<[u8; 64], AgentdError> {
    bytes.try_into().map_err(|_: Vec<u8>| invalid("original signature must contain 64 bytes"))
}
