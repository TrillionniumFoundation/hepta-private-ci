//! Public trust and withdrawal inputs for the original read-only CURRENT owner.
//! These DTOs alone grant nothing: the protected frontier must match every cut.
use super::*;
use codex_hepta_agent_components::learning_artifacts::ArtifactOwnerTrustV1;
use codex_hepta_agent_components::learning_artifacts::DatasetWithdrawalSnapshotReceiptV1;
use codex_hepta_agent_components::learning_artifacts::TrustedArtifactSignerV1;
use codex_hepta_agent_components::learning_artifacts::read_dataset_withdrawal_snapshot;

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CurrentArtifactOwnerDescriptorV1 {
    owner_root: PathBuf,
    registry_id: String,
    withdrawal_scope_digest: String,
    minimum_registry_generation: u64,
    genesis_predecessor_head_digest: String,
    minimum_authority_epoch: u64,
    writer_signers: Vec<ArtifactSignerDescriptorV1>,
    head_signers: Vec<ArtifactSignerDescriptorV1>,
    withdrawals: WithdrawalSnapshotDescriptorV1,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ArtifactSignerDescriptorV1 {
    signer_id: String,
    verifying_key_hex: String,
    minimum_authority_epoch: u64,
    maximum_authority_epoch: u64,
    valid_from: u64,
    expires_at: u64,
    revoked_at: Option<u64>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct WithdrawalSnapshotDescriptorV1 {
    path: PathBuf,
    binding: String,
    scope_digest: String,
    head_digest: String,
    file_digest: String,
    records: usize,
    encoded_bytes: usize,
}

impl CurrentArtifactOwnerDescriptorV1 {
    pub(super) fn source(&self) -> Result<crate::CurrentArtifactRegistrySourceV1, AgentdError> {
        if !self.owner_root.is_absolute() {
            return invalid("artifact CURRENT owner root must be absolute");
        }
        require_absolute_regular_file(&self.withdrawals.path, "CURRENT withdrawal snapshot")?;
        let receipt = DatasetWithdrawalSnapshotReceiptV1 {
            binding: digest(&self.withdrawals.binding, "withdrawal snapshot binding")?,
            scope_digest: digest(&self.withdrawals.scope_digest, "withdrawal scope")?,
            head_digest: digest(&self.withdrawals.head_digest, "withdrawal head")?,
            file_digest: digest(&self.withdrawals.file_digest, "withdrawal file")?,
            records: self.withdrawals.records,
            encoded_bytes: self.withdrawals.encoded_bytes,
        };
        let withdrawals =
            read_dataset_withdrawal_snapshot(File::open(&self.withdrawals.path)?, receipt)
                .map_err(|error| {
                    AgentdError::Invalid(format!("invalid CURRENT withdrawal cut: {error}"))
                })?;
        let trust = ArtifactOwnerTrustV1 {
            registry_id: stable_id(&self.registry_id, "artifact CURRENT registry")?,
            withdrawal_scope_digest: digest(
                &self.withdrawal_scope_digest,
                "CURRENT withdrawal scope",
            )?,
            minimum_registry_generation: Generation::new(self.minimum_registry_generation)
                .map_err(|_| AgentdError::Invalid("CURRENT generation".to_string()))?,
            genesis_predecessor_head_digest: Digest32::from_str(
                &self.genesis_predecessor_head_digest,
            )
            .map_err(|_| AgentdError::Invalid("CURRENT genesis predecessor digest".to_string()))?,
            minimum_authority_epoch: self.minimum_authority_epoch,
            writer_signers: self
                .writer_signers
                .iter()
                .map(ArtifactSignerDescriptorV1::signer)
                .collect::<Result<_, _>>()?,
            head_signers: self
                .head_signers
                .iter()
                .map(ArtifactSignerDescriptorV1::signer)
                .collect::<Result<_, _>>()?,
        };
        crate::CurrentArtifactRegistrySourceV1::open(self.owner_root.clone(), trust, withdrawals)
            .map_err(|error| AgentdError::Invalid(format!("artifact CURRENT unavailable: {error}")))
    }
}

impl ArtifactSignerDescriptorV1 {
    fn signer(&self) -> Result<TrustedArtifactSignerV1, AgentdError> {
        Ok(TrustedArtifactSignerV1 {
            signer_id: stable_id(&self.signer_id, "artifact CURRENT signer")?,
            verifying_key: parse_hex_32(&self.verifying_key_hex, "artifact CURRENT public key")?,
            minimum_authority_epoch: self.minimum_authority_epoch,
            maximum_authority_epoch: self.maximum_authority_epoch,
            valid_from: self.valid_from,
            expires_at: self.expires_at,
            revoked_at: self.revoked_at,
        })
    }
}
