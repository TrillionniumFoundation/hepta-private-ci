//! Root-owned initial deployment data. It locates actual original inputs;
//! it cannot certify genesis, create a nonce owner or replace Initial authority.

use std::path::PathBuf;
use serde::Deserialize;
use serde::Serialize;
use super::shared_data::*;
use crate::RootGenerationInitialModeV1;
use crate::RootPublicationFinalUseConsumerV1;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct InitialDeploymentData {
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
