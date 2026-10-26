//! The original registered loader with a late authenticated Root writer FD.
//! Recovery roles cannot pre-load an as-yet nonexistent successor generation.

use super::*;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;

impl AgentdConfig {
    /// Consume Root's actual original writer file after the real Supervisor
    /// Starting transition. Inputs must come from the original sealed Root
    /// handoff; the original live verifier and actual peer are rechecked here.
    /// No path-open fallback, fresh store, generation or authority is created.
    pub fn from_root_writer_handoff(
        inputs: &crate::AgentdRootProductionInputs,
        writer: crate::RootProductionWriterDescriptor,
        current_dir: PathBuf,
    ) -> Result<Self, AgentdError> {
        let bundle = &inputs.bootstrap;
        let writer = writer.into_file();
        let identity = bundle.registered_identity.identity()?;
        let registration = crate::HostAuthorityRegistration {
            schema_version: 1,
            peer_pid: bundle.consumer.pid,
            boot_id: bundle.consumer.boot_id.clone(),
            process_start_ticks: bundle.consumer.process_start_ticks,
            registered_identity: bundle.registered_identity.clone(),
            checkpoint_owner_agent_id: identity.agent_id.clone(),
            publisher_epoch: bundle.checkpoint.publisher_epoch,
        };
        // SAFETY: these functions read actual process credentials only.
        let (uid, gid) = unsafe { (libc::geteuid(), libc::getegid()) };
        if uid == 0
            || gid == 0
            || bundle.consumer.uid != uid
            || bundle.consumer.pid != std::process::id()
            || current_dir.canonicalize()? != std::env::current_dir()?.canonicalize()?
        {
            return Err(root_error(
                "late writer handoff requires its exact non-Root recipient",
            ));
        }
        crate::authority_host_runtime::verify_process(&registration, uid, gid)?;
        let verify = || {
            inputs
                .session
                .verifier()
                .verify_sender_process_binding(
                    &inputs.session.authority(),
                    &identity.agent_id,
                    &bundle.writer.local_lease_id,
                    bundle.writer.local_lease_generation,
                    identity.spawn_generation,
                )
                .map_err(AgentdError::GenerationFenced)
        };
        verify()?;
        let _agent = pin_control_directory(identity.layout.agent_root(), gid)?;
        let _run = pin_control_directory(identity.layout.run_root(), gid)?;
        let descriptor = writer.metadata()?;
        let named = std::fs::symlink_metadata(identity.layout.writer_lock())?;
        // SAFETY: F_GETFL reads the access flags of this retained live FD.
        let flags = unsafe { libc::fcntl(writer.as_raw_fd(), libc::F_GETFL) };
        if !descriptor.is_file()
            || !named.is_file()
            || descriptor.uid() != 0
            || named.uid() != 0
            || descriptor.nlink() != 1
            || named.nlink() != 1
            || descriptor.mode() & 0o7777 != 0o600
            || named.mode() & 0o7777 != 0o600
            || (descriptor.dev(), descriptor.ino()) != (named.dev(), named.ino())
            || flags < 0
            || flags & libc::O_ACCMODE != libc::O_RDWR
        {
            return Err(root_error(
                "late handoff is not the exact original Root0600 writer FD",
            ));
        }
        let config = Self::load_with_writer_source(
            identity.fleet_root.clone(),
            identity.agent_id.clone(),
            identity.spawn_generation,
            identity.home_root.clone(),
            identity.run_root.clone(),
            identity.home_root.clone(),
            current_dir,
            WriterSource::RootDescriptor(writer),
        )?;
        crate::authority_host_runtime::verify_process(&registration, uid, gid)?;
        verify()?;
        Ok(config)
    }
}
