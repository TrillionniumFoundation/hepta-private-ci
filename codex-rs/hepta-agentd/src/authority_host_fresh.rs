//! Fresh Root preparation of the original DB, never recovery of existing state.

use super::*;
use crate::authority_host_config::HostAuthorityRegisteredIdentity;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_paths::HeptaFleetRoot;
use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;

/// A genuinely fresh original CognitiveStore cut, still under Root custody
/// and the original Agentd writer lock. It is not Clone or deserializable and
/// exposes no caller-selected cut, proof, token or generation constructor.
pub struct FreshHostCognitiveState {
    identity: HostAuthorityRegisteredIdentity,
    record: AgentRecord,
    cut: CognitiveRecoveryAnchor,
    _writer_lock: File,
    _directory: Arc<RootAuthorityDirectory>,
}

impl FreshHostCognitiveState {
    /// Prepare before releasing the registered daemon to its writable state.
    /// Only an empty Root0700 cognitive directory and the original Registry's
    /// exact Starting record are admitted. Existing or partial bytes remain
    /// untouched; a failed recovery must never call this constructor.
    pub async fn prepare(identity: &HostAuthorityRegisteredIdentity) -> io::Result<Self> {
        let (record, directory) = validate_fresh_custody(identity)?;
        RootAuthorityDirectory::open(record.layout.run_root()).map_err(io::Error::other)?;
        let writer_lock = OpenOptions::new()
            .read(true).write(true).create(true).truncate(false).mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
            .open(record.layout.writer_lock())?;
        let metadata = writer_lock.metadata()?;
        if !metadata.is_file() || metadata.uid() != 0 || metadata.nlink() != 1
            || metadata.mode() & 0o777 != 0o600
        {
            return Err(io::Error::other("fresh preparation requires the original Root0600 writer lock"));
        }
        writer_lock.try_lock().map_err(io::Error::other)?;
        if std::fs::read_dir(record.layout.cognitive_root())?.next().is_some() {
            return Err(io::Error::other("fresh preparation refuses existing cognitive bytes"));
        }
        let store = CognitiveStore::open(&record.layout).await.map_err(io::Error::other)?;
        let cut = store.recovery_anchor().await;
        // Await the original pool's shutdown even if anchor capture failed.
        // Drop alone is not a SQLx/WAL cleanup barrier.
        store.close().await;
        let cut = cut.map_err(io::Error::other)?;
        let (observed, _) = validate_fresh_custody(identity)?;
        if observed != record {
            return Err(io::Error::other("original Registry changed during fresh preparation"));
        }
        Ok(Self { identity: identity.clone(), record, cut, _writer_lock: writer_lock,
            _directory: directory })
    }

    pub(super) fn current_cut(&self, identity: &AgentdIdentity) -> io::Result<&CognitiveRecoveryAnchor> {
        if identity.agent_id != self.identity.agent_id
            || identity.spawn_generation != self.identity.spawn_generation
            || identity.fleet_root != self.identity.fleet_root
            || identity.workspace != self.identity.workspace
            || identity.resources != self.identity.resources
        {
            return Err(io::Error::other("fresh state belongs to a different original writer"));
        }
        let (record, _) = validate_fresh_custody(&self.identity)?;
        if record != self.record {
            return Err(io::Error::other("original Registry changed before fresh publication"));
        }
        Ok(&self.cut)
    }
}

fn validate_fresh_custody(
    identity: &HostAuthorityRegisteredIdentity,
) -> io::Result<(AgentRecord, Arc<RootAuthorityDirectory>)> {
    let original = identity.identity()?;
    RootAuthorityDirectory::open(original.layout.agent_root()).map_err(io::Error::other)?;
    let directory = RootAuthorityDirectory::open(original.layout.cognitive_root())
        .map_err(io::Error::other)?;
    let registry = FleetRegistry::open_existing(
        HeptaFleetRoot::parse(identity.fleet_root.clone()).map_err(io::Error::other)?,
    ).map_err(io::Error::other)?;
    let record = registry.load_agent(&identity.agent_id).map_err(io::Error::other)?;
    if record.lifecycle.lifecycle != AgentLifecycle::Starting
        || record.lifecycle.generation != identity.spawn_generation
        || record.manifest.workspace.as_path() != identity.workspace
        || record.manifest.resources != identity.resources
        || record.layout != original.layout
    {
        return Err(io::Error::other("fresh preparation requires the exact original Registry Starting record"));
    }
    Ok((record, directory))
}

#[cfg(test)]
#[path = "authority_host_fresh_tests.rs"]
mod tests;
