//! Fixed listener-to-lane mapping and captured-owner session lifetime.
use super::*;
use std::os::unix::net::UnixListener;
use std::time::Duration;

struct SocketGuard(Vec<(std::path::PathBuf, u64, u64)>);
impl Drop for SocketGuard {
    fn drop(&mut self) {
        for (path, device, inode) in &self.0 {
            if std::fs::symlink_metadata(path)
                .is_ok_and(|entry| entry.dev() == *device && entry.ino() == *inode)
            {
                let _ = std::fs::remove_file(path);
            }
        }
    }
}

/// Read-only admission for both handoff capture and the subsequent bind.
/// This does not reserve names; serving must repeat the check before binding.
pub(crate) fn validate_runtime_lanes(
    config: &HostAuthorityServiceConfig,
) -> io::Result<Vec<(HostAuthorityLane, &std::path::PathBuf)>> {
    let mut lanes = vec![
        (HostAuthorityLane::Observation, &config.sockets.observation),
        (HostAuthorityLane::Issuer, &config.sockets.issuer),
        (HostAuthorityLane::Checkpoint, &config.sockets.checkpoint),
    ];
    if let (Some(device), Some(notes)) = (
        &config.sockets.device_frontier,
        &config.sockets.notes_frontier,
    ) {
        lanes.push((HostAuthorityLane::DeviceConsumerFrontier, device));
        lanes.push((HostAuthorityLane::NotesConsumerFrontier, notes));
    }
    let paths: Vec<_> = lanes.iter().map(|(_, path)| *path).collect();
    validate_lane_paths(&paths, config.peer_gid)?;
    Ok(lanes)
}

/// The authenticated consumer repeats the same path custody check before
/// connecting. This contains no registration, issuer or listener owner.
pub(crate) fn validate_lane_paths(paths: &[&std::path::PathBuf], peer_gid: u32) -> io::Result<()> {
    if paths.is_empty() {
        return Err(io::Error::other("lane sockets required"));
    }
    if paths
        .iter()
        .collect::<std::collections::BTreeSet<_>>()
        .len()
        != paths.len()
    {
        return Err(io::Error::other("distinct lane sockets required"));
    }
    let parent = paths[0]
        .parent()
        .ok_or_else(|| io::Error::other("socket parent"))?;
    let metadata = std::fs::symlink_metadata(parent)?;
    if !metadata.is_dir()
        || metadata.uid() != 0
        || metadata.gid() != peer_gid
        || metadata.mode() & 0o7777 != 0o2710
        || paths
            .iter()
            .any(|path| !path.is_absolute() || path.parent() != Some(parent))
    {
        return Err(io::Error::other(
            "private runtime parent must be root:peer-gid mode02710",
        ));
    }
    // Public runtime ancestors must allow peer traversal but never peer writes.
    // Every checked path is root-owned; the unprivileged peer cannot replace an
    // ancestor between this check and bind. Private state has stricter 0700 rules.
    for ancestor in parent.ancestors() {
        let entry = std::fs::symlink_metadata(ancestor)?;
        if !entry.is_dir() || entry.uid() != 0 || entry.mode() & 0o022 != 0 {
            return Err(io::Error::other("unsafe runtime ancestor"));
        }
    }
    Ok(())
}

pub(super) fn serve_lanes(
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner: &OwnedFd,
) -> io::Result<()> {
    serve_lanes_with_ready(service, config, registration, owner, || Ok(()))
}

pub(super) fn serve_lanes_with_ready(
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner: &OwnedFd,
    ready: impl FnOnce() -> io::Result<()>,
) -> io::Result<()> {
    let bound = bind_runtime_lanes(config, ready)?;
    serve_bound_lanes(service, config, registration, owner, bound)
}

pub(super) fn serve_bound_lanes(
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner: &OwnedFd,
    bound: BoundLanes,
) -> io::Result<()> {
    let BoundLanes { _guard, listeners } = bound;
    let end = Instant::now() + Duration::from_millis(config.lifetime_ms);
    let mut streams = Vec::new();
    for (lane, listener) in listeners {
        loop {
            owner_alive(owner, end)?;
            match listener.accept() {
                Ok((stream, _)) => {
                    streams.push((lane, stream));
                    break;
                }
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                    std::thread::sleep(Duration::from_millis(5))
                }
                Err(error) => return Err(error),
            }
        }
    }
    std::thread::scope(|scope| {
        let mut workers = Vec::new();
        for (lane, stream) in streams {
            let pidfd = owner.try_clone()?;
            let lifetime = end
                .checked_duration_since(Instant::now())
                .ok_or_else(|| io::Error::other("session lifetime elapsed"))?;
            let policy = HostAuthorityPeerPolicy {
                peer: HostIssuerPeer {
                    uid: config.peer_uid,
                    pid: registration.peer_pid,
                },
                timeout: Duration::from_millis(config.timeout_ms),
                lifetime,
                request_bound: 1,
                response_bound: 1,
            };
            workers.push(scope.spawn(move || service.serve(lane, stream, policy, pidfd)));
        }
        for worker in workers {
            worker
                .join()
                .map_err(|_| io::Error::other("authority lane panicked"))?
                .map_err(io::Error::other)?;
        }
        Ok(())
    })
}

pub(super) struct BoundLanes {
    _guard: SocketGuard,
    listeners: Vec<(HostAuthorityLane, UnixListener)>,
}

pub(super) fn bind_runtime_lanes(
    config: &HostAuthorityServiceConfig,
    ready: impl FnOnce() -> io::Result<()>,
) -> io::Result<BoundLanes> {
    let lanes = validate_runtime_lanes(config)?;
    let mut guard = SocketGuard(Vec::new());
    let mut listeners = Vec::new();
    for (lane, path) in lanes {
        let listener = UnixListener::bind(path)?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o660))?;
        let metadata = std::fs::symlink_metadata(path)?;
        if metadata.uid() != 0 || metadata.gid() != config.peer_gid {
            return Err(io::Error::other("socket ownership mismatch"));
        }
        guard.0.push((path.clone(), metadata.dev(), metadata.ino()));
        listener.set_nonblocking(true)?;
        listeners.push((lane, listener));
    }
    // Native launch has already completed its actual spawn and registration.
    // Release the sole child handoff only after every original listener can
    // accept, then immediately enter the original all-lane acceptance barrier.
    // A failed release drops all held listeners and their exact socket guards.
    ready()?;
    Ok(BoundLanes {
        _guard: guard,
        listeners,
    })
}

/// The explicit phase mode keeps the startup end through the existing
/// all-five-lane acceptance barrier and into each original peer channel.
/// A failed lane closes the shared gate before its scoped join can block.
pub(super) fn serve_bound_phase_lanes_until(
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner: &OwnedFd,
    bound: BoundLanes,
    gate: &std::sync::Arc<crate::same_actor_q24_phase_gate::SameActorPhaseGate>,
) -> io::Result<()> {
    use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
    let _scope_close = CloseSameActorPhaseOnDrop::new(gate);
    let BoundLanes { _guard, listeners } = bound;
    let end = gate.deadline().instant();
    let mut streams = Vec::new();
    for (lane, listener) in listeners {
        loop {
            gate.require_open()?;
            owner_alive(owner, end)?;
            match listener.accept() {
                Ok((stream, _)) => {
                    let stream_stop = gate.retain_original_stream(&stream)?;
                    streams.push((lane, stream, stream_stop));
                    break;
                }
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                    let epoch = gate.original_wait_epoch()?;
                    gate.wait_original_change(epoch)?;
                }
                Err(error) => return Err(error),
            }
        }
    }
    std::thread::scope(|scope| {
        let _join_close = CloseSameActorPhaseOnDrop::new(gate);
        let mut workers = Vec::new();
        for (lane, stream, stream_stop) in streams {
            let pidfd = owner.try_clone()?;
            let policy = HostAuthorityPeerPolicy {
                peer: HostIssuerPeer {
                    uid: config.peer_uid,
                    pid: registration.peer_pid,
                },
                timeout: Duration::from_millis(config.timeout_ms),
                // This bounds policy validation only; the channel stores end.
                lifetime: Duration::from_millis(config.lifetime_ms),
                request_bound: 1,
                response_bound: 1,
            };
            workers.push(scope.spawn(move || {
                let _stream_stop = stream_stop;
                service
                    .serve_original_phase_lane_until(lane, stream, policy, pidfd, gate)
                    .map_err(io::Error::other)
            }));
        }
        let mut result = Ok(());
        for worker in workers {
            let joined = worker
                .join()
                .map_err(|_| io::Error::other("original phase authority lane panicked"))
                .and_then(|served| served);
            if joined.is_err() {
                gate.close();
            }
            result = result.and(joined);
        }
        result
    })
}

#[cfg(test)]
#[path = "authority_host_listeners_tests.rs"]
mod tests;


pub(super) struct OriginalRootAuthorityLanesJoined {
    channels: Vec<(HostAuthorityLane, crate::OriginalRootRetiredChannel)>,
    // Keep the exact original listening sockets and inode-removal guard.
    _bound: BoundLanes,
}

impl OriginalRootAuthorityLanesJoined {
    pub(super) fn require_original(
        &self,
        retirement: &crate::OriginalRootRetirementScope,
    ) -> io::Result<()> {
        if self.channels.len() != 5 {
            return Err(io::Error::other("the actual original five Root lanes are not joined"));
        }
        let mut purposes = 0u8;
        for (lane, channel) in &self.channels {
            let (bit, purpose) = match lane {
                HostAuthorityLane::Observation => (1, crate::OriginalRootRetirementPurpose::Observation),
                HostAuthorityLane::Issuer => (2, crate::OriginalRootRetirementPurpose::Issuer),
                HostAuthorityLane::Checkpoint => (4, crate::OriginalRootRetirementPurpose::Checkpoint),
                HostAuthorityLane::DeviceConsumerFrontier => (8, crate::OriginalRootRetirementPurpose::DeviceFrontier),
                HostAuthorityLane::NotesConsumerFrontier => (16, crate::OriginalRootRetirementPurpose::NotesFrontier),
            };
            if purposes & bit != 0 {
                return Err(io::Error::other("original Root lane join duplicated a purpose"));
            }
            purposes |= bit;
            channel.require_original(retirement, purpose)?;
        }
        if purposes != 31 {
            return Err(io::Error::other("an original Root lane purpose is missing"));
        }
        Ok(())
    }
}

pub(super) fn serve_bound_phase_lanes_for_root_retirement(
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner: &OwnedFd,
    bound: BoundLanes,
    retirement: &std::sync::Arc<crate::OriginalRootRetirementScope>,
) -> io::Result<OriginalRootAuthorityLanesJoined> {
    use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
    let gate = retirement.gate();
    let mut scope_close = CloseSameActorPhaseOnDrop::new(gate);
    retirement.require_original(gate)?;
    let end = gate.deadline().instant();
    let mut streams = Vec::new();
    for (lane, listener) in &bound.listeners {
        loop {
            gate.require_open()?;
            owner_alive(owner, end)?;
            match listener.accept() {
                Ok((stream, _)) => {
                    let stream_stop = gate.retain_original_stream(&stream)?;
                    streams.push((*lane, stream, stream_stop));
                    break;
                }
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                    let epoch = gate.original_wait_epoch()?;
                    gate.wait_original_change(epoch)?;
                }
                Err(error) => return Err(error),
            }
        }
    }
    let channels = std::thread::scope(|scope| {
        let mut join_close = CloseSameActorPhaseOnDrop::new(gate);
        let mut workers = Vec::new();
        for (lane, stream, stream_stop) in streams {
            let pidfd = owner.try_clone()?;
            let policy = HostAuthorityPeerPolicy {
                peer: HostIssuerPeer {
                    uid: config.peer_uid,
                    pid: registration.peer_pid,
                },
                timeout: Duration::from_millis(config.timeout_ms),
                lifetime: Duration::from_millis(config.lifetime_ms),
                request_bound: 1,
                response_bound: 1,
            };
            workers.push((lane, scope.spawn(move || {
                service
                    .serve_original_phase_lane_for_root_retirement(
                        lane, (stream, stream_stop), policy, pidfd, retirement,
                    )
                    .map_err(io::Error::other)
            })));
        }
        let mut outcomes = Vec::new();
        for (lane, worker) in workers {
            let joined = worker
                .join()
                .map_err(|_| io::Error::other("original phase authority lane panicked"))
                .and_then(|served| served);
            if joined.is_err() {
                gate.close();
            }
            outcomes.push(joined.map(|channel| (lane, channel)));
        }
        // This collection follows every real join, including the failure path.
        let channels = outcomes.into_iter().collect::<io::Result<Vec<_>>>()?;
        retirement.require_original(gate)?;
        join_close.disarm();
        Ok::<_, io::Error>(channels)
    })?;
    let joined = OriginalRootAuthorityLanesJoined { channels, _bound: bound };
    joined.require_original(retirement)?;
    scope_close.disarm();
    Ok(joined)
}
