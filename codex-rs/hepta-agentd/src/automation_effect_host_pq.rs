//! PQ-only composition for the ordinary HTTP and PoN effect loader.
//! The external services attest to their own state; independent deployment and
//! whole-machine recovery remain qualifications outside this composition.

use super::*;
#[cfg(all(test, target_os = "linux"))]
use std::collections::BTreeSet;

use crate::pq_final_use::PqDispatchLease;
use crate::pq_final_use::PqFinalUseConfig as AuthorityConfig;
use crate::pq_final_use::PqFinalUseGate;
use codex_hepta_contracts::FinalUseAuthenticationProfile;
use codex_hepta_contracts::PqAuthorityTrustKey;
#[cfg(all(test, target_os = "linux"))]
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use serde::Serialize;

const SCHEMA_VERSION: u32 = 4;
const MAX_CONFIG_BYTES: u64 = 256 * 1024;

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct EffectHostConfig {
    schema_version: u32,
    authentication_profile: FinalUseAuthenticationProfile,
    provider_scope: String,
    destination_id: String,
    final_use_scope_sha256: String,
    provider: ProviderConfig,
    contract_id: String,
    contract_sha256: String,
    contract_authority_epoch: u64,
    contract_signature: Vec<u8>,
    contract_key: PqAuthorityTrustKey,
    final_use: AuthorityConfig,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "provider_kind", deny_unknown_fields)]
enum ProviderConfig {
    #[serde(rename = "http-v1")]
    Http {
        dispatch_url: String,
        lookup_url_template: String,
        #[serde(default)]
        headers: BTreeMap<String, String>,
        timeout_ms: u64,
    },
    #[serde(rename = "trillionnium-pon-local-v1")]
    Pon {
        chain_binary: PathBuf,
        chain_binary_sha256: String,
        chain_store: PathBuf,
        chain_state_backend: String,
        chain_genesis_time: u64,
        chain_evaluation_policy: String,
        chain_task_profile: String,
        chain_model_profile: String,
        chain_workers: u64,
        chain_min_confirmation_depth: u64,
        chain_min_confirmation_work_depth_hex: String,
        timeout_ms: u64,
    },
}

pub(super) struct PqEffectAuthority(PqFinalUseGate);

/// Production drivers must carry the authenticated PQ lease. Classical test
/// fixtures have an explicit variant that is absent from production builds.
#[derive(Clone)]
pub(super) enum EffectDispatchLease {
    Pq(PqDispatchLease),
    #[cfg(test)]
    ClassicalFixture,
}

impl EffectDispatchLease {
    pub(super) fn check(&self) -> Result<(), AuthorizedEffectDriverError> {
        match self {
            Self::Pq(lease) => lease
                .check()
                .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact),
            #[cfg(test)]
            Self::ClassicalFixture => Ok(()),
        }
    }
}

impl PqEffectAuthority {
    pub(super) fn authenticate(
        &self,
        authority: &FinalUseAuthority,
        path: &Path,
        grant: &SignedFinalUseGrant,
    ) -> Result<PqDispatchLease, AgentdError> {
        self.0.authenticate(authority, path, grant).map_err(invalid)
    }
}

pub(super) fn open(
    identity: &AgentdIdentity,
    path: &Path,
) -> Result<AgentdAutomationEffectHost, AgentdError> {
    let bytes = read_protected_file(path, MAX_CONFIG_BYTES, "PQ automation effect host file")?;
    let value: Value = serde_json::from_slice(&bytes)?;
    // Reject legacy selection before keys, trust requests, owner creation or
    // provider preparation. No optional/default classical branch exists here.
    if value.get("schema_version").and_then(Value::as_u64) != Some(u64::from(SCHEMA_VERSION))
        || value.get("authentication_profile").and_then(Value::as_str) != Some("ml_dsa65_v2")
    {
        return Err(invalid(
            "ordinary automation effects require schema 4 and explicit ml_dsa65_v2",
        ));
    }
    let config: EffectHostConfig = serde_json::from_value(value)?;
    if config.schema_version != SCHEMA_VERSION
        || config.authentication_profile != FinalUseAuthenticationProfile::MlDsa65V2
        || config.contract_authority_epoch != config.final_use.head.authority_epoch
        || config.contract_authority_epoch < config.contract_key.not_before_authority_epoch
        || config.contract_authority_epoch > config.contract_key.not_after_authority_epoch
    {
        return Err(invalid(
            "PQ effect contract profile or authority epoch is invalid",
        ));
    }
    validate_host_identifier("provider_scope", &config.provider_scope)?;
    validate_host_identifier("destination_id", &config.destination_id)?;
    let scope = Sha256Digest::parse(config.final_use_scope_sha256.clone()).map_err(invalid)?;
    let declared = Sha256Digest::parse(config.contract_sha256.clone()).map_err(invalid)?;
    let authority_root = identity
        .layout
        .automation_root()
        .join("final-use-authority");
    let attestation = HttpProviderEffectContractAttestation::verify_pq_signed(
        config.contract_id.clone(),
        declared.clone(),
        config.contract_authority_epoch,
        &config.contract_signature,
        &config.contract_key.public_key_spki,
        config.contract_key.public_key_id,
    )
    .map_err(invalid)?;
    if !attestation.is_pq_verified() {
        return Err(invalid("PQ provider contract attestation required"));
    }
    let adapter = prepare_provider(&config, attestation, &declared)?;
    let revocations_file = config.final_use.signed_revocations_file.clone();
    let (authority, gate) = config
        .final_use
        .open(&authority_root, &[&config.contract_key])
        .map_err(invalid)?;
    Ok(AgentdAutomationEffectHost {
        agent_id: identity.agent_id.clone(),
        provider_scope: config.provider_scope,
        destination_id: config.destination_id,
        final_use_scope_digest: scope,
        authority,
        revocations_file,
        revocation_refresh: Arc::new(Mutex::new(())),
        pq: Some(Arc::new(PqEffectAuthority(gate))),
        adapter,
    })
}

fn prepare_provider(
    config: &EffectHostConfig,
    attestation: HttpProviderEffectContractAttestation,
    declared: &Sha256Digest,
) -> Result<AgentdProviderEffectAdapter, AgentdError> {
    match &config.provider {
        ProviderConfig::Http {
            dispatch_url,
            lookup_url_template,
            headers,
            timeout_ms,
        } => {
            if headers.len() > MAX_PROVIDER_HEADERS || !(1..=30_000).contains(timeout_ms) {
                return Err(invalid("PQ HTTP provider limits are invalid"));
            }
            let mut parsed_headers = HeaderMap::new();
            for (name, value) in headers {
                parsed_headers.append(
                    HeaderName::from_bytes(name.as_bytes()).map_err(invalid)?,
                    HeaderValue::from_bytes(value.as_bytes()).map_err(invalid)?,
                );
            }
            let provider = HttpProviderEffectConfig {
                dispatch_url: dispatch_url.clone(),
                lookup_url_template: lookup_url_template.clone(),
                headers: parsed_headers,
                timeout: Duration::from_millis(*timeout_ms),
                contract_id: config.contract_id.clone(),
                attestation: Some(attestation),
            };
            if provider.contract_sha256().map_err(invalid)? != *declared {
                return Err(invalid("PQ HTTP provider contract digest mismatch"));
            }
            Ok(AgentdProviderEffectAdapter::Http(
                HttpProviderEffectAdapter::new(provider).map_err(invalid)?,
            ))
        }
        ProviderConfig::Pon {
            chain_binary,
            chain_binary_sha256,
            chain_store,
            chain_state_backend,
            chain_genesis_time,
            chain_evaluation_policy,
            chain_task_profile,
            chain_model_profile,
            chain_workers,
            chain_min_confirmation_depth,
            chain_min_confirmation_work_depth_hex,
            timeout_ms,
        } => {
            for value in [
                chain_evaluation_policy,
                chain_task_profile,
                chain_model_profile,
            ] {
                validate_host_identifier("PoN profile", value)?;
            }
            if !matches!(
                chain_state_backend.as_str(),
                "legacy-v2" | "authenticated-v1"
            ) || *chain_genesis_time == 0
                || !(1..=64).contains(chain_workers)
                || !(1..=4096).contains(chain_min_confirmation_depth)
                || !lower_hex_64(chain_min_confirmation_work_depth_hex)
                || chain_min_confirmation_work_depth_hex
                    .bytes()
                    .all(|byte| byte == b'0')
                || !(1..=30_000).contains(timeout_ms)
            {
                return Err(invalid("PQ PoN provider limits are invalid"));
            }
            let mut contract = b"hepta.agentd.pon-provider-contract.pq.v3\0".to_vec();
            contract.extend(serde_json::to_vec(&serde_json::json!({
                "provider_scope": config.provider_scope, "destination_id": config.destination_id,
                "final_use_scope_sha256": config.final_use_scope_sha256, "provider": config.provider,
            }))?);
            if Sha256Digest::for_bytes(&contract) != *declared {
                return Err(invalid("PQ PoN provider contract digest mismatch"));
            }
            let binary_sha256 =
                Sha256Digest::parse(chain_binary_sha256.clone()).map_err(invalid)?;
            verify_pinned_binary(chain_binary, &binary_sha256)?;
            if !chain_store.is_absolute()
                || chain_store.canonicalize()? != *chain_store
                || !chain_store.join("native.sqlite").is_file()
            {
                return Err(invalid(
                    "PoN store must be an existing canonical Node namespace",
                ));
            }
            Ok(AgentdProviderEffectAdapter::Pon(
                PonLocalProviderEffectAdapter {
                    binary: chain_binary.clone(),
                    binary_sha256,
                    store: chain_store.clone(),
                    state_backend: chain_state_backend.clone(),
                    genesis_time: *chain_genesis_time,
                    evaluation_policy: chain_evaluation_policy.clone(),
                    task_profile: chain_task_profile.clone(),
                    model_profile: chain_model_profile.clone(),
                    workers: *chain_workers,
                    min_confirmation_depth: *chain_min_confirmation_depth,
                    min_confirmation_work_depth_hex: chain_min_confirmation_work_depth_hex.clone(),
                    timeout: Duration::from_millis(*timeout_ms),
                },
            ))
        }
    }
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(format!("PQ automation effect authority: {error}"))
}

#[cfg(all(test, target_os = "linux"))]
#[path = "automation_effect_host_pq_tests.rs"]
mod tests;
