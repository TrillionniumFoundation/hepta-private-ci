//! Explicit V2 product configuration for the original Unix FinalUse port.
//! The embedding trusted host supplies its existing clock and CAS frontier;
//! neither JSON configuration nor an issuer response can manufacture them.

use super::*;
use std::sync::Arc;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseMlDsa65IssuerTrustKeyV2;

/// Protected V2 selection. The original 64 KiB file bound includes the 1952-byte
/// public-key arrays and all other fields; the core key-count limit is separate.
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FinalUseMlDsa65AuthorizerConfigV2 {
    pub schema_version: u32,
    pub issuer_socket: PathBuf,
    pub issuer_uid: u32,
    pub signer_id: String,
    pub issuer_keys: Vec<FinalUseMlDsa65IssuerTrustKeyV2>,
    pub authority_state_dir: PathBuf,
    pub authority_epoch: u64,
    pub revocation_revision: u64,
    pub revoked_grant_ids: BTreeSet<String>,
    pub issuer_timeout_ms: u64,
}

impl UnixFinalUseAuthorizer {
    /// Read the existing protected configuration channel, selecting only V2.
    /// There is no algorithm auto-detection or fallback to the V1 constructor.
    pub fn open_ml_dsa65_v2(
        config_path: &Path,
        clock: Arc<dyn AuthorityClock>,
        frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
    ) -> Result<Self> {
        let config = serde_json::from_slice(&read_private_config(config_path)?)?;
        Self::from_ml_dsa65_v2_config(config, clock, frontier_store)
    }

    pub fn from_ml_dsa65_v2_config(
        config: FinalUseMlDsa65AuthorizerConfigV2,
        clock: Arc<dyn AuthorityClock>,
        frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
    ) -> Result<Self> {
        if config.schema_version != 2
            || !config.issuer_socket.is_absolute()
            || !config.authority_state_dir.is_absolute()
        {
            return Err(
                "explicit V2 final-use configuration and absolute owner paths required".into(),
            );
        }
        let issuer_timeout = Duration::from_millis(config.issuer_timeout_ms);
        if issuer_timeout.is_zero() || issuer_timeout > MAX_ISSUER_TIMEOUT {
            return Err("final-use issuer timeout must be 1..=30000 ms".into());
        }
        let authority = FinalUseAuthority::open_state_dir_with_ml_dsa65_v2(
            &config.authority_state_dir,
            config.signer_id,
            config.issuer_keys,
            FinalUseRevocations {
                authority_epoch: config.authority_epoch,
                revision: config.revocation_revision,
                revoked_grant_ids: config.revoked_grant_ids,
            },
            clock,
            frontier_store,
        )?;
        Ok(Self {
            issuer_socket: config.issuer_socket,
            issuer_uid: config.issuer_uid,
            issuer_timeout,
            authority,
            port_schema: 2,
        })
    }
}

#[cfg(all(test, unix))]
#[path = "final_use_authorizer_ml_dsa65_v2_tests.rs"]
pub(crate) mod tests;
