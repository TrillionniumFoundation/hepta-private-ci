//! The single initial configuration schema shared by the Root installer and Host.
//! These values select installed resources; they do not grant writer authority.

use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;
use serde::Serialize;
use std::io;
use std::path::Path;
use std::path::PathBuf;

pub const ROOT_NOTES_HOST_CONFIG_OPERATION_V1: &str = "root_notes_host_config_v1";
pub const ROOT_NOTES_HOST_CONFIG_BOUND: usize = 64 * 1024;

/// Initial FD 0 payload. The original authority bootstrap arrives separately on
/// the canonical launch stream; neither it nor a recovery cut belongs here.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RootNotesHostConfigV1 {
    pub schema_version: u32,
    pub operation: String,
    pub root: CognitiveCheckpointPeerLifetime,
    pub launch: RootNotesLaunchEndpointV1,
    pub agent: RootNotesAgentPathsV1,
    pub authbus: RootNotesAuthBusPathsV1,
    pub session_peer_config_path: PathBuf,
    pub installed_bundle: RootNotesInstalledBundleV1,
    pub deployment: RootNotesDeploymentV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RootNotesLaunchEndpointV1 {
    pub socket_path: PathBuf,
    /// Bounds the initial wait, never extends either original launch deadline.
    pub wait_lifetime_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RootNotesAgentPathsV1 {
    pub fleet_root: PathBuf,
    pub agent_id: AgentId,
    pub spawn_generation: u64,
    pub home_root: PathBuf,
    pub run_root: PathBuf,
    pub codex_home: PathBuf,
    pub workspace: PathBuf,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RootNotesAuthBusPathsV1 {
    pub trust_file: PathBuf,
    pub checkpoint_file: PathBuf,
    pub objective_profile_file: PathBuf,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RootNotesInstalledBundleV1 {
    /// Root-owned, single-link regular file containing exactly the bindings DTO.
    /// The installer derives its values from the actual installed bundle.
    pub manifest_path: PathBuf,
    #[serde(with = "digest32")]
    pub manifest_sha256: Digest32,
    pub bindings: RootNotesInstalledBindingsV1,
}

/// Exact inputs used by the original Notes objective compiler. A digest match
/// verifies installed bytes; it does not issue an authority lease or grant.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RootNotesInstalledBindingsV1 {
    #[serde(with = "digest32")]
    pub principal_scope_digest: Digest32,
    #[serde(with = "generation")]
    pub policy_generation: Generation,
    pub locale: String,
    #[serde(with = "digest32")]
    pub runtime_body_digest: Digest32,
    #[serde(with = "digest32")]
    pub preference_state_digest: Digest32,
    #[serde(with = "digest32")]
    pub model_tuple_digest: Digest32,
    #[serde(with = "digest32")]
    pub prompt_registry_digest: Digest32,
    #[serde(with = "digest32")]
    pub artifact_set_digest: Digest32,
}

/// A sealed installation choice, never a runtime fallback. Both profiles retain
/// the original two FinalUse consumers and revocation observation.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum RootNotesDeploymentV1 {
    /// No Device target is attached and no Device grant may be issued.
    NotesOnly {},
    /// Requires actual control FD 5, sealed HOS2BOOTv2 FD 6 and original QueryAbi.
    NativeHos2 {},
}

impl RootNotesHostConfigV1 {
    /// Checks only closed-document structure and path/role relationships. The
    /// caller must separately authenticate sealed provenance, installed files,
    /// actual Root lifetime, original Fleet identity and original authority.
    pub fn validate_shape(&self) -> io::Result<()> {
        if self.schema_version != 1
            || self.operation != ROOT_NOTES_HOST_CONFIG_OPERATION_V1
            || self.root.uid != 0
            || self.root.pid == 0
            || self.root.pid > i32::MAX as u32
            || self.root.process_start_ticks == 0
            || !canonical_boot_id(&self.root.boot_id)
            || self.agent.spawn_generation == 0
            || !(1..=300_000).contains(&self.launch.wait_lifetime_ms)
        {
            return Err(invalid("Root Notes initial config identity or version"));
        }
        for path in [
            &self.launch.socket_path,
            &self.agent.fleet_root,
            &self.agent.home_root,
            &self.agent.run_root,
            &self.agent.codex_home,
            &self.agent.workspace,
            &self.authbus.trust_file,
            &self.authbus.checkpoint_file,
            &self.authbus.objective_profile_file,
            &self.session_peer_config_path,
            &self.installed_bundle.manifest_path,
        ] {
            require_absolute_path(path)?;
        }
        let home = &self.agent.home_root;
        if self.launch.socket_path.as_os_str().len() > 107
            || self.agent.codex_home != *home
            || self.agent.run_root == *home
            || self.authbus.trust_file.parent() != Some(home.as_path())
            || self.authbus.objective_profile_file.parent() != Some(home.as_path())
            || self.authbus.trust_file == self.authbus.objective_profile_file
            || self.authbus.checkpoint_file.starts_with(home)
            || self.launch.socket_path.starts_with(home)
            || self.session_peer_config_path.starts_with(home)
            || self.installed_bundle.manifest_path.starts_with(home)
        {
            return Err(invalid("Root Notes initial config path roles"));
        }
        if self.installed_bundle.manifest_sha256.is_zero() {
            return Err(invalid("Root Notes installed manifest digest"));
        }
        self.installed_bundle.bindings.validate_shape()
    }
}

impl RootNotesInstalledBindingsV1 {
    /// Rejects empty bindings without claiming that installed assets exist.
    pub fn validate_shape(&self) -> io::Result<()> {
        if !matches!(self.locale.as_str(), "en-US" | "zh-CN")
            || [
                self.principal_scope_digest,
                self.runtime_body_digest,
                self.preference_state_digest,
                self.model_tuple_digest,
                self.prompt_registry_digest,
                self.artifact_set_digest,
            ]
            .into_iter()
            .any(Digest32::is_zero)
        {
            return Err(invalid("Root Notes installed bindings"));
        }
        Ok(())
    }
}

fn require_absolute_path(path: &Path) -> io::Result<()> {
    let value = path
        .to_str()
        .ok_or_else(|| invalid("Root Notes path must be UTF-8"))?;
    if !value.starts_with('/')
        || value.len() > 4096
        || value.contains('\0')
        || value
            .split('/')
            .skip(1)
            .any(|part| matches!(part, "" | "." | ".."))
    {
        return Err(invalid("Root Notes path must be absolute and normalized"));
    }
    Ok(())
}

fn canonical_boot_id(value: &str) -> bool {
    value.len() == 36
        && value.bytes().enumerate().all(|(index, byte)| {
            if [8, 13, 18, 23].contains(&index) {
                byte == b'-'
            } else {
                matches!(byte, b'0'..=b'9' | b'a'..=b'f')
            }
        })
        && value
            .bytes()
            .any(|byte| matches!(byte, b'1'..=b'9' | b'a'..=b'f'))
}

fn invalid(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

mod digest32 {
    use super::*;
    use serde::de::Error as _;

    pub fn serialize<S: serde::Serializer>(
        value: &Digest32,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        serializer.collect_str(value)
    }

    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Digest32, D::Error> {
        String::deserialize(deserializer)?
            .parse()
            .map_err(D::Error::custom)
    }
}

mod generation {
    use super::*;
    use serde::de::Error as _;

    pub fn serialize<S: serde::Serializer>(
        value: &Generation,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        serializer.serialize_u64(value.get())
    }

    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Generation, D::Error> {
        Generation::new(u64::deserialize(deserializer)?).map_err(D::Error::custom)
    }
}

#[cfg(test)]
#[path = "root_notes_host_config_tests.rs"]
mod tests;
