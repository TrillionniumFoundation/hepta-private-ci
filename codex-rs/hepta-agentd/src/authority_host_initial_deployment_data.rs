//! Root-owned initial deployment data. It locates actual original inputs;
//! it cannot certify genesis, create a nonce owner or replace Initial authority.

use super::shared_data::*;
use crate::RootGenerationInitialModeV1;
use crate::RootPublicationFinalUseConsumerV1;
use serde::Deserialize;
use serde::Serialize;
use std::path::PathBuf;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct InitialDeploymentData {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub learning_trust: Option<PathBuf>,
    pub schema_version: u32,
    pub mode: RootGenerationInitialModeV1,
    pub operation: String,
    pub current_directory: PathBuf,
    pub target_journal: PathBuf,
    pub target_witness: PathBuf,
    pub target: ObserverData,
    pub artifact_root: PathBuf,
    pub owner_trust: OwnerTrustData,
    pub retained_current: CurrentData,
    pub storage_binding: [u8; 32],
    pub withdrawal_file: PathBuf,
    pub withdrawal: WithdrawalData,
    pub selector_trust: SelectorTrustData,
    pub selection: SelectionData,
    pub consumer: RootPublicationFinalUseConsumerV1,
    pub consumer_state_root: PathBuf,
    pub issuer_keys: Vec<IssuerKeyData>,
    pub trigger: PathBuf,
}

impl crate::OriginalRootInitialLaunchDataV1 {
    /// Public configuration preimages only. Calling this decoder does not open
    /// a Root store, enroll a consumer, acquire a grant, or construct CURRENT.
    pub(crate) fn from_original_deployment_value(
        value: serde_json::Value,
    ) -> std::io::Result<Self> {
        let data: InitialDeploymentData =
            serde_json::from_value(value).map_err(std::io::Error::other)?;
        if data.schema_version != 1 {
            return Err(std::io::Error::other(
                "original Initial deployment schema required",
            ));
        }
        let trust = data.owner_trust.original_owner_trust()?;
        let selector = data.selector_trust.original_selector(&trust)?;
        Ok(Self {
            mode: data.mode,
            operation: data.operation,
            target_journal: data.target_journal,
            target_witness: data.target_witness,
            target: data.target.original_observer_config()?,
            artifact_root: data.artifact_root,
            trust,
            retained_current: data.retained_current.original_current()?,
            storage_binding: codex_hepta_types::Digest32::from_array(data.storage_binding),
            withdrawal_file: data.withdrawal_file,
            withdrawal_receipt:
                codex_hepta_learning_artifacts::DatasetWithdrawalSnapshotReceiptV1 {
                    binding: codex_hepta_types::Digest32::from_array(data.withdrawal.binding),
                    scope_digest: codex_hepta_types::Digest32::from_array(data.withdrawal.scope),
                    head_digest: codex_hepta_types::Digest32::from_array(data.withdrawal.head),
                    file_digest: codex_hepta_types::Digest32::from_array(
                        data.withdrawal.file_digest,
                    ),
                    records: data.withdrawal.records,
                    encoded_bytes: data.withdrawal.encoded_bytes,
                },
            selector,
            selection: data.selection.original_selection()?,
        })
    }
}
