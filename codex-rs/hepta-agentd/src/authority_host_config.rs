//! Root-only, open-only service configuration. Ordinary peer data is never
//! parsed as registration or administrative bootstrap.

use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_paths::HeptaFleetRoot;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdIdentity;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityBindIdentity {
    pub mountpoint: PathBuf,
    pub source_path: PathBuf,
    pub device: u64,
    pub inode: u64,
}

impl HostAuthorityBindIdentity {
    pub(super) fn verify(&self) -> io::Result<()> {
        RootAuthorityDirectory::open(&self.mountpoint).map_err(io::Error::other)?;
        let actual = std::fs::metadata(&self.mountpoint)?;
        let source = std::fs::symlink_metadata(&self.source_path)?;
        if !source.is_dir()
            || source.uid() != 0
            || source.mode() & 0o777 != 0o700
            || actual.dev() != self.device
            || actual.ino() != self.inode
            || source.dev() != self.device
            || source.ino() != self.inode
        {
            return Err(io::Error::other("required bind identity mismatch"));
        }
        let mountpoint = self
            .mountpoint
            .to_str()
            .ok_or_else(|| io::Error::other("non-UTF8 mount"))?;
        if mountpoint
            .bytes()
            .any(|byte| byte.is_ascii_whitespace() || byte == b'\\')
        {
            return Err(io::Error::other("unsupported mountpoint encoding"));
        }
        let mut mounts = String::new();
        File::open("/proc/self/mountinfo")?
            .take(1_048_577)
            .read_to_string(&mut mounts)?;
        if mounts.len() > 1_048_576
            || !mounts
                .lines()
                .any(|line| line.split_whitespace().nth(4) == Some(mountpoint))
        {
            return Err(io::Error::other("required bind mount is not mounted"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityServiceConfig {
    pub schema_version: u32,
    pub state_dir: PathBuf,
    pub required_bind: HostAuthorityBindIdentity,
    pub signer_id: String,
    pub expected_verifying_key: [u8; 32],
    pub lease_id: String,
    pub lease_revision: u64,
    pub writer: Option<crate::HostAuthorityWriterRegistration>,
    pub checkpoint_state_dir: Option<PathBuf>,
    pub consumers: Option<HostAuthorityConsumersConfig>,
    pub sockets: HostAuthoritySocketPaths,
    pub peer_uid: u32,
    pub peer_gid: u32,
    pub timeout_ms: u64,
    pub lifetime_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthoritySocketPaths {
    pub observation: PathBuf,
    pub issuer: PathBuf,
    pub checkpoint: PathBuf,
    pub device_frontier: Option<PathBuf>,
    pub notes_frontier: Option<PathBuf>,
}

/// Two fixed original consumer namespaces, supplied only by the root launcher.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityConsumersConfig {
    pub device: HostAuthorityConsumerConfig,
    pub notes: HostAuthorityConsumerConfig,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityConsumerConfig {
    pub state_dir: PathBuf,
    pub owner_id: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityRegistration {
    pub schema_version: u32,
    pub peer_pid: u32,
    pub boot_id: String,
    pub process_start_ticks: u64,
    pub registered_identity: HostAuthorityRegisteredIdentity,
    pub checkpoint_owner_agent_id: AgentId,
    pub publisher_epoch: u64,
}

/// Exact original identity fields attested by the root launcher. Derived layout
/// paths come from HeptaFleetRoot; opening AgentdConfig here would incorrectly
/// compete with the actual daemon's exclusive original writer lock.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityRegisteredIdentity {
    pub agent_id: AgentId,
    pub spawn_generation: u64,
    pub fleet_root: PathBuf,
    pub workspace: PathBuf,
    pub resources: ResourceBudget,
}

impl HostAuthorityRegisteredIdentity {
    pub(super) fn identity(&self) -> io::Result<AgentdIdentity> {
        if self.spawn_generation == 0
            || self.fleet_root.canonicalize()? != self.fleet_root
            || self.workspace.canonicalize()? != self.workspace
        {
            return Err(io::Error::other("invalid registered identity"));
        }
        let layout = HeptaFleetRoot::parse(self.fleet_root.clone())
            .map_err(io::Error::other)?
            .layout()
            .agent(&self.agent_id);
        Ok(AgentdIdentity {
            agent_id: self.agent_id.clone(),
            spawn_generation: self.spawn_generation,
            fleet_root: self.fleet_root.clone(),
            workspace: self.workspace.clone(),
            resources: self.resources.clone(),
            home_root: layout.home_root().to_path_buf(),
            run_root: layout.run_root().to_path_buf(),
            control_socket: layout.agentd_control_socket().to_path_buf(),
            app_server_socket: layout.app_server_socket().to_path_buf(),
            layout,
        })
    }
}

pub(super) fn read_root_json<T: serde::de::DeserializeOwned>(path: &Path) -> io::Result<T> {
    RootAuthorityDirectory::open(
        path.parent()
            .ok_or_else(|| io::Error::other("missing parent"))?,
    )
    .map_err(io::Error::other)?;
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file()
        || metadata.uid() != 0
        || metadata.mode() & 0o777 != 0o600
        || metadata.nlink() != 1
    {
        return Err(io::Error::other(
            "configuration must be root0600 regular single-link file",
        ));
    }
    let mut bytes = Vec::new();
    file.by_ref().take(65_537).read_to_end(&mut bytes)?;
    if bytes.is_empty() || bytes.len() > 65_536 {
        return Err(io::Error::other("configuration too large"));
    }
    serde_json::from_slice(&bytes).map_err(io::Error::other)
}
