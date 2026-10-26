//! Physical restore under the original successor Registry dispatch fence.

use super::*;
use crate::authority_host_checkpoint::PreparedMaterialRecovery;
use crate::authority_host_checkpoint::RootMaterialProfile;
use crate::authority_host_config::HostAuthorityRegistration;
use crate::authority_host_config::HostAuthorityServiceConfig;
use crate::authority_host_runtime::validate_runtime_lanes;
use crate::authority_host_runtime::verify_pinned_process;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_paths::HeptaFleetRoot;
use std::fs::File;
use std::fs::OpenOptions;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::time::Duration;
use std::time::Instant;

impl HostAuthorityService {
    pub(crate) fn original_root_writer_descriptor(&self) -> io::Result<File> {
        // SAFETY: these functions read actual credentials, not a wire witness.
        if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
            return Err(io::Error::other(
                "actual Root required for original writer FD handoff",
            ));
        }
        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| io::Error::other("original registered writer required"))?;
        writer.registration.with_live(&writer.leases, |_| {
            if self
                .issuer
                .retained_writer_authorization(&writer.registration)?
                != writer.proof
            {
                return Err(io::Error::other("retained original writer proof changed"));
            }
            let record = verify_original_starting_record(&self.identity)?;
            self.checkpoint
                .as_ref()
                .ok_or_else(|| io::Error::other("original material-backed Current required"))?
                .backend
                .observe_physical_current()
                .map_err(io::Error::other)?;
            let path = self.identity.layout.writer_lock();
            let file = OpenOptions::new()
                .read(true)
                .write(true)
                .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
                .open(path)?;
            let held = file.metadata()?;
            let named = std::fs::symlink_metadata(path)?;
            if !held.is_file()
                || !named.is_file()
                || held.uid() != 0
                || named.uid() != 0
                || held.nlink() != 1
                || named.nlink() != 1
                || held.mode() & 0o7777 != 0o600
                || named.mode() & 0o7777 != 0o600
                || (held.dev(), held.ino()) != (named.dev(), named.ino())
                || verify_original_starting_record(&self.identity)? != record
                || self.clock.now_unix_ms().map_err(io::Error::other)?
                    >= writer.registration.authority_lease.expires_at_unix_ms
            {
                return Err(io::Error::other(
                    "original Root writer FD custody or registration changed",
                ));
            }
            Ok(file)
        })
    }

    pub(crate) fn observe_registered_physical_current(
        &self,
    ) -> io::Result<crate::HostPhysicalCurrentObservation> {
        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| io::Error::other("original registered writer required"))?;
        writer.registration.with_live(&writer.leases, |_| {
            if self
                .issuer
                .retained_writer_authorization(&writer.registration)?
                != writer.proof
            {
                return Err(io::Error::other("retained original writer proof changed"));
            }
            self.checkpoint
                .as_ref()
                .ok_or_else(|| io::Error::other("original material-backed checkpoint required"))?
                .backend
                .observe_physical_current()
                .map_err(io::Error::other)
        })
    }

    pub(crate) fn resume_registered_material_handoff(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
    ) -> io::Result<()> {
        let end = Instant::now() + Duration::from_secs(30);
        verify_pinned_process(
            registration,
            config.peer_uid,
            config.peer_gid,
            owner_pidfd,
            end,
        )?;
        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| io::Error::other("original registered writer required"))?;
        writer.registration.with_live(&writer.leases, |_| {
            if self
                .issuer
                .retained_writer_authorization(&writer.registration)?
                != writer.proof
            {
                return Err(io::Error::other("retained original writer proof changed"));
            }
            let _writer_lock = retain_original_writer_lock(&self.identity)?;
            let record = verify_original_starting_record(&self.identity)?;
            let checkpoint = self
                .checkpoint
                .as_ref()
                .ok_or_else(|| io::Error::other("existing material-backed Current required"))?;
            let installed = checkpoint
                .backend
                .reopen_material_installation()
                .map_err(io::Error::other)?;
            if verify_original_starting_record(&self.identity)? != record
                || self.clock.now_unix_ms().map_err(io::Error::other)?
                    >= writer.registration.authority_lease.expires_at_unix_ms
            {
                return Err(io::Error::other(
                    "original registration changed during material reconciliation",
                ));
            }
            verify_pinned_process(
                registration,
                config.peer_uid,
                config.peer_gid,
                owner_pidfd,
                end,
            )?;
            installed
                .release_to_registered_owner(config.peer_uid, config.peer_gid)
                .map_err(io::Error::other)
        })
    }

    pub(crate) fn recover_material_from_registered(
        mut self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
    ) -> io::Result<Self> {
        let end = Instant::now() + Duration::from_secs(30);
        verify_pinned_process(
            registration,
            config.peer_uid,
            config.peer_gid,
            owner_pidfd,
            end,
        )?;
        validate_runtime_lanes(config)?;
        if self.checkpoint.is_some() || self.consumers.is_some() {
            return Err(io::Error::other(
                "recovery requires unopened original checkpoint lanes",
            ));
        }
        let directory = config
            .checkpoint_state_dir
            .as_ref()
            .filter(|path| path.parent() == Some(config.state_dir.as_path()))
            .ok_or_else(|| io::Error::other("original checkpoint state child required"))?;
        let material_root = config.state_dir.join("cognitive-material-v1");
        if *directory == material_root {
            return Err(io::Error::other("checkpoint and material must be distinct"));
        }
        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| io::Error::other("registered successor writer required"))?;
        let (checkpoint, consumers) = writer.registration.with_live(&writer.leases, |_| {
            if self
                .issuer
                .retained_writer_authorization(&writer.registration)?
                != writer.proof
            {
                return Err(io::Error::other("retained successor writer proof changed"));
            }
            let _writer_lock = retain_original_writer_lock(&self.identity)?;
            let record = verify_original_starting_record(&self.identity)?;
            let peer = CognitiveCheckpointPeerLifetime {
                uid: config.peer_uid,
                pid: registration.peer_pid,
                boot_id: registration.boot_id.clone(),
                process_start_ticks: registration.process_start_ticks,
            };
            let binding = writer.checkpoint_registration(
                &self.issuer,
                registration.publisher_epoch,
                peer.clone(),
            )?;
            let recovery = PreparedMaterialRecovery::observe(
                RootAuthorityDirectory::open(directory).map_err(io::Error::other)?,
                RootMaterialProfile {
                    layout: self.identity.layout.clone(),
                    root: material_root.clone(),
                    deadline: Duration::from_millis(config.timeout_ms.min(5_000)),
                },
                binding,
                self.clock.clone(),
            )
            .map_err(io::Error::other)?;
            // All authority, retirement and independent-image admission precedes
            // the first custody mutation. Never read/hash the suspect live DB.
            let _custody = seize_registered_cognitive_root(&self.identity, config.peer_uid)?;
            let (backend, installed) = recovery
                .install()
                .map_err(io::Error::other)?
                .adopt()
                .map_err(io::Error::other)?;
            let consumers = match (
                &config.consumers,
                &config.sockets.device_frontier,
                &config.sockets.notes_frontier,
            ) {
                (Some(consumers), Some(_), Some(_)) => Some(RegisteredConsumers::open(
                    &config.state_dir,
                    consumers,
                    &self.issuer.trust_key()?.key_id,
                    self.clock.clone(),
                    writer.registration.authority_lease.expires_at_unix_ms,
                )?),
                (None, None, None) => None,
                _ => {
                    return Err(io::Error::other(
                        "both original consumer lanes required together",
                    ));
                }
            };
            if verify_original_starting_record(&self.identity)? != record
                || self.clock.now_unix_ms().map_err(io::Error::other)?
                    >= writer.registration.authority_lease.expires_at_unix_ms
            {
                return Err(io::Error::other(
                    "successor identity or lease changed during restore",
                ));
            }
            verify_pinned_process(
                registration,
                config.peer_uid,
                config.peer_gid,
                owner_pidfd,
                end,
            )?;
            installed
                .release_to_registered_owner(config.peer_uid, config.peer_gid)
                .map_err(io::Error::other)?;
            Ok((
                RegisteredCheckpoint::adopted_material(backend, peer),
                consumers,
            ))
        })?;
        self.checkpoint = Some(checkpoint);
        self.consumers = consumers;
        Ok(self)
    }
}

fn verify_original_starting_record(
    identity: &AgentdIdentity,
) -> io::Result<codex_hepta_fleet::AgentRecord> {
    let fleet = HeptaFleetRoot::parse(identity.fleet_root.clone()).map_err(io::Error::other)?;
    let registry = FleetRegistry::open_existing(fleet).map_err(io::Error::other)?;
    let snapshot = registry.load().map_err(io::Error::other)?;
    let record = snapshot
        .agent(&identity.agent_id)
        .ok_or_else(|| io::Error::other("original Agent missing"))?;
    if snapshot.agents.len() != 1
        || record.lifecycle.lifecycle != AgentLifecycle::Starting
        || record.lifecycle.generation != identity.spawn_generation
        || record.layout != identity.layout
        || record.manifest.workspace.as_path() != identity.workspace
        || record.manifest.resources != identity.resources
    {
        return Err(io::Error::other(
            "one exact original Starting successor required",
        ));
    }
    Ok(record.clone())
}

fn retain_original_writer_lock(identity: &AgentdIdentity) -> io::Result<File> {
    let parent = identity.layout.run_root();
    let directory = std::fs::symlink_metadata(parent)?;
    if !directory.is_dir()
        || directory.uid() != 0
        || directory.mode() & 0o022 != 0
        || parent.canonicalize()? != parent
    {
        return Err(io::Error::other("original Root run directory required"));
    }
    let path = identity.layout.writer_lock();
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
        .open(path)?;
    let held = file.metadata()?;
    let named = std::fs::symlink_metadata(path)?;
    if !held.is_file()
        || held.uid() != 0
        || held.nlink() != 1
        || held.mode() & 0o7777 != 0o600
        || (held.dev(), held.ino()) != (named.dev(), named.ino())
    {
        return Err(io::Error::other(
            "retained original Root0600 writer lock required",
        ));
    }
    file.try_lock().map_err(io::Error::other)?;
    Ok(file)
}

fn seize_registered_cognitive_root(identity: &AgentdIdentity, uid: u32) -> io::Result<File> {
    let path = identity.layout.cognitive_root();
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    let held = file.metadata()?;
    let named = std::fs::symlink_metadata(path)?;
    // Actual Root was checked by independent material admission before this
    // function. The old owner must have exactly its registered private root.
    if !held.is_dir()
        || (held.uid() != uid && held.uid() != 0)
        || held.mode() & 0o7777 != 0o700
        || (held.dev(), held.ino()) != (named.dev(), named.ino())
        || path.canonicalize()? != path
    {
        return Err(io::Error::other(
            "original registered cognitive directory custody differs",
        ));
    }
    // SAFETY: the descriptor pins the exact checked original directory. Root
    // takes custody only after the original old process and lease are retired.
    if unsafe { libc::fchown(file.as_raw_fd(), 0, 0) } != 0 {
        return Err(io::Error::last_os_error());
    }
    file.sync_all()?;
    Ok(file)
}
