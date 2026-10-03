//! Resolve root-owned per-agent descriptors before reserving a launch. The
//! resulting environment is frozen into that execution's semantic digest.

use std::ffi::OsString;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use serde::Deserialize;
use sha2::Digest;
use sha2::Sha256;

use super::Policy;
use super::hex_digest;
use super::trust;
use crate::ProcessDriverError;

const PROFILE: &str = "HEPTA_MODEL_CREDENTIAL_PROFILE_HOME";
const RELAY: &str = "HEPTA_MODEL_RELAY_SOCKET";
const CONFIG: &str = "HEPTA_SELF_ITERATION_HOST_CONFIG";
const PIN: &str = "HEPTA_SELF_ITERATION_HOST_CONFIG_DIGEST";

pub(super) struct LaunchEnvironment {
    profile: Option<OsString>,
    relay: Option<OsString>,
    legacy_config: Option<PathBuf>,
    legacy_pin: Option<OsString>,
}

impl LaunchEnvironment {
    pub(super) fn capture() -> Self {
        Self {
            profile: std::env::var_os(PROFILE),
            relay: std::env::var_os(RELAY),
            legacy_config: std::env::var_os(CONFIG).map(PathBuf::from),
            legacy_pin: std::env::var_os(PIN),
        }
    }

    pub(super) fn resolve(
        &self,
        policy: &Policy,
        agent: &AgentId,
    ) -> Result<Vec<(OsString, OsString)>, ProcessDriverError> {
        let mut environment = Vec::new();
        if self.relay.is_some() && self.profile.is_some() {
            return Err(ProcessDriverError::new(
                "model relay and direct credential profile are mutually exclusive",
            ));
        }
        if let Some(relay) = &self.relay {
            let path = Path::new(relay);
            if !path.is_absolute()
                || path
                    .components()
                    .any(|part| matches!(part, std::path::Component::ParentDir))
            {
                return Err(ProcessDriverError::new(
                    "model relay socket must be absolute and normalized",
                ));
            }
            environment.push((OsString::from(RELAY), relay.clone()));
        }
        if let Some(profile) = &self.profile {
            environment.push((OsString::from(PROFILE), profile.clone()));
        }
        if let Some(directory) = &policy.self_iteration_config_directory {
            trust::validate_root_directory(directory)?;
            let path = directory.join(format!("{agent}.json"));
            match std::fs::symlink_metadata(&path) {
                Ok(_) => {
                    let bytes = trust::read_root_file(&path, 64 * 1024)?;
                    let descriptor =
                        descriptor_environment(&path, &bytes, agent)?.ok_or_else(|| {
                            ProcessDriverError::new("per-agent descriptor identity mismatch")
                        })?;
                    environment.extend(descriptor);
                }
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(error) => return Err(error.into()),
            }
        } else if let Some(path) = &self.legacy_config {
            let bytes = trust::read_root_file(path, 64 * 1024)?;
            if let Some(descriptor) = descriptor_environment(path, &bytes, agent)? {
                if self.legacy_pin.as_deref() != Some(descriptor[1].1.as_os_str()) {
                    return Err(ProcessDriverError::new(
                        "legacy self-iteration descriptor pin mismatch",
                    ));
                }
                environment.extend(descriptor);
            }
        }
        Ok(environment)
    }
}

// The installed evolving Agentd validates the complete schema. The resource
// owner needs only the exact principal and schema version for launch routing.
#[derive(Deserialize)]
struct DescriptorIdentity {
    version: u32,
    agent_id: AgentId,
}

fn descriptor_environment(
    path: &Path,
    bytes: &[u8],
    agent: &AgentId,
) -> Result<Option<[(OsString, OsString); 2]>, ProcessDriverError> {
    let descriptor: DescriptorIdentity = serde_json::from_slice(bytes)?;
    if descriptor.version != 1 {
        return Err(ProcessDriverError::new(
            "unsupported self-iteration descriptor version",
        ));
    }
    if &descriptor.agent_id != agent {
        return Ok(None);
    }
    Ok(Some([
        (OsString::from(CONFIG), path.as_os_str().to_owned()),
        (
            OsString::from(PIN),
            OsString::from(hex_digest(Sha256::digest(bytes))),
        ),
    ]))
}

#[cfg(test)]
#[path = "local_fleet_environment_tests.rs"]
mod tests;
