//! PNP2 growth provider composition. This is a separate signed provider profile;
//! maintenance work never supplies an external task or useful-output claim.

use super::AgentdAutomationEffectHost;
use super::AgentdError;
use super::AgentdIdentity;
use super::AgentdProviderEffectAdapter;
use super::FinalUseAuthority;
use super::HttpProviderEffectContractAttestation;
use super::PonLocalProfile;
use super::PonLocalProviderEffectAdapter;
use super::PonObservationProfile;
use super::Sha256Digest;
use super::decode_hex_array;
use super::lower_hex_32;
use super::lower_hex_64;
use super::parse_pon_observation_fields;
use super::read_revocations_file;
use super::validate_host_identifier;
use super::verify_pinned_binary;
use serde::Deserialize;
use serde_json::Value;
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

pub(super) const SCHEMA_VERSION: u32 = 4;
const PROVIDER_KIND: &str = "trillionnium-pon-growth-local-v1";
pub(super) const OBSERVATION_SCHEMA: &str = "pon-native-exact-growth-packet-observation-v1";
pub(super) const MEMBERSHIP_SQL_BUDGET: u64 = 8193;
const PACKET_PROFILE: &str = "PNP2";
const STATE_PROFILE: &str = "permanent-account-growth-native-v2";

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct HostFileV4 {
    schema_version: u32,
    provider_kind: String,
    provider_scope: String,
    destination_id: String,
    final_use_scope_sha256: String,
    chain_binary: PathBuf,
    chain_binary_sha256: String,
    chain_store: PathBuf,
    chain_growth_namespace: String,
    chain_network_sha256: String,
    chain_parameters_sha256: String,
    chain_genesis_sha256: String,
    chain_genesis_time: u64,
    chain_min_confirmation_depth: u64,
    chain_min_confirmation_work_depth_hex: String,
    timeout_ms: u64,
    contract_id: String,
    contract_sha256: String,
    contract_authority_epoch: u64,
    contract_signature_hex: String,
    contract_verifying_key_hex: String,
    final_use_signer_id: String,
    final_use_verifying_key_hex: String,
    final_use_revocations_file: PathBuf,
}

#[derive(Clone, Debug)]
pub(super) struct Context {
    pub(super) namespace: String,
    pub(super) network: String,
    pub(super) parameters: String,
    pub(super) genesis: String,
}

impl Context {
    pub(super) fn parse_observation(
        &self,
        value: &Value,
        min_depth: u64,
        min_work: &str,
    ) -> Option<crate::AutomationEffectChainObservation> {
        let result = value.get("result")?;
        if result.get("packet_profile")?.as_str()? != PACKET_PROFILE
            || result.get("state_profile")?.as_str()? != STATE_PROFILE
            || result.get("network")?.as_str()? != self.network
            || result.get("parameters")?.as_str()? != self.parameters
            || result.get("genesis")?.as_str()? != self.genesis
        {
            return None;
        }
        // Share field invariants, never relabel a legacy response as growth.
        let observation = parse_pon_observation_fields(
            value,
            PonObservationProfile::Growth,
            min_depth,
            min_work,
        )?;
        if observation.owner_generation == 0 {
            // The read-only owner does not recover/activate after an admission
            // crash. Genesis may retain exact inactive bytes, or local absence;
            // neither shape can establish task acceptance or confirmation.
            if observation.active_tip != self.genesis
                || observation.active_tip_height != 0
                || observation
                    .active_tip_chainwork_hex
                    .bytes()
                    .any(|byte| byte != b'0')
                || observation.active_chain_member
                || observation.active_depth.is_some()
                || observation.active_work_depth_hex.is_some()
                || observation.accepted_task.is_some()
                || (observation.stored_exact
                    && (observation.block_height.is_none_or(|height| height <= 0)
                        || !observation
                            .block_chainwork_hex
                            .as_deref()
                            .is_some_and(|work| work.bytes().any(|byte| byte != b'0'))
                        || observation.active_membership_sql_lookups != Some(1)))
            {
                return None;
            }
        }
        Some(observation)
    }
}

fn contract_digest(config: &HostFileV4) -> Result<Sha256Digest, AgentdError> {
    let value = serde_json::json!({
        "schema":"hepta-agentd-pon-growth-provider-contract-v1",
        "provider_kind":config.provider_kind,
        "provider_scope":config.provider_scope,
        "destination_id":config.destination_id,
        "final_use_scope_sha256":config.final_use_scope_sha256,
        "chain_binary":config.chain_binary,
        "chain_binary_sha256":config.chain_binary_sha256,
        "chain_store":config.chain_store,
        "chain_growth_namespace":config.chain_growth_namespace,
        "chain_network_sha256":config.chain_network_sha256,
        "chain_parameters_sha256":config.chain_parameters_sha256,
        "chain_genesis_sha256":config.chain_genesis_sha256,
        "chain_genesis_time":config.chain_genesis_time,
        "packet_profile":PACKET_PROFILE,
        "state_profile":STATE_PROFILE,
        "observation_schema":OBSERVATION_SCHEMA,
        "active_membership_sql_budget":MEMBERSHIP_SQL_BUDGET,
        "chain_min_confirmation_depth":config.chain_min_confirmation_depth,
        "chain_min_confirmation_work_depth_hex":config.chain_min_confirmation_work_depth_hex,
        "timeout_ms":config.timeout_ms,
    });
    let mut bytes = b"hepta.agentd.pon-growth-provider-contract.v1\0".to_vec();
    bytes.extend_from_slice(&serde_json::to_vec(&value)?);
    Ok(Sha256Digest::for_bytes(&bytes))
}

pub(super) fn open(
    identity: &AgentdIdentity,
    config: HostFileV4,
) -> Result<AgentdAutomationEffectHost, AgentdError> {
    if config.schema_version != SCHEMA_VERSION || config.provider_kind != PROVIDER_KIND {
        return Err(AgentdError::Invalid(
            "unsupported PoN growth automation effect host schema".to_string(),
        ));
    }
    validate_host_identifier("provider_scope", &config.provider_scope)?;
    validate_host_identifier("destination_id", &config.destination_id)?;
    validate_host_identifier("chain_growth_namespace", &config.chain_growth_namespace)?;
    if config.chain_genesis_time == 0
        || !lower_hex_32(&config.chain_network_sha256)
        || !lower_hex_32(&config.chain_parameters_sha256)
        || !lower_hex_32(&config.chain_genesis_sha256)
        || !(1..=4096).contains(&config.chain_min_confirmation_depth)
        || !lower_hex_64(&config.chain_min_confirmation_work_depth_hex)
        || config
            .chain_min_confirmation_work_depth_hex
            .bytes()
            .all(|byte| byte == b'0')
        || !(1..=30_000).contains(&config.timeout_ms)
    {
        return Err(AgentdError::Invalid(
            "PoN growth context or limits are invalid".to_string(),
        ));
    }
    let final_use_scope_digest =
        Sha256Digest::parse(config.final_use_scope_sha256.clone()).map_err(AgentdError::Invalid)?;
    let binary_digest =
        Sha256Digest::parse(config.chain_binary_sha256.clone()).map_err(AgentdError::Invalid)?;
    verify_pinned_binary(&config.chain_binary, &binary_digest)?;
    let adapter = PonLocalProviderEffectAdapter {
        binary: config.chain_binary.clone(),
        binary_sha256: binary_digest,
        store: config.chain_store.clone(),
        genesis_time: config.chain_genesis_time,
        profile: PonLocalProfile::Growth(Context {
            namespace: config.chain_growth_namespace.clone(),
            network: config.chain_network_sha256.clone(),
            parameters: config.chain_parameters_sha256.clone(),
            genesis: config.chain_genesis_sha256.clone(),
        }),
        min_confirmation_depth: config.chain_min_confirmation_depth,
        min_confirmation_work_depth_hex: config.chain_min_confirmation_work_depth_hex.clone(),
        timeout: Duration::from_millis(config.timeout_ms),
    };
    if !config.chain_store.is_absolute() || adapter.validate_paths().is_err() {
        return Err(AgentdError::Invalid(
            "PoN store must be an existing canonical Node namespace".to_string(),
        ));
    }
    let declared =
        Sha256Digest::parse(config.contract_sha256.clone()).map_err(AgentdError::Invalid)?;
    if contract_digest(&config)? != declared {
        return Err(AgentdError::Invalid(
            "PoN growth provider contract digest mismatch".to_string(),
        ));
    }
    let signature =
        decode_hex_array::<64>(&config.contract_signature_hex, "contract_signature_hex")?;
    let key = decode_hex_array::<32>(
        &config.contract_verifying_key_hex,
        "contract_verifying_key_hex",
    )?;
    HttpProviderEffectContractAttestation::verify_signed(
        config.contract_id,
        declared,
        config.contract_authority_epoch,
        &signature,
        &key,
    )
    .map_err(AgentdError::Invalid)?;
    let revocations = read_revocations_file(&config.final_use_revocations_file)?;
    let final_use_key = decode_hex_array::<32>(
        &config.final_use_verifying_key_hex,
        "final_use_verifying_key_hex",
    )?;
    let authority_root = identity
        .layout
        .automation_root()
        .join("final-use-authority");
    fs::create_dir_all(&authority_root)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&authority_root, fs::Permissions::from_mode(0o700))?;
    }
    let authority = FinalUseAuthority::open_state_dir(
        &authority_root,
        config.final_use_signer_id,
        final_use_key,
        revocations,
    )
    .map_err(|error| {
        AgentdError::Protocol(format!(
            "open automation final-use authority state: {error}"
        ))
    })?;
    Ok(AgentdAutomationEffectHost {
        agent_id: identity.agent_id.clone(),
        provider_scope: config.provider_scope,
        destination_id: config.destination_id,
        final_use_scope_digest,
        authority,
        revocations_file: config.final_use_revocations_file,
        revocation_refresh: Arc::new(Mutex::new(())),
        adapter: AgentdProviderEffectAdapter::Pon(adapter),
    })
}

#[cfg(test)]
#[path = "automation_effect_host_pon_growth_tests.rs"]
mod tests;
