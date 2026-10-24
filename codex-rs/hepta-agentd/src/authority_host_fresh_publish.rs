//! Explicit genesis of original protected heads under the existing writer.

use super::*;
use crate::authority_host_config::HostAuthorityRegistration;
use crate::authority_host_config::HostAuthorityServiceConfig;
use crate::authority_host_runtime::validate_runtime_lanes;
use crate::authority_host_runtime::verify_pinned_process;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use std::fs::File;
use std::os::unix::fs::DirBuilderExt;
use std::time::Duration;
use std::time::Instant;

impl HostAuthorityService {
    pub(crate) fn initialize_fresh_heads(
        mut self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
        fresh: FreshHostCognitiveState,
    ) -> io::Result<Self> {
        let end = Instant::now() + Duration::from_secs(30);
        verify_pinned_process(registration, config.peer_uid, config.peer_gid, owner_pidfd, end)?;
        validate_runtime_lanes(config)?;
        if self.checkpoint.is_some() || self.consumers.is_some() {
            return Err(io::Error::other("fresh publication cannot replace existing service owners"));
        }
        let writer = self.writer.as_ref().ok_or_else(|| io::Error::other("registered writer required"))?;
        let directory = config.checkpoint_state_dir.as_ref()
            .ok_or_else(|| io::Error::other("fresh checkpoint directory is required"))?;
        let mut paths = vec![directory];
        match (&config.consumers, &config.sockets.device_frontier, &config.sockets.notes_frontier) {
            (Some(consumers), Some(_), Some(_)) => {
                if consumers.device.owner_id != config.signer_id || consumers.notes.owner_id != config.signer_id {
                    return Err(io::Error::other("consumer owner must match the canonical signer"));
                }
                paths.extend([&consumers.device.state_dir, &consumers.notes.state_dir]);
            }
            (None, None, None) => {}
            _ => return Err(io::Error::other("both fixed consumer lanes are required together")),
        }
        if paths.iter().collect::<std::collections::BTreeSet<_>>().len() != paths.len()
            || paths.iter().any(|path| path.parent() != Some(config.state_dir.as_path()))
        {
            return Err(io::Error::other("fresh heads require distinct direct protected-state children"));
        }
        RootAuthorityDirectory::open(&config.state_dir).map_err(io::Error::other)?;
        for path in &paths {
            match std::fs::symlink_metadata(path) {
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                Err(error) => return Err(error),
                Ok(_) => return Err(io::Error::other("fresh publication refuses existing or partial protected state")),
            }
        }
        let cut = fresh.current_cut(&self.identity)?;
        let (checkpoint, consumers) = writer.registration.with_live(&writer.leases, |_| {
            if self.issuer.retained_writer_authorization(&writer.registration)? != writer.proof {
                return Err(io::Error::other("retained writer proof changed"));
            }
            let binding = writer.checkpoint_registration(&self.issuer, registration.publisher_epoch,
                CognitiveCheckpointPeerLifetime {
                    uid: config.peer_uid, pid: registration.peer_pid, boot_id: registration.boot_id.clone(),
                    process_start_ticks: registration.process_start_ticks,
                })?;
            for path in &paths {
                std::fs::DirBuilder::new().mode(0o700).create(path)?;
                File::open(&config.state_dir)?.sync_all()?;
            }
            let checkpoint = RegisteredCheckpoint::initialize_fresh(
                RootAuthorityDirectory::open(directory).map_err(io::Error::other)?,
                binding, cut.clone(), self.clock.clone(),
            )?;
            let consumers = config.consumers.as_ref().map(|consumers| RegisteredConsumers::initialize_fresh(
                &config.state_dir, consumers, &self.issuer, self.clock.clone(),
                writer.registration.authority_lease.expires_at_unix_ms,
            )).transpose()?;
            Ok((checkpoint, consumers))
        })?;
        fresh.current_cut(&self.identity)?;
        verify_pinned_process(registration, config.peer_uid, config.peer_gid, owner_pidfd, end)?;
        self.checkpoint = Some(checkpoint);
        self.consumers = consumers;
        // The original writer lock remains held through all durable creation
        // and post-I/O checks. Failure retains every partial byte for diagnosis.
        drop(fresh);
        Ok(self)
    }
}
