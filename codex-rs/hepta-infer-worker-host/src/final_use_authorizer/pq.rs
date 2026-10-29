//! Explicit PQ composition of the original runtime authorizer.
use super::*;
use crate::authority_trust_unix::UnixPqAuthorityClock;
use crate::authority_trust_unix::UnixPqFinalUseFrontier;
use crate::authority_trust_unix::UnixPqTrustEndpointConfig;
use crate::authority_trust_unix::fresh_challenge;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseAuthenticationProfile;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::PqAuthorityTrustKey;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PqFinalUseAuthorizerConfig {
    pub authentication_profile: FinalUseAuthenticationProfile,
    pub issuer_socket: PathBuf,
    pub issuer_uid: u32,
    pub signer_id: String,
    pub issuer_keys: Vec<PqAuthorityTrustKey>,
    pub authority_state_dir: PathBuf,
    pub head: FinalUseRevocations,
    pub issuer_timeout_ms: u64,
    pub revocation_distributor_id: String,
    pub revocation_keys: Vec<PqAuthorityTrustKey>,
    pub external_clock: UnixPqTrustEndpointConfig,
    pub external_frontier: UnixPqTrustEndpointConfig,
}

pub(super) struct PqRuntime {
    clock: Arc<dyn AuthorityClock>,
    feed: FinalUseRevocationFeedVerifier,
    // Per-instance scheduling only: deterministic tests pause one real claim
    // after authentication without replacing the issuer, clock, or owner.
    #[cfg(test)]
    after_feed_hook: Option<Arc<dyn Fn(&FinalUseBinding) + Send + Sync>>,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PqIssuerRequestV2 {
    pub schema_version: u32,
    pub operation: String,
    pub challenge: [u8; 32],
    pub binding: FinalUseBinding,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PqIssuerResponseV2 {
    pub schema_version: u32,
    pub challenge: [u8; 32],
    pub revocations: SignedFinalUseRevocationUpdate,
    pub grant: Option<SignedFinalUseGrant>,
    pub denial_reason: Option<String>,
}

impl UnixFinalUseAuthorizer {
    pub fn from_pq_config(config: PqFinalUseAuthorizerConfig) -> Result<Self> {
        if config.authentication_profile != FinalUseAuthenticationProfile::MlDsa65V2 {
            return Err("PQ final-use authentication profile required".into());
        }
        // Resolve every protected identity before any remote request or local
        // store open. Lexical prefix checks alone permit ancestor-symlink aliases
        // to move a purported external service into the rollbackable owner tree.
        let owner = canonical_config_path(&config.authority_state_dir, Presence::OptionalLeaf)?;
        let issuer = canonical_config_path(&config.issuer_socket, Presence::OptionalLeaf)?;
        let clock_path =
            canonical_config_path(&config.external_clock.socket_path, Presence::Existing)?;
        let frontier_path =
            canonical_config_path(&config.external_frontier.socket_path, Presence::Existing)?;
        if clock_path == issuer
            || frontier_path == issuer
            || clock_path.starts_with(&owner)
            || frontier_path.starts_with(&owner)
        {
            return Err("PQ final-use requires distinct explicit external trust services".into());
        }
        let issuer_timeout = Duration::from_millis(config.issuer_timeout_ms);
        if issuer_timeout.is_zero() || issuer_timeout > MAX_ISSUER_TIMEOUT {
            return Err("final-use issuer timeout must be 1..=30000 ms".into());
        }
        let clock = Arc::new(UnixPqAuthorityClock::new(config.external_clock)?);
        let frontier = Arc::new(UnixPqFinalUseFrontier::new(config.external_frontier)?);
        let feed = FinalUseRevocationFeedVerifier::new_pq_with_keys(
            config.revocation_distributor_id,
            config.revocation_keys,
        )?;
        // Neither call creates a remote entry. Missing or uncertain external
        // state fails before the local authority directory is opened.
        clock.now_unix_ms()?;
        frontier.load(&config.signer_id)?;
        let authority = FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
            &config.authority_state_dir,
            config.signer_id,
            config.issuer_keys,
            config.head,
            clock.clone(),
            frontier,
        )?;
        Ok(Self {
            issuer_socket: config.issuer_socket,
            issuer_uid: config.issuer_uid,
            issuer_timeout,
            authority,
            pq: Some(Arc::new(PqRuntime {
                clock,
                feed,
                #[cfg(test)]
                after_feed_hook: None,
            })),
        })
    }
    pub(super) async fn claim_exact_pq(
        &self,
        binding: FinalUseBinding,
    ) -> Result<VerifiedUseToken> {
        let runtime = self
            .pq
            .as_ref()
            .ok_or("PQ final-use profile required")?
            .clone();
        let challenge = fresh_challenge()?;
        let request = PqIssuerRequestV2 {
            schema_version: 2,
            operation: AUTHORITY_PORT_OPERATION.to_string(),
            challenge,
            binding: binding.clone(),
        };
        let raw = self
            .request_port_bytes(&serde_json::to_vec(&request)?)
            .await?;
        let response: PqIssuerResponseV2 = serde_json::from_slice(&raw)?;
        if response.schema_version != 2 || response.challenge != challenge {
            return Err("PQ issuer schema/request challenge mismatch".into());
        }
        let authority = self.authority.clone();
        // External synchronous trust calls execute off the async runtime worker.
        tokio::task::spawn_blocking(move || -> Result<VerifiedUseToken> {
            let grant = match (response.grant, response.denial_reason) {
                (Some(grant), None) => grant,
                (None, Some(reason))
                    if !reason.is_empty() && reason.len() <= MAX_DENIAL_REASON_BYTES =>
                {
                    return Err(format!("final-use authority denied turn/start: {reason}").into());
                }
                _ => return Err("PQ issuer must return exactly one outcome".into()),
            };
            if grant.grant.schema_version != 2 || grant.grant.nonce != challenge {
                return Err("PQ grant must sign the exact fresh request challenge".into());
            }
            let now = runtime.clock.now_unix_ms()?;
            let receipt =
                runtime
                    .feed
                    .apply_or_confirm_current(&authority, &response.revocations, now)?;
            if grant.grant.expires_at_unix_ms > receipt.valid_until_unix_ms() {
                return Err("PQ grant outlives authenticated revocation freshness".into());
            }
            #[cfg(test)]
            if let Some(after_feed_hook) = &runtime.after_feed_hook {
                after_feed_hook(&binding);
            }
            let token = authority.claim(&grant, &binding)?;
            // Another ordinary concurrent claim may advance the owner after
            // this response authenticated its feed. A token claimed under that
            // newer head must not inherit the older response's freshness lease.
            // This rejection deliberately leaves the claimed nonce consumed.
            if token.claimed_authority_epoch() != receipt.authority_epoch()
                || token.claimed_revocation_revision() != receipt.revision()
            {
                return Err("PQ claimed revocation head does not match authenticated feed".into());
            }
            if runtime.clock.now_unix_ms()? >= receipt.valid_until_unix_ms() {
                return Err("PQ revocation feed expired during claim".into());
            }
            Ok(token)
        })
        .await?
    }
}

enum Presence {
    Existing,
    OptionalLeaf,
}

/// A missing final component is allowed only below an existing canonical
/// parent. No ancestor, dangling symlink, `..`, or lexical alias is accepted.
fn canonical_config_path(path: &Path, presence: Presence) -> Result<PathBuf> {
    if !path.is_absolute() {
        return Err("PQ final-use requires absolute canonical host paths".into());
    }
    let canonical = match std::fs::symlink_metadata(path) {
        Ok(_) => path.canonicalize()?,
        Err(error)
            if error.kind() == std::io::ErrorKind::NotFound
                && matches!(presence, Presence::OptionalLeaf) =>
        {
            let parent = path
                .parent()
                .ok_or("PQ host path has no parent")?
                .canonicalize()?;
            parent.join(
                path.file_name()
                    .ok_or("PQ host path has no final component")?,
            )
        }
        Err(error) => return Err(error.into()),
    };
    // Path equality normalizes some lexical aliases; exact OsStr equality
    // deliberately keeps the protected configuration itself canonical.
    if canonical.as_os_str() != path.as_os_str() {
        return Err("PQ final-use host path contains an alias".into());
    }
    Ok(canonical)
}

#[cfg(all(test, target_os = "linux"))]
#[path = "pq_tests.rs"]
mod tests;

#[cfg(all(test, target_os = "linux"))]
#[path = "pq_resource_tests.rs"]
mod resource_tests;

#[cfg(all(test, target_os = "linux"))]
#[path = "pq_path_tests.rs"]
mod path_tests;

#[cfg(all(test, target_os = "linux"))]
#[path = "pq_concurrency_tests.rs"]
mod concurrency_tests;
