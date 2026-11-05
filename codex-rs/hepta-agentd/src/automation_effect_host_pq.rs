//! Ordinary effect composition. Public keys and signed feeds come from the
//! operator; this host creates neither a root nor an external frontier.
use super::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseAuthenticationProfile;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseRevocationReceipt;
use codex_hepta_contracts::PqAuthorityTrustKey;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_contracts::authority_trust_unix::UnixPqAuthorityClock;
use codex_hepta_contracts::authority_trust_unix::UnixPqFinalUseFrontier;
use codex_hepta_contracts::authority_trust_unix::UnixPqTrustEndpointConfig;
use codex_hepta_contracts::pq_auth::PqNativeVerifier;
use serde::Serialize;
use std::collections::BTreeSet;

#[path = "automation_effect_host_pq_policy.rs"]
mod policy;
use policy::authenticate_recovery_policies;

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct HostV4 {
    schema_version: u32,
    authentication_profile: FinalUseAuthenticationProfile,
    agent_id: String,
    spawn_generation: u64,
    provider_scope: String,
    destination_id: String,
    final_use_scope_sha256: String,
    contract_id: String,
    contract_authority_epoch: u64,
    contract_root: PqAuthorityTrustKey,
    contract_signature: Vec<u8>,
    provider: ProviderV4,
    authority: AuthorityV4,
    #[serde(default)]
    recovery_provider_policies: Vec<RecoveryPolicyRef>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RecoveryPolicyRef {
    path: PathBuf,
    sha256: Sha256Digest,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct AuthorityV4 {
    signer_id: String,
    issuer_keys: Vec<PqAuthorityTrustKey>,
    head: FinalUseRevocations,
    revocation_distributor_id: String,
    revocation_keys: Vec<PqAuthorityTrustKey>,
    signed_revocations_file: PathBuf,
    external_clock: UnixPqTrustEndpointConfig,
    external_frontier: UnixPqTrustEndpointConfig,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum ProviderV4 {
    Http {
        dispatch_url: String,
        lookup_url_template: String,
        headers: BTreeMap<String, String>,
        timeout_ms: u64,
    },
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

pub(super) struct PqEffectRuntime {
    clock: Arc<dyn AuthorityClock>,
    frontier: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
    signer_id: String,
    feed: FinalUseRevocationFeedVerifier,
    contract_epoch: u64,
    recovery_scopes: Vec<Sha256Digest>,
    refresh: Mutex<()>,
}

fn invalid(message: impl ToString) -> AgentdError {
    AgentdError::Invalid(format!("PQ automation effect: {}", message.to_string()))
}

fn endpoint_policy(value: &UnixPqTrustEndpointConfig) -> Value {
    serde_json::json!({
        "socket_path":value.socket_path,"peer_uid":value.peer_uid,
        "service_id":value.service_id,"key_generation":value.key_generation,
        "public_key_id":value.public_key_id,"public_key_spki":value.public_key_spki,
        "timeout_ms":value.timeout_ms,
    })
}

pub(super) fn open(
    identity: &AgentdIdentity,
    bytes: &[u8],
) -> Result<AgentdAutomationEffectHost, AgentdError> {
    let config: HostV4 = serde_json::from_slice(bytes)?;
    let scope = config.validate(identity)?;
    let adapter = match &config.provider {
        ProviderV4::Http {
            dispatch_url,
            lookup_url_template,
            headers,
            timeout_ms,
        } => {
            if headers.len() > MAX_PROVIDER_HEADERS || !(1..=30_000).contains(timeout_ms) {
                return Err(invalid("original HTTP header and timeout limits required"));
            }
            let mut values = HeaderMap::new();
            for (name, value) in headers {
                values.append(
                    HeaderName::from_bytes(name.as_bytes()).map_err(invalid)?,
                    HeaderValue::from_str(value).map_err(invalid)?,
                );
            }
            let mut http = HttpProviderEffectConfig {
                dispatch_url: dispatch_url.clone(),
                lookup_url_template: lookup_url_template.clone(),
                headers: values,
                timeout: Duration::from_millis(*timeout_ms),
                contract_id: config.contract_id.clone(),
                attestation: None,
            };
            let digest = http.contract_sha256().map_err(invalid)?;
            http.attestation = Some(attestation(&config, &digest, &scope)?);
            AgentdProviderEffectAdapter::Http(
                HttpProviderEffectAdapter::new(http).map_err(invalid)?,
            )
        }
        ProviderV4::Pon {
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
            for (label, value) in [
                ("evaluation policy", chain_evaluation_policy),
                ("task profile", chain_task_profile),
                ("model profile", chain_model_profile),
            ] {
                validate_host_identifier(label, value)?;
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
                    .all(|b| b == b'0')
                || !(1..=30_000).contains(timeout_ms)
            {
                return Err(invalid("original PoN limits required"));
            }
            let binary_digest =
                Sha256Digest::parse(chain_binary_sha256.clone()).map_err(invalid)?;
            verify_pinned_binary(chain_binary, &binary_digest)?;
            let pon = PonLocalProviderEffectAdapter {
                binary: chain_binary.clone(),
                binary_sha256: binary_digest,
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
            };
            pon.validate_paths()
                .map_err(|()| invalid("canonical existing PoN store required"))?;
            let mut raw = b"hepta.agentd.pon-provider-contract.pq.v3\0".to_vec();
            raw.extend(serde_json::to_vec(&config.provider)?);
            let digest = Sha256Digest::for_bytes(&raw);
            attestation(&config, &digest, &scope)?;
            AgentdProviderEffectAdapter::Pon(pon)
        }
    };
    let recovery_scopes = authenticate_recovery_policies(&config)?;
    let a = config.authority;
    let clock: Arc<dyn AuthorityClock> =
        Arc::new(UnixPqAuthorityClock::new(a.external_clock).map_err(invalid)?);
    let frontier = Arc::new(UnixPqFinalUseFrontier::new(a.external_frontier).map_err(invalid)?);
    let feed = FinalUseRevocationFeedVerifier::new_pq_with_keys(
        a.revocation_distributor_id,
        a.revocation_keys,
    )
    .map_err(invalid)?;
    // Authenticate the initial head before any local authority file exists.
    // No feed receipt is fabricated: only the original owner may apply it.
    let now = clock.now_unix_ms().map_err(invalid)?;
    let raw = read_protected_file(
        &a.signed_revocations_file,
        256 * 1024,
        "signed PQ effect revocations",
    )?;
    let signed: SignedFinalUseRevocationUpdate = serde_json::from_slice(&raw)?;
    let authenticated = feed
        .authenticate_fresh_head(&signed, now)
        .map_err(invalid)?;
    if authenticated != a.head {
        return Err(invalid(
            "initial authority head must equal the authenticated signed feed",
        ));
    }
    frontier.load(&a.signer_id).map_err(invalid)?;
    let root = identity
        .layout
        .automation_root()
        .join("final-use-authority-pq-v2");
    let authority = FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
        &root,
        a.signer_id.clone(),
        a.issuer_keys,
        authenticated,
        clock.clone(),
        frontier.clone(),
    )
    .map_err(invalid)?;
    let runtime = Arc::new(PqEffectRuntime {
        clock,
        frontier,
        signer_id: a.signer_id,
        feed,
        contract_epoch: config.contract_authority_epoch,
        recovery_scopes,
        refresh: Mutex::new(()),
    });
    runtime.refresh(&authority, &a.signed_revocations_file)?;
    Ok(AgentdAutomationEffectHost {
        agent_id: identity.agent_id.clone(),
        provider_scope: config.provider_scope,
        destination_id: config.destination_id,
        final_use_scope_digest: scope,
        authority,
        revocations_file: a.signed_revocations_file,
        #[cfg(test)]
        revocation_refresh: Arc::new(Mutex::new(())),
        adapter,
        pq: Some(runtime),
    })
}

fn attestation(
    config: &HostV4,
    digest: &Sha256Digest,
    scope: &Sha256Digest,
) -> Result<HttpProviderEffectContractAttestation, AgentdError> {
    let proof = HttpProviderEffectContractAttestation::verify_pq_signed(
        &config.contract_id,
        digest.clone(),
        config.contract_authority_epoch,
        scope,
        &config.contract_signature,
        &config.contract_root,
    )
    .map_err(invalid)?;
    if proof.authentication_profile() != FinalUseAuthenticationProfile::MlDsa65V2 {
        return Err(invalid("classical contract cannot enter PQ host"));
    }
    Ok(proof)
}

impl PqEffectRuntime {
    pub(super) fn refresh(
        &self,
        authority: &FinalUseAuthority,
        path: &Path,
    ) -> Result<FinalUseRevocationReceipt, AgentdError> {
        let _refresh = self
            .refresh
            .lock()
            .map_err(|_| invalid("revocation refresh lock poisoned"))?;
        let raw = read_protected_file(path, 256 * 1024, "signed PQ effect revocations")?;
        let signed: SignedFinalUseRevocationUpdate = serde_json::from_slice(&raw)?;
        let now = self.clock.now_unix_ms().map_err(invalid)?;
        // Authenticate every presentation, including equal epoch/revision.
        let receipt = self
            .feed
            .apply_or_confirm_current(authority, &signed, now)
            .map_err(invalid)?;
        if receipt.authority_epoch() != self.contract_epoch {
            return Err(invalid(
                "current epoch requires a newly signed provider contract",
            ));
        }
        if self.frontier.load(&self.signer_id).map_err(invalid)?
            != authority.frontier().map_err(invalid)?
        {
            return Err(invalid("external FinalUse frontier is not current"));
        }
        Ok(receipt)
    }

    pub(super) fn validate_grant(
        &self,
        authority: &FinalUseAuthority,
        path: &Path,
        grant: &SignedFinalUseGrant,
    ) -> Result<(), AgentdError> {
        let feed = self.refresh(authority, path)?;
        let now = self.clock.now_unix_ms().map_err(invalid)?;
        if grant.grant.schema_version != 2
            || grant.grant.authority_epoch != feed.authority_epoch()
            || grant.grant.expires_at_unix_ms > feed.valid_until_unix_ms()
            || now < grant.grant.not_before_unix_ms
            || now >= grant.grant.expires_at_unix_ms
            || now >= feed.valid_until_unix_ms()
        {
            return Err(invalid(
                "PQ grant must remain inside the current signed revocation lease",
            ));
        }
        Ok(())
    }
}

pub(super) fn verify_pending_binding(
    host: &AgentdAutomationEffectHost,
    pending: &AuthorizedEffectPending,
) -> Result<(), AgentdError> {
    let runtime = host
        .pq
        .as_ref()
        .ok_or_else(|| invalid("PQ recovery owner required"))?;
    for scope in std::iter::once(&host.final_use_scope_digest).chain(&runtime.recovery_scopes) {
        let binding = FinalUseBinding {
            subject_id: host.agent_id.to_string(),
            destination_id: host.destination_id.clone(),
            request_sha256: decode_hex_array(
                pending.intent_digest.as_str(),
                "pending intent digest",
            )?,
            scope_sha256: decode_hex_array(scope.as_str(), "PQ owner scope")?,
            payload_sha256: decode_hex_array(
                pending.payload_digest.as_str(),
                "pending payload digest",
            )?,
        };
        if Sha256Digest::for_bytes(&serde_json::to_vec(&binding)?) == pending.binding_digest {
            return Ok(());
        }
    }
    Err(invalid(
        "pending effect requires its original signed provider policy",
    ))
}

#[cfg(all(test, target_os = "linux"))]
#[path = "automation_effect_host_pq_tests.rs"]
mod tests;
