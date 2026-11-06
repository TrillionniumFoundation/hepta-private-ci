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

#[cfg(test)]
#[path = "authority_host_listeners_tests.rs"]
mod tests;
