//! PQ-only composition for the ordinary private Browser caller. The service
//! wire remains unchanged; only Agentd owns FinalUse and its freshness checks.

use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::FinalUseAuthenticationProfile;
use codex_hepta_contracts::FinalUseAuthority;
use serde::Deserialize;
use serde_json::Value;

use crate::BrowserServoError;
use crate::BrowserServoPort;
use crate::BrowserServoProcessConfig;
use crate::ChildBrowserTransport;
use crate::pq_final_use::PqFinalUseConfig;
use crate::pq_final_use::PqFinalUseGate;

const MAX_HOST_CONFIG_BYTES: u64 = 65_536;
const MAX_TRUST_TIMEOUT_MS: u64 = 2_000;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HostConfig {
    schema_version: u32,
    authentication_profile: FinalUseAuthenticationProfile,
    authority_state_dir: PathBuf,
    final_use: PqFinalUseConfig,
    node_path: PathBuf,
    service_path: PathBuf,
    service_sha256: String,
    worker_path: PathBuf,
    worker_sha256: String,
    profile_root: PathBuf,
    journal_path: PathBuf,
    bwrap_path: PathBuf,
    driver_timeout_ms: u64,
}

/// A configured ordinary Browser owner. Construction requires explicit PQ
/// issuer, authenticated revocation, external clock and external frontier
/// trust; no compatibility constructor can create this value.
pub struct BrowserServoHost {
    pub(crate) authority: BrowserPqAuthority,
    process: BrowserServoProcessConfig,
}

pub(crate) struct BrowserPqAuthority {
    pub(crate) owner: FinalUseAuthority,
    pub(crate) gate: PqFinalUseGate,
    pub(crate) feed_path: PathBuf,
}

impl BrowserServoHost {
    pub fn open(path: &Path) -> Result<Self, BrowserServoError> {
        let bytes = crate::protected_file::read(path, MAX_HOST_CONFIG_BYTES).map_err(invalid)?;
        let value: Value = serde_json::from_slice(&bytes).map_err(invalid)?;
        // Profile refusal precedes key parsing, external trust contact, owner
        // creation, artifact inspection and any Browser child construction.
        if value.get("schema_version").and_then(Value::as_u64) != Some(2)
            || value.get("authentication_profile").and_then(Value::as_str) != Some("ml_dsa65_v2")
        {
            return Err(invalid(
                "ordinary Browser effects require schema 2 and explicit ml_dsa65_v2",
            ));
        }
        let config: HostConfig = serde_json::from_value(value).map_err(invalid)?;
        if config.schema_version != 2
            || config.authentication_profile != FinalUseAuthenticationProfile::MlDsa65V2
            || !(1..=MAX_TRUST_TIMEOUT_MS).contains(&config.final_use.external_clock.timeout_ms)
            || !(1..=MAX_TRUST_TIMEOUT_MS).contains(&config.final_use.external_frontier.timeout_ms)
        {
            return Err(invalid("Browser PQ profile or trust deadline is invalid"));
        }
        let process = BrowserServoProcessConfig {
            node_path: config.node_path,
            service_path: config.service_path,
            service_sha256: crate::browser_servo::parse_hex_32(
                &config.service_sha256,
                "service_sha256",
            )?,
            worker_path: config.worker_path,
            worker_sha256: crate::browser_servo::parse_hex_32(
                &config.worker_sha256,
                "worker_sha256",
            )?,
            profile_root: config.profile_root,
            journal_path: config.journal_path,
            bwrap_path: config.bwrap_path,
            driver_timeout_ms: config.driver_timeout_ms,
        };
        process.validate()?;
        let feed_path = config.final_use.signed_revocations_file.clone();
        let (owner, gate) = config
            .final_use
            .open(&config.authority_state_dir, &[])
            .map_err(invalid)?;
        Ok(Self {
            authority: BrowserPqAuthority {
                owner,
                gate,
                feed_path,
            },
            process,
        })
    }

    pub fn spawn(self) -> Result<BrowserServoPort<ChildBrowserTransport>, BrowserServoError> {
        let transport = ChildBrowserTransport::spawn(&self.process)?;
        Ok(BrowserServoPort::new_pq(self.authority, transport))
    }
}

pub(crate) fn invalid(error: impl std::fmt::Display) -> BrowserServoError {
    BrowserServoError::Invalid(format!("PQ Browser authority: {error}"))
}
