//! PQ-only composition for the ordinary HTTP and PoN effect loader.
//! The external services attest to their own state; independent deployment and
//! whole-machine recovery remain qualifications outside this composition.

use super::*;
use std::collections::BTreeSet;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseAuthenticationProfile;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::PqAuthorityTrustKey;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_contracts::authority_trust_unix::UnixPqAuthorityClock;
use codex_hepta_contracts::authority_trust_unix::UnixPqFinalUseFrontier;
use codex_hepta_contracts::authority_trust_unix::UnixPqTrustEndpointConfig;
use codex_hepta_contracts::pq_auth::PqNativeVerifier;
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

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct AuthorityConfig {
    signer_id: String,
    issuer_keys: Vec<PqAuthorityTrustKey>,
    head: FinalUseRevocations,
    revocation_distributor_id: String,
    revocation_keys: Vec<PqAuthorityTrustKey>,
    signed_revocations_file: PathBuf,
    external_clock: UnixPqTrustEndpointConfig,
    external_frontier: UnixPqTrustEndpointConfig,
}

pub(super) struct PqEffectAuthority {
    clock: Arc<dyn AuthorityClock>,
    feed: FinalUseRevocationFeedVerifier,
    contract_epoch: u64,
}

/// Only an authenticated feed creates this lease. Its exact head is checked
/// inside the original final-use effect fence, after every preceding await.
#[derive(Clone)]
pub(super) struct PqDispatchLease {
    authority: FinalUseAuthority,
    clock: Arc<dyn AuthorityClock>,
    head: FinalUseRevocations,
    valid_until_unix_ms: u64,
}

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
            Self::Pq(lease) => lease.check(),
            #[cfg(test)]
            Self::ClassicalFixture => Ok(()),
        }
    }
}

impl PqDispatchLease {
    pub(super) fn check(&self) -> Result<(), AuthorizedEffectDriverError> {
        if self.authority.authentication_profile() != FinalUseAuthenticationProfile::MlDsa65V2
            || self.authority.revocation_head().ok().as_ref() != Some(&self.head)
            || !self
                .clock
                .now_unix_ms()
                .is_ok_and(|now| now < self.valid_until_unix_ms)
        {
            return Err(AuthorizedEffectDriverError::BeforeProviderContact);
        }
        Ok(())
    }
}

impl PqEffectAuthority {
    pub(super) fn authenticate(
        &self,
        authority: &FinalUseAuthority,
        path: &Path,
        grant: &SignedFinalUseGrant,
    ) -> Result<PqDispatchLease, AgentdError> {
        let bytes = read_protected_file(
            path,
            MAX_AUTOMATION_EFFECT_REVOCATIONS_FILE_BYTES,
            "PQ automation signed revocations",
        )?;
        let signed: SignedFinalUseRevocationUpdate = serde_json::from_slice(&bytes)?;
        let now = self.clock.now_unix_ms().map_err(invalid)?;
        let receipt = self
            .feed
            .apply_or_confirm_current(authority, &signed, now)
            .map_err(invalid)?;
        if grant.grant.schema_version != 2
            || grant.grant.authority_epoch != receipt.authority_epoch()
            || receipt.authority_epoch() != self.contract_epoch
            || grant.grant.expires_at_unix_ms > receipt.valid_until_unix_ms()
        {
            return Err(invalid(
                "PQ effect grant, contract and authenticated feed disagree",
            ));
        }
        Ok(PqDispatchLease {
            authority: authority.clone(),
            clock: Arc::clone(&self.clock),
            head: signed.update.head,
            valid_until_unix_ms: grant.grant.expires_at_unix_ms,
        })
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
    validate_roles_and_paths(&config, &authority_root)?;
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
    let clock =
        Arc::new(UnixPqAuthorityClock::new(config.final_use.external_clock).map_err(invalid)?);
    let frontier =
        Arc::new(UnixPqFinalUseFrontier::new(config.final_use.external_frontier).map_err(invalid)?);
    let feed = FinalUseRevocationFeedVerifier::new_pq_with_keys(
        config.final_use.revocation_distributor_id,
        config.final_use.revocation_keys,
    )
    .map_err(invalid)?;
    // Existing external registration is mandatory. An absent witness never
    // bootstraps itself from this rollbackable local configuration.
    clock.now_unix_ms().map_err(invalid)?;
    frontier
        .load(&config.final_use.signer_id)
        .map_err(invalid)?;
    let authority = FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
        &authority_root,
        config.final_use.signer_id,
        config.final_use.issuer_keys,
        config.final_use.head,
        clock.clone(),
        frontier,
    )
    .map_err(invalid)?;
    Ok(AgentdAutomationEffectHost {
        agent_id: identity.agent_id.clone(),
        provider_scope: config.provider_scope,
        destination_id: config.destination_id,
        final_use_scope_digest: scope,
        authority,
        revocations_file: config.final_use.signed_revocations_file,
        revocation_refresh: Arc::new(Mutex::new(())),
        pq: Some(Arc::new(PqEffectAuthority {
            clock,
            feed,
            contract_epoch: config.contract_authority_epoch,
        })),
        adapter,
    })
}

fn validate_roles_and_paths(config: &EffectHostConfig, owner: &Path) -> Result<(), AgentdError> {
    if !(1..=8).contains(&config.final_use.issuer_keys.len())
        || !(1..=8).contains(&config.final_use.revocation_keys.len())
    {
        return Err(invalid(
            "PQ effect requires one to eight keys per authority ring",
        ));
    }
    let mut keys = BTreeSet::new();
    for (spki, pin) in config
        .final_use
        .issuer_keys
        .iter()
        .chain(&config.final_use.revocation_keys)
        .chain(std::iter::once(&config.contract_key))
        .map(|key| (key.public_key_spki.as_slice(), key.public_key_id))
        .chain([
            (
                config.final_use.external_clock.public_key_spki.as_slice(),
                config.final_use.external_clock.public_key_id,
            ),
            (
                config
                    .final_use
                    .external_frontier
                    .public_key_spki
                    .as_slice(),
                config.final_use.external_frontier.public_key_id,
            ),
        ])
    {
        let key = PqNativeVerifier::from_pinned_spki(spki, pin).map_err(invalid)?;
        if !keys.insert(*key.public_spki()) {
            return Err(invalid(
                "PQ effect authority roles must have distinct public keys",
            ));
        }
    }
    let parent = owner
        .parent()
        .ok_or_else(|| invalid("authority parent missing"))?
        .canonicalize()?;
    if parent.join("final-use-authority").as_os_str() != owner.as_os_str() {
        return Err(invalid("PQ effect authority directory contains an alias"));
    }
    match fs::symlink_metadata(owner) {
        Ok(metadata)
            if metadata.is_dir() && owner.canonicalize()?.as_os_str() == owner.as_os_str() => {}
        Ok(_) => return Err(invalid("PQ effect authority directory contains an alias")),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(error.into()),
    }
    let clock = &config.final_use.external_clock.socket_path;
    let frontier = &config.final_use.external_frontier.socket_path;
    for path in [clock, frontier] {
        if !path.is_absolute()
            || path.canonicalize()?.as_os_str() != path.as_os_str()
            || path.starts_with(owner)
        {
            return Err(invalid(
                "PQ effect requires canonical external trust services",
            ));
        }
    }
    if clock == frontier {
        return Err(invalid(
            "PQ effect clock and frontier must be distinct services",
        ));
    }
    if !config.final_use.signed_revocations_file.is_absolute() {
        return Err(invalid("PQ signed revocation file must be absolute"));
    }
    Ok(())
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
