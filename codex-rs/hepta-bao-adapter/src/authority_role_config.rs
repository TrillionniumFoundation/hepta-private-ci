//! Frozen issuance scope and separately purposed private authority keys.

use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::FinalUseApprovalVerifier;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use serde::Serialize;

use crate::ConsumerPortError;
use crate::local_service::LocalServiceConfig;
use crate::private_files::read_private;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretsAuthorityServiceConfig {
    pub(crate) schema_version: u32,
    pub(crate) service: LocalServiceConfig,
    pub(crate) database_path: PathBuf,
    pub(crate) runtime_uid: u32,
    pub(crate) operator_uid: u32,
    pub(crate) issuer_id: String,
    pub(crate) issuer_signing_key_file: PathBuf,
    pub(crate) issuer_verifying_key: [u8; 32],
    pub(crate) time_issuer_id: String,
    pub(crate) time_key_epoch: u64,
    pub(crate) time_signing_key_file: PathBuf,
    pub(crate) time_verifying_key: [u8; 32],
    pub(crate) approver_id: String,
    pub(crate) approver_verifying_key: [u8; 32],
    pub(crate) distributor_id: String,
    pub(crate) distributor_verifying_key: [u8; 32],
    pub(crate) frozen_binding: FinalUseBinding,
    pub(crate) initial_revocations: FinalUseRevocations,
    pub(crate) grant_lifetime_ms: u64,
}

pub(crate) struct AuthorityKeys {
    pub issuer: SigningKey,
    pub time: SigningKey,
    pub approval: FinalUseApprovalVerifier,
    pub revocation: ed25519_dalek::VerifyingKey,
}

impl SecretsAuthorityServiceConfig {
    pub fn load_root_owned(path: &Path) -> Result<Self, ConsumerPortError> {
        crate::private_files::read_root_configuration(path)
    }

    pub(crate) fn keys_and_profile(&self) -> Result<(AuthorityKeys, [u8; 32]), ConsumerPortError> {
        StableId::new(&self.issuer_id).map_err(invalid)?;
        StableId::new(&self.time_issuer_id).map_err(invalid)?;
        StableId::new(&self.distributor_id).map_err(invalid)?;
        Generation::new(self.time_key_epoch).map_err(invalid)?;
        if self.schema_version != 1
            || self.runtime_uid == self.operator_uid
            || self.service.service_uid == self.runtime_uid
            || self.service.service_uid == self.operator_uid
            || self.service.service_uid != rustix::process::geteuid().as_raw()
            || self.service.allowed_peer_uids != [self.runtime_uid, self.operator_uid]
            || self.issuer_verifying_key == self.time_verifying_key
            || self.issuer_verifying_key == self.approver_verifying_key
            || self.time_verifying_key == self.approver_verifying_key
            || self.grant_lifetime_ms == 0
            || self.grant_lifetime_ms > 180_000
            || self.frozen_binding.destination_id != "provider:heptabao"
            || self.frozen_binding.request_sha256 == [0; 32]
            || self.frozen_binding.scope_sha256 == [0; 32]
            || self.frozen_binding.payload_sha256 == [0; 32]
        {
            return Err(ConsumerPortError::Invalid);
        }
        let pins = [
            self.issuer_verifying_key,
            self.time_verifying_key,
            self.approver_verifying_key,
            self.distributor_verifying_key,
        ];
        if pins
            .iter()
            .copied()
            .collect::<std::collections::BTreeSet<_>>()
            .len()
            != pins.len()
        {
            return Err(ConsumerPortError::Invalid);
        }
        FinalUseFrontier::for_initial_head(&self.initial_revocations).map_err(invalid)?;
        let revocation = ed25519_dalek::VerifyingKey::from_bytes(&self.distributor_verifying_key)
            .map_err(invalid)?;
        if revocation.is_weak() {
            return Err(ConsumerPortError::Invalid);
        }
        let issuer = load_key(&self.issuer_signing_key_file, &self.issuer_verifying_key)?;
        let time = load_key(&self.time_signing_key_file, &self.time_verifying_key)?;
        let approval =
            FinalUseApprovalVerifier::new(self.approver_id.clone(), self.approver_verifying_key)
                .map_err(invalid)?;
        // Revocation heads advance through the external CAS path; their
        // changing revision is not a reason to reset original grant history.
        let encoding = serde_json::to_vec(&(
            "hepta.secrets.authority-role.profile.v1",
            &self.issuer_id,
            self.issuer_verifying_key,
            &self.time_issuer_id,
            self.time_key_epoch,
            self.time_verifying_key,
            &self.approver_id,
            self.approver_verifying_key,
            &self.distributor_id,
            self.distributor_verifying_key,
            &self.frozen_binding,
            self.grant_lifetime_ms,
        ))
        .map_err(invalid)?;
        Ok((
            AuthorityKeys {
                issuer,
                time,
                approval,
                revocation,
            },
            Digest32::of_bytes(&encoding).into_array(),
        ))
    }
}

pub(crate) fn load_key(path: &Path, expected: &[u8; 32]) -> Result<SigningKey, ConsumerPortError> {
    let bytes = read_private(path, 32)?;
    let seed: &[u8; 32] = bytes.as_slice().try_into().map_err(invalid)?;
    let key = SigningKey::from_bytes(seed);
    if key.verifying_key().to_bytes() != *expected || key.verifying_key().is_weak() {
        return Err(ConsumerPortError::Invalid);
    }
    Ok(key)
}

fn invalid(_error: impl std::fmt::Display) -> ConsumerPortError {
    ConsumerPortError::Invalid
}
