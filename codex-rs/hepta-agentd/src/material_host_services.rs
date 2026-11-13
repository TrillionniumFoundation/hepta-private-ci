//! The five fixed original services borrow one consumed Material owner.
//! Cancellation aliases can only shut down these same sockets; no reader,
//! writer, permit, retry channel or role upgrade is constructed here.

use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::{Duration, Instant};

use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_neuron::FileAnchorWitnessStore;

use crate::{AgentdError, OriginalCellQ24MaterialCommandOwnerV1};

use super::config::{Configuration, ServicePeer};
use super::{OriginalMaterialChannelFilesV1, files, invalid};

type MaterialOwner = OriginalCellQ24MaterialCommandOwnerV1<
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
>;

#[derive(Clone, Copy)]
enum ServiceRole {
    ExperienceCommand,
    DatasetCommand,
    ExperienceReadback,
    DatasetReadback,
    DatasetSource,
}

impl ServiceRole {
    fn label(self) -> &'static str {
        match self {
            Self::ExperienceCommand => "original Material Experience command",
            Self::DatasetCommand => "original Material Dataset command",
            Self::ExperienceReadback => "original Material Experience readback",
            Self::DatasetReadback => "original Material Dataset readback",
            Self::DatasetSource => "original Material Dataset source",
        }
    }
}

struct ShutdownGroup {
    streams: Vec<UnixStream>,
    cancelled: AtomicBool,
}

impl ShutdownGroup {
    fn stop(&self) {
        self.cancelled.store(/*val*/ true, Ordering::Release);
        for stream in &self.streams {
            // Shutdown is best effort. Explicit joins below, not this syscall,
            // determine when the original workers have actually terminated.
            let _ = stream.shutdown(Shutdown::Both);
        }
    }
}

impl Drop for ShutdownGroup {
    fn drop(&mut self) {
        self.stop();
    }
}

struct ServiceCompletion<'a> {
    shutdown: &'a ShutdownGroup,
    accepted: bool,
}

impl Drop for ServiceCompletion<'_> {
    fn drop(&mut self) {
        // This also runs during a worker panic, before its handle is joined.
        if !self.accepted {
            self.shutdown.stop();
        }
    }
}

/// Serve only the five original, preconnected purposes on the same owner.
/// All started scoped workers are joined, including after a spawn failure.
/// The original APIs construct their own relative channel lifetimes; each
/// receives only the remaining common lifetime and an overdue outer result
/// is rejected. This does not promise an exact internal absolute deadline or
/// physical interruption of synchronous Source, ledger or journal work.
pub(super) fn serve_original_material_channels(
    owner: OriginalCellQ24MaterialCommandOwnerV1<
        FileAnchorWitnessStore,
        FileAnchorWitnessStore,
        FileAnchorWitnessStore,
    >,
    cfg: &Configuration,
    end: Instant,
    experience_command: OriginalMaterialChannelFilesV1,
    dataset_command: OriginalMaterialChannelFilesV1,
    experience_readback: OriginalMaterialChannelFilesV1,
    dataset_readback: OriginalMaterialChannelFilesV1,
    dataset_source: OriginalMaterialChannelFilesV1,
) -> Result<(), AgentdError> {
    let channels = [
        (ServiceRole::ExperienceCommand, &cfg.experience_command, experience_command),
        (ServiceRole::DatasetCommand, &cfg.dataset_command, dataset_command),
        (ServiceRole::ExperienceReadback, &cfg.experience_readback, experience_readback),
        (ServiceRole::DatasetReadback, &cfg.dataset_readback, dataset_readback),
        (ServiceRole::DatasetSource, &cfg.dataset_source, dataset_source),
    ];
    let mut aliases = Vec::with_capacity(channels.len());
    for (_, _, channel) in &channels {
        match channel.stream.try_clone() {
            Ok(alias) => aliases.push(alias),
            Err(error) => {
                for (_, _, original) in &channels {
                    let _ = original.stream.shutdown(Shutdown::Both);
                }
                return Err(error.into());
            }
        }
    }
    let shutdown = ShutdownGroup { streams: aliases, cancelled: AtomicBool::default() };
    files::remaining(end)?;
    // Reject a bad fixed peer before starting any of the five services. Each
    // worker repeats this observation after its actual thread has started.
    for (_, peer, channel) in &channels {
        files::require_peer(&channel.stream, &channel.original_peer_pidfd,
            &peer.peer, peer.uid, peer.gid)?;
    }
    files::remaining(end)?;

    thread::scope(|scope| {
        let owner = &owner;
        let shutdown = &shutdown;
        let mut workers = Vec::with_capacity(channels.len());
        let mut failures = Vec::new();
        for (role, peer, channel) in channels {
            if shutdown.cancelled.load(Ordering::Acquire) {
                break;
            }
            let spawned = thread::Builder::new().name(role.label().to_owned())
                .spawn_scoped(scope, move || serve_original_channel(owner, role, peer, channel, end, shutdown));
            match spawned {
                Ok(worker) => workers.push((role, worker)),
                Err(error) => {
                    shutdown.stop();
                    failures.push(format!("{} could not start: {error}", role.label()));
                    break;
                }
            }
        }
        for (role, worker) in workers {
            match worker.join() {
                Ok(Ok(())) => {},
                Ok(Err(error)) => {
                    shutdown.stop();
                    failures.push(format!("{}: {error}", role.label()));
                }
                Err(_) => {
                    shutdown.stop();
                    failures.push(format!("{} panicked; same-operation readback is required", role.label()));
                }
            }
        }
        if !failures.is_empty() {
            return Err(invalid(failures.join("; ")));
        }
        if shutdown.cancelled.load(Ordering::Acquire) {
            return Err(invalid("original Material services were cancelled; same-operation readback is required"));
        }
        files::remaining(end)?;
        Ok(())
    })
}

fn serve_original_channel(
    owner: &MaterialOwner,
    role: ServiceRole,
    peer: &ServicePeer,
    channel: OriginalMaterialChannelFilesV1,
    end: Instant,
    shutdown: &ShutdownGroup,
) -> Result<(), AgentdError> {
    let mut completion = ServiceCompletion { shutdown, accepted: false };
    if shutdown.cancelled.load(Ordering::Acquire) {
        return Err(invalid("original Material channel was cancelled before service"));
    }
    files::require_peer(&channel.stream, &channel.original_peer_pidfd,
        &peer.peer, peer.uid, peer.gid)?;
    let lifetime = files::remaining(end)?;
    let timeout = Duration::from_millis(/*millis*/ 500);
    let policy = HostAuthorityPeerPolicy {
        peer: peer.policy_peer(), timeout, lifetime,
        request_bound: 16_384, response_bound: 16_384,
    };
    if shutdown.cancelled.load(Ordering::Acquire) {
        return Err(invalid("original Material channel was cancelled before original I/O"));
    }
    let OriginalMaterialChannelFilesV1 { stream, original_peer_pidfd } = channel;
    match role {
        ServiceRole::ExperienceCommand => {
            OriginalCellQ24MaterialCommandOwnerV1::serve_experience_commands(
                owner, stream, peer.peer.original(), peer.uid, original_peer_pidfd, timeout, lifetime,
            ).map_err(invalid)?;
        }
        ServiceRole::DatasetCommand => {
            OriginalCellQ24MaterialCommandOwnerV1::serve_dataset_commands(
                owner, stream, peer.peer.original(), peer.uid, original_peer_pidfd, timeout, lifetime,
            ).map_err(invalid)?;
        }
        ServiceRole::ExperienceReadback => {
            OriginalCellQ24MaterialCommandOwnerV1::serve_experience_readback(
                owner, stream, policy, original_peer_pidfd,
            ).map_err(invalid)?;
        }
        ServiceRole::DatasetReadback => {
            OriginalCellQ24MaterialCommandOwnerV1::serve_dataset_readback(
                owner, stream, policy, original_peer_pidfd,
            ).map_err(invalid)?;
        }
        ServiceRole::DatasetSource => {
            OriginalCellQ24MaterialCommandOwnerV1::serve_dataset_source(
                owner, stream, policy, original_peer_pidfd,
            ).map_err(invalid)?;
        }
    }
    files::remaining(end)?;
    if shutdown.cancelled.load(Ordering::Acquire) {
        return Err(invalid("original Material channel completed after another service failed"));
    }
    completion.accepted = true;
    Ok(())
}
