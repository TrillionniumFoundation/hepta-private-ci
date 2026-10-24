//! Keep the original validated configuration and writer descriptor across the
//! Root preparation barrier. No second Registry, identity or writer is made.

use super::*;
use codex_hepta_contracts::RootAuthorityDirectory;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;

/// Root-only preparation of this same process. The ordinary configuration is
/// inaccessible until its original lock is reacquired after a live authenticated
/// Root handoff. This value cannot be serialized, cloned or used as a runtime.
pub struct PreparedRootAgentdConfig {
    config: AgentdConfig,
    process_id: u32,
    expected_uid: u32,
    expected_gid: u32,
    lock_device: u64,
    lock_inode: u64,
    _agent_custody: Arc<RootAuthorityDirectory>,
    _run_custody: Arc<RootAuthorityDirectory>,
}

impl AgentdConfig {
    /// Call only in the trusted child before dropping its credentials. `self`
    /// must come from the unchanged original constructor, which already read
    /// the original Starting record and acquired the original writer lock.
    /// Release just that lock so Root's fresh preparation can use the same file.
    /// No directory ownership or Registry lifecycle is changed by this method.
    pub fn prepare_root_handoff(
        self,
        expected_uid: u32,
        expected_gid: u32,
    ) -> Result<PreparedRootAgentdConfig, AgentdError> {
        // SAFETY: getuid/geteuid read this process's actual kernel credentials.
        if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0
            || expected_uid == 0 || expected_gid == 0
        {
            return Err(AgentdError::Invalid("Root preparation requires actual Root and a dedicated non-Root UID/GID".into()));
        }
        self.require_unconfigured_production_hosts()?;
        let agent = RootAuthorityDirectory::open(self.identity.layout.agent_root()).map_err(root_error)?;
        let run = RootAuthorityDirectory::open(self.identity.layout.run_root()).map_err(root_error)?;
        let descriptor = self._writer_lock.metadata()?;
        let path = std::fs::symlink_metadata(self.identity.layout.writer_lock())?;
        if !descriptor.is_file() || !path.is_file() || descriptor.uid() != 0 || path.uid() != 0
            || descriptor.nlink() != 1 || path.nlink() != 1
            || descriptor.dev() != path.dev() || descriptor.ino() != path.ino()
        {
            return Err(root_error("original Root writer lock custody differs"));
        }
        // Tighten the original descriptor while its Root0700 parent is retained.
        // The descriptor remains open across credential drop; it is never made
        // writable by path to the unprivileged process.
        self._writer_lock.set_permissions(std::fs::Permissions::from_mode(0o600))?;
        let record = self.registry.load_agent(&self.identity.agent_id)?;
        require_starting(&self.identity, &record)?;
        self._writer_lock.unlock()?;
        Ok(PreparedRootAgentdConfig {
            process_id: std::process::id(), expected_uid, expected_gid,
            lock_device: descriptor.dev(), lock_inode: descriptor.ino(), config: self,
            _agent_custody: agent, _run_custody: run,
        })
    }
}

impl PreparedRootAgentdConfig {
    pub fn identity(&self) -> &AgentdIdentity {
        self.config.identity()
    }

    /// Root must finish original fresh publication and exact filesystem access
    /// before handing over its sealed inputs. Reacquire the same retained file
    /// description only in the exact same, now unprivileged process, then
    /// repeat the original Registry and live writer-authority checks.
    pub fn finish(self, inputs: &crate::AgentdRootProductionInputs) -> Result<AgentdConfig, AgentdError> {
        let identity = self.config.identity();
        // SAFETY: these calls read only the current kernel credentials.
        let (uid, gid) = unsafe { (libc::geteuid(), libc::getegid()) };
        if std::process::id() != self.process_id || uid != self.expected_uid || gid != self.expected_gid
            || inputs.bootstrap.consumer.pid != self.process_id
            || inputs.bootstrap.consumer.uid != uid
            || inputs.bootstrap.registered_identity.identity()? != *identity
            || std::env::current_dir()?.canonicalize()? != identity.workspace
        {
            return Err(root_error("prepared original configuration differs from actual Root handoff or process"));
        }
        let registration = crate::authority_host_config::HostAuthorityRegistration {
            schema_version: 1, peer_pid: self.process_id,
            boot_id: inputs.bootstrap.consumer.boot_id.clone(),
            process_start_ticks: inputs.bootstrap.consumer.process_start_ticks,
            registered_identity: inputs.bootstrap.registered_identity.clone(),
            checkpoint_owner_agent_id: identity.agent_id.clone(),
            publisher_epoch: inputs.bootstrap.checkpoint.publisher_epoch,
        };
        crate::authority_host_runtime::verify_process(&registration, uid, gid)?;
        for directory in [identity.layout.agent_root(), identity.layout.run_root()] {
            let metadata = std::fs::symlink_metadata(directory)?;
            if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
                return Err(root_error("original Registry custody must remain Root-owned without shared writes"));
            }
        }
        let path = std::fs::symlink_metadata(identity.layout.writer_lock())?;
        let descriptor = self.config._writer_lock.metadata()?;
        if !path.is_file() || !descriptor.is_file() || path.uid() != 0 || descriptor.uid() != 0
            || path.nlink() != 1 || descriptor.nlink() != 1
            || path.mode() & 0o7777 != 0o600 || descriptor.mode() & 0o7777 != 0o600
            || path.dev() != self.lock_device || descriptor.dev() != self.lock_device
            || path.ino() != self.lock_inode || descriptor.ino() != self.lock_inode
        {
            return Err(root_error("the retained original writer lock was replaced or made peer-writable"));
        }
        let verify = || inputs.session.verifier().verify_sender_process_binding(
            &inputs.session.authority(), &identity.agent_id,
            &inputs.bootstrap.writer.local_lease_id, inputs.bootstrap.writer.local_lease_generation,
            identity.spawn_generation,
        ).map_err(AgentdError::GenerationFenced);
        verify()?;
        self.config._writer_lock.try_lock().map_err(|error| root_error(format!("original writer lock is still owned: {error}")))?;
        let record = self.config.registry.load_agent(&identity.agent_id)?;
        require_starting(identity, &record)?;
        verify()?;
        Ok(self.config)
    }
}

fn require_starting(identity: &AgentdIdentity, record: &codex_hepta_fleet::AgentRecord) -> Result<(), AgentdError> {
    if record.lifecycle.lifecycle != AgentLifecycle::Starting
        || record.lifecycle.generation != identity.spawn_generation
        || record.layout != identity.layout || record.manifest.workspace.as_path() != identity.workspace
        || record.manifest.resources != identity.resources
    {
        return Err(root_error("original Registry Starting record changed during Root handoff"));
    }
    Ok(())
}

fn root_error(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::GenerationFenced(format!("original Root configuration handoff: {error}"))
}

#[cfg(test)]
#[path = "config_root_handoff_tests.rs"]
mod tests;
