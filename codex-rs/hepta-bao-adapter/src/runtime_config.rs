//! Root alone fixes provider, consumer, governed scope and Agent kernel peers.
use crate::BaoClient;
use crate::BaoReadRequest;
use crate::BaoToken;
use crate::ConsumerEvidenceConfig;
use crate::ConsumerPortClient;
use crate::ConsumerPortError;
use crate::SecretsAuthorityClient;
use crate::SecretsRoleClientConfig;
use crate::local_service::LocalServiceConfig;
use crate::private_files::read_private;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeMap;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretsRuntimeServiceConfig {
    pub(crate) schema_version: u32,
    pub(crate) service: LocalServiceConfig,
    pub(crate) agents: BTreeMap<u32, String>,
    pub(crate) roles: SecretsRoleClientConfig,
    pub(crate) evidence: ConsumerEvidenceConfig,
    pub(crate) revocation_distributor_id: String,
    pub(crate) revocation_verifying_key: [u8; 32],
    pub(crate) provider_endpoint: String,
    pub(crate) provider_token_file: PathBuf,
    pub(crate) provider_ca_file: PathBuf,
    pub(crate) provider_timeout_ms: u64,
    pub(crate) request: BaoReadRequest,
    pub(crate) owner_database: PathBuf,
    pub(crate) authbus_database: PathBuf,
    pub(crate) authbus_checkpoint: PathBuf,
    pub(crate) final_use_state: PathBuf,
    pub(crate) authbus_owner_id: String,
    pub(crate) policy_id: String,
    pub(crate) policy_not_before_ms: u64,
    pub(crate) policy_expires_at_ms: u64,
    pub(crate) quota_period_id: String,
    pub(crate) quota_limit: u64,
    pub(crate) maximum_clock_age_ms: u64,
}
impl SecretsRuntimeServiceConfig {
    pub fn load_root_owned(path: &Path) -> Result<Self, ConsumerPortError> {
        crate::private_files::read_root_configuration(path)
    }
    pub(crate) fn components(
        &self,
    ) -> Result<(BaoClient, ConsumerPortClient, SecretsAuthorityClient), ConsumerPortError> {
        let uid = rustix::process::geteuid().as_raw();
        let peers: Vec<u32> = self.agents.keys().copied().collect();
        if self.schema_version != 1
            || self.service.service_uid != uid
            || self.roles.runtime_uid != uid
            || self.evidence.runtime_uid != uid
            || peers != self.service.allowed_peer_uids
            || peers.is_empty()
            || peers.len() > 8
            || peers.contains(&uid)
            || peers.contains(&self.roles.authority.connection.peer_uid)
            || peers.contains(&self.roles.operator.peer_uid)
            || peers.contains(&self.evidence.consumer.service_uid)
            || self
                .agents
                .values()
                .collect::<std::collections::BTreeSet<_>>()
                .len()
                != self.agents.len()
            || self.service.request_timeout_ms == 0
            || self.service.request_timeout_ms > 30_000
            || self.service.shutdown_drain_ms < self.service.request_timeout_ms
            || self.service.shutdown_drain_ms > 60_000
            || self.provider_timeout_ms == 0
            || self.provider_timeout_ms > 5_000
            || self.maximum_clock_age_ms == 0
            || self.maximum_clock_age_ms > self.service.request_timeout_ms
            || self.policy_not_before_ms >= self.policy_expires_at_ms
            || self.quota_limit == 0
            || self.evidence.cost > self.quota_limit
            || serde_json::to_vec(&self.roles.authority).map_err(|_| ConsumerPortError::Invalid)?
                != serde_json::to_vec(&self.evidence.authority)
                    .map_err(|_| ConsumerPortError::Invalid)?
        {
            return Err(ConsumerPortError::Invalid);
        }
        for agent in self.agents.values() {
            crate::authority_role_owner::original_id(agent)?;
            if agent.len() > 64 {
                return Err(ConsumerPortError::Invalid);
            }
        }
        for path in [
            &self.owner_database,
            &self.authbus_database,
            &self.authbus_checkpoint,
            &self.final_use_state,
        ] {
            if !path.is_absolute() {
                return Err(ConsumerPortError::Invalid);
            }
        }
        if self.authbus_checkpoint.parent() == self.authbus_database.parent()
            || self.owner_database == self.authbus_database
            || self.authbus_database == self.authbus_checkpoint
            || self.owner_database == self.authbus_checkpoint
        {
            return Err(ConsumerPortError::Invalid);
        }
        let token = read_private(&self.provider_token_file, 8192)?;
        let token = BaoToken::new(
            std::str::from_utf8(&token)
                .map_err(|_| ConsumerPortError::Invalid)?
                .to_owned(),
        )
        .map_err(|_| ConsumerPortError::Invalid)?;
        let ca = read_private(&self.provider_ca_file, 128 * 1024)?;
        let client = BaoClient::new(
            &self.provider_endpoint,
            &ca,
            token,
            Duration::from_millis(self.provider_timeout_ms),
        )
        .map_err(|_| ConsumerPortError::Invalid)?;
        let consumer = ConsumerPortClient::new_receipt_bound(self.evidence.consumer.clone())?;
        if self.request.consumer_id != self.evidence.consumer.consumer_id
            || self.request.expected_secret_sha256
                != self.evidence.consumer.credential_reference_sha256
            || self.request.consumer_configuration_sha256 != Some(consumer.configuration_sha256())
            || client
                .binding(&self.request)
                .map_err(|_| ConsumerPortError::Invalid)?
                != self.roles.frozen_binding
        {
            return Err(ConsumerPortError::Invalid);
        }
        let authority = SecretsAuthorityClient::new(self.roles.clone())?;
        Ok((client, consumer, authority))
    }
    pub(crate) fn operation_id(
        &self,
        peer_uid: u32,
        original: &str,
    ) -> Result<String, ConsumerPortError> {
        let agent = self
            .agents
            .get(&peer_uid)
            .ok_or(ConsumerPortError::Rejected)?;
        runtime_original_id(agent, original)
    }
}

pub(crate) fn runtime_original_id(
    agent: &str,
    original: &str,
) -> Result<String, ConsumerPortError> {
    crate::authority_role_owner::original_id(agent)?;
    crate::authority_role_owner::original_id(original)?;
    if agent.len() > 64 {
        return Err(ConsumerPortError::Invalid);
    }
    Ok(format!(
        "secrets.read:{agent}:{}",
        codex_hepta_types::Digest32::of_bytes(original.as_bytes())
    ))
}
