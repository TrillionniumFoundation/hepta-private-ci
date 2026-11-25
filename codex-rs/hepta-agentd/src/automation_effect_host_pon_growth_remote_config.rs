//! V5 explicitly binds a live protected growth owner. V4 remains local-only.

use super::super::AgentdAutomationEffectHost;
use super::super::AgentdError;
use super::super::AgentdIdentity;
use super::super::AgentdProviderEffectAdapter;
use super::super::PonLocalProfile;
use super::super::PonLocalProviderEffectAdapter;
use super::super::decode_hex_array;
use super::super::lower_hex_32;
use super::super::lower_hex_64;
use super::super::pon_growth;
use super::super::pon_process;
use super::super::read_revocations_file;
use super::super::validate_host_identifier;
use super::super::verify_pinned_binary;
use super::TRANSPORT_PROFILE;
use super::Transport;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::Sha256Digest;
use codex_model_provider::HttpProviderEffectContractAttestation;
use serde::Deserialize;
use std::fs;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

pub(in super::super) const SCHEMA_VERSION: u32 = 5;
const PROVIDER_KIND: &str = "trillionnium-pon-growth-remote-v1";

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(in super::super) struct HostFileV5 {
    schema_version: u32,
    provider_kind: String,
    provider_scope: String,
    destination_id: String,
    final_use_scope_sha256: String,
    chain_binary: PathBuf,
    chain_binary_sha256: String,
    chain_transport_profile: String,
    chain_peer: String,
    chain_server_public_key_hex: String,
    chain_resource_profile_sha256: String,
    chain_client_secret_file: PathBuf,
    chain_client_secret_sha256: String,
    chain_client_public_key_hex: String,
    chain_admission_bits: u8,
    chain_admission_ttl_ms: u64,
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

fn contract_digest(config: &HostFileV5) -> Result<Sha256Digest, AgentdError> {
    let value = serde_json::json!({
        "schema":"hepta-agentd-pon-growth-remote-provider-contract-v1",
        "provider_kind":config.provider_kind,
        "provider_scope":config.provider_scope,
        "destination_id":config.destination_id,
        "final_use_scope_sha256":config.final_use_scope_sha256,
        "chain_binary":config.chain_binary,
        "chain_binary_sha256":config.chain_binary_sha256,
        "chain_transport_profile":config.chain_transport_profile,
        "chain_peer":config.chain_peer,
        "chain_server_public_key_hex":config.chain_server_public_key_hex,
        "chain_resource_profile_sha256":config.chain_resource_profile_sha256,
        "chain_client_secret_file":config.chain_client_secret_file,
        "chain_client_secret_sha256":config.chain_client_secret_sha256,
        "chain_client_public_key_hex":config.chain_client_public_key_hex,
        "chain_admission_bits":config.chain_admission_bits,
        "chain_admission_ttl_ms":config.chain_admission_ttl_ms,
        "chain_growth_namespace":config.chain_growth_namespace,
        "chain_network_sha256":config.chain_network_sha256,
        "chain_parameters_sha256":config.chain_parameters_sha256,
        "chain_genesis_sha256":config.chain_genesis_sha256,
        "chain_genesis_time":config.chain_genesis_time,
        "packet_profile":"PNP2",
        "state_profile":"permanent-account-growth-native-v2",
        "observation_schema":pon_growth::OBSERVATION_SCHEMA,
        "active_membership_sql_budget":pon_growth::MEMBERSHIP_SQL_BUDGET,
        "chain_min_confirmation_depth":config.chain_min_confirmation_depth,
        "chain_min_confirmation_work_depth_hex":config.chain_min_confirmation_work_depth_hex,
        "timeout_ms":config.timeout_ms,
        "final_use_signer_id":config.final_use_signer_id,
        "final_use_verifying_key_hex":config.final_use_verifying_key_hex,
        "final_use_revocations_file":config.final_use_revocations_file,
    });
    let mut bytes = b"hepta.agentd.pon-growth-remote-provider-contract.v1\0".to_vec();
    bytes.extend_from_slice(&serde_json::to_vec(&value)?);
    Ok(Sha256Digest::for_bytes(&bytes))
}

pub(in super::super) fn open(
    identity: &AgentdIdentity,
    config: HostFileV5,
) -> Result<AgentdAutomationEffectHost, AgentdError> {
    if config.schema_version != SCHEMA_VERSION
        || config.provider_kind != PROVIDER_KIND
        || config.chain_transport_profile != TRANSPORT_PROFILE
    {
        return Err(AgentdError::Invalid(
            "unsupported PoN growth transport schema".into(),
        ));
    }
    validate_host_identifier("provider_scope", &config.provider_scope)?;
    validate_host_identifier("destination_id", &config.destination_id)?;
    validate_host_identifier("chain_growth_namespace", &config.chain_growth_namespace)?;
    let peer: SocketAddr = config
        .chain_peer
        .parse()
        .map_err(|_| AgentdError::Invalid("PoN peer must be a numeric IP:port".into()))?;
    if peer.port() == 0
        || peer.to_string() != config.chain_peer
        || config.chain_genesis_time == 0
        || !lower_hex_32(&config.chain_server_public_key_hex)
        || !lower_hex_32(&config.chain_resource_profile_sha256)
        || !lower_hex_32(&config.chain_client_public_key_hex)
        || !lower_hex_32(&config.chain_network_sha256)
        || !lower_hex_32(&config.chain_parameters_sha256)
        || !lower_hex_32(&config.chain_genesis_sha256)
        || !(8..=20).contains(&config.chain_admission_bits)
        || !(100..=2000).contains(&config.chain_admission_ttl_ms)
        || !(1..=4096).contains(&config.chain_min_confirmation_depth)
        || !lower_hex_64(&config.chain_min_confirmation_work_depth_hex)
        || config
            .chain_min_confirmation_work_depth_hex
            .bytes()
            .all(|byte| byte == b'0')
        || !(1..=30_000).contains(&config.timeout_ms)
    {
        return Err(AgentdError::Invalid(
            "PoN live context or limits are invalid".into(),
        ));
    }
    let declared =
        Sha256Digest::parse(config.contract_sha256.clone()).map_err(AgentdError::Invalid)?;
    if contract_digest(&config)? != declared {
        return Err(AgentdError::Invalid(
            "PoN live provider contract digest mismatch".into(),
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
    let final_use_scope_digest =
        Sha256Digest::parse(config.final_use_scope_sha256).map_err(AgentdError::Invalid)?;
    let binary_digest =
        Sha256Digest::parse(config.chain_binary_sha256).map_err(AgentdError::Invalid)?;
    verify_pinned_binary(&config.chain_binary, &binary_digest)?;
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
    let snapshot_root = identity
        .layout
        .automation_root()
        .join("pon-transport-credentials");
    let directory = fs::DirBuilder::new();
    #[cfg(unix)]
    let directory = {
        use std::os::unix::fs::DirBuilderExt;
        let mut directory = directory;
        directory.mode(0o700);
        directory
    };
    if let Err(error) = directory.create(&snapshot_root)
        && error.kind() != std::io::ErrorKind::AlreadyExists
    {
        return Err(error.into());
    }
    let credential = pon_process::CredentialPin {
        source: config.chain_client_secret_file,
        sha256: Sha256Digest::parse(config.chain_client_secret_sha256)
            .map_err(AgentdError::Invalid)?,
        public_key: decode_hex_array::<32>(
            &config.chain_client_public_key_hex,
            "chain_client_public_key_hex",
        )?,
        snapshot_root,
    };
    // Check the real source FD and derived identity at open, then again for
    // every operation. This temporary check is removed before any child starts.
    drop(
        credential
            .prepare(Instant::now() + Duration::from_millis(config.timeout_ms))
            .map_err(|_| AgentdError::Invalid("PoN live credential pin unavailable".into()))?,
    );
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
    let adapter = PonLocalProviderEffectAdapter {
        binary: config.chain_binary,
        binary_sha256: binary_digest,
        // Shared historical adapter type; the remote variant never opens or
        // supplies a local store. V5 has no chain_store configuration field.
        store: PathBuf::new(),
        genesis_time: config.chain_genesis_time,
        profile: PonLocalProfile::GrowthRemote(Transport {
            context: pon_growth::Context {
                namespace: config.chain_growth_namespace,
                network: config.chain_network_sha256,
                parameters: config.chain_parameters_sha256,
                genesis: config.chain_genesis_sha256,
            },
            peer,
            server_public: config.chain_server_public_key_hex,
            resource_profile: config.chain_resource_profile_sha256,
            admission_bits: config.chain_admission_bits,
            admission_ttl_ms: config.chain_admission_ttl_ms,
            credential,
        }),
        min_confirmation_depth: config.chain_min_confirmation_depth,
        min_confirmation_work_depth_hex: config.chain_min_confirmation_work_depth_hex,
        timeout: Duration::from_millis(config.timeout_ms),
    };
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
#[path = "automation_effect_host_pon_growth_remote_config_tests.rs"]
mod tests;
