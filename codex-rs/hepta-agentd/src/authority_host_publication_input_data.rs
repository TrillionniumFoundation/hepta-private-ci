//! Original publication locations and trust data shared by explicit loaders.
//! This value supplies no capability; enrollment reopens the actual owners.

use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;

use super::data::CurrentData;
use super::data::DeploymentData;
use super::data::IssuerKeyData;
use super::data::Mode;
use super::data::ObserverData;
use super::data::OwnerTrustData;
use super::data::SelectorTrustData;
use super::data::WithdrawalData;
use crate::RootPublicationFinalUseConsumerV1;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PublicationInputData {
    pub mode: Mode,
    pub current_directory: PathBuf,
    pub previous_journal: PathBuf,
    pub previous_witness: PathBuf,
    pub previous: ObserverData,
    pub target_journal: PathBuf,
    pub target_witness: PathBuf,
    pub artifact_root: PathBuf,
    pub owner_trust: OwnerTrustData,
    pub retained_current: CurrentData,
    pub storage_binding: [u8; 32],
    pub withdrawal_file: PathBuf,
    pub withdrawal: WithdrawalData,
    pub selector_trust: SelectorTrustData,
    pub consumer: RootPublicationFinalUseConsumerV1,
    pub consumer_state_root: PathBuf,
    pub issuer_keys: Vec<IssuerKeyData>,
}

impl DeploymentData {
    pub(super) fn original_input_data(&self) -> PublicationInputData {
        PublicationInputData {
            mode: self.mode,
            current_directory: self.current_directory.clone(),
            previous_journal: self.previous_journal.clone(),
            previous_witness: self.previous_witness.clone(),
            previous: self.previous.clone(),
            target_journal: self.target_journal.clone(),
            target_witness: self.target_witness.clone(),
            artifact_root: self.artifact_root.clone(),
            owner_trust: self.owner_trust.clone(),
            retained_current: self.retained_current.clone(),
            storage_binding: self.storage_binding,
            withdrawal_file: self.withdrawal_file.clone(),
            withdrawal: self.withdrawal.clone(),
            selector_trust: self.selector_trust.clone(),
            consumer: self.consumer,
            consumer_state_root: self.consumer_state_root.clone(),
            issuer_keys: self.issuer_keys.clone(),
        }
    }
}
