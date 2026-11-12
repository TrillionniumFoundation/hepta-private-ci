//! One fixed listener in the original Root serve scope. It accepts no second
//! peer, preserves the absolute end, and closes the real stream before joining.

use std::net::Shutdown;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::os::unix::net::UnixStream;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::HostIssuerTransportError;

use super::*;
use crate::authority_host_runtime::owner_alive;
use crate::authority_host_runtime::validate_lane_paths;
use crate::authority_host_runtime::validate_runtime_lanes;
use crate::authority_host_runtime::verify_pinned_process;
use crate::root_historical_task_read_protocol::HistoricalTaskReadRequestV1;
use crate::root_historical_task_read_protocol::MAX_READS;

pub(in super::super) struct BoundHistoricalTaskRead {
    runtime: HistoricalTaskReadRuntime,
    listener: UnixListener,
    device: u64,
    inode: u64,
}

impl BoundHistoricalTaskRead {
    pub(in super::super) fn bind(
        runtime: HistoricalTaskReadRuntime,
        config: &HostAuthorityServiceConfig,
    ) -> io::Result<Self> {
        original_root()?;
        runtime
            .phase
            .compare_exchange(SEALED, SERVING, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| io::Error::other("original historical offer was not sealed"))?;
        runtime.metadata.require_metadata_unchanged()?;
        let mut paths: Vec<_> = validate_runtime_lanes(config)?
            .into_iter()
            .map(|(_, path)| path)
            .collect();
        paths.push(&runtime.socket);
        validate_lane_paths(&paths, config.peer_gid)?;
        let listener = UnixListener::bind(&runtime.socket)?;
        let metadata = std::fs::symlink_metadata(&runtime.socket)?;
        let bound = Self {
            runtime,
            listener,
            device: metadata.dev(),
            inode: metadata.ino(),
        };
        if metadata.uid() != 0 || metadata.gid() != config.peer_gid {
            return Err(io::Error::other("historical listener custody differs"));
        }
        std::fs::set_permissions(
            &bound.runtime.socket,
            std::fs::Permissions::from_mode(0o660),
        )?;
        bound.listener.set_nonblocking(true)?;
        Ok(bound)
    }

    pub(in super::super) fn path(&self) -> &Path {
        &self.runtime.socket
    }
}

impl Drop for BoundHistoricalTaskRead {
    fn drop(&mut self) {
        self.runtime.phase.store(STOPPED, Ordering::Release);
        if std::fs::symlink_metadata(&self.runtime.socket)
            .is_ok_and(|entry| entry.dev() == self.device && entry.ino() == self.inode)
        {
            let _ = std::fs::remove_file(&self.runtime.socket);
        }
    }
}

pub(in super::super) fn serve_optional(
    bound: Option<&BoundHistoricalTaskRead>,
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner: &OwnedFd,
    session_end: Instant,
    original: impl FnOnce() -> io::Result<()>,
) -> io::Result<()> {
    let Some(bound) = bound else {
        return original();
    };
    let stopping = AtomicBool::new(false);
    let active = Mutex::new(None::<UnixStream>);
    std::thread::scope(|scope| {
        let worker = scope.spawn(|| {
            let result = (|| {
                let stream = loop {
                    if stopping.load(Ordering::Acquire) {
                        return Ok(());
                    }
                    owner_alive(owner, session_end)?;
                    match bound.listener.accept() {
                        Ok((stream, _)) => break stream,
                        Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                            std::thread::sleep(Duration::from_millis(5));
                        }
                        Err(error) => return Err(error),
                    }
                };
                verify_pinned_process(
                    registration,
                    config.peer_uid,
                    config.peer_gid,
                    owner,
                    session_end,
                )?;
                {
                    let mut held = active
                        .lock()
                        .map_err(|_| io::Error::other("historical stream slot poisoned"))?;
                    if stopping.load(Ordering::Acquire) {
                        return Ok(());
                    }
                    *held = Some(stream.try_clone()?);
                }
                let policy = HostAuthorityPeerPolicy {
                    peer: HostIssuerPeer {
                        uid: config.peer_uid,
                        pid: registration.peer_pid,
                    },
                    timeout: Duration::from_millis(config.timeout_ms),
                    lifetime: session_end
                        .checked_duration_since(Instant::now())
                        .ok_or_else(|| io::Error::other("original historical session expired"))?,
                    request_bound: WIRE_BOUND,
                    response_bound: WIRE_BOUND,
                };
                let mut channel =
                    HostAuthorityPeerChannel::from_stream(stream, policy, owner.try_clone()?)
                        .map_err(io::Error::other)?;
                let mut sequence = 1_u64;
                while channel
                    .exchange(|bytes| {
                        let request: HistoricalTaskReadRequestV1 = serde_json::from_slice(bytes)
                            .map_err(|_| HostIssuerTransportError::Unavailable)?;
                        if request.schema != 1
                            || request.purpose != PURPOSE
                            || request.profile != bound.runtime.profile.binding
                            || request.request_id != sequence
                            || !(1..=MAX_READS).contains(&sequence)
                            || stopping.load(Ordering::Acquire)
                        {
                            return Err(HostIssuerTransportError::Unavailable);
                        }
                        sequence = sequence
                            .checked_add(1)
                            .ok_or(HostIssuerTransportError::Unavailable)?;
                        let request_end = session_end
                            .min(Instant::now() + Duration::from_millis(config.timeout_ms));
                        bound
                            .runtime
                            .observe_complete_task(
                                service,
                                config,
                                registration,
                                owner,
                                request.request_id,
                                request_end,
                            )
                            .map_err(|_| HostIssuerTransportError::Unavailable)
                    })
                    .map_err(io::Error::other)?
                {
                    require_end(session_end)?;
                }
                Ok(())
            })();
            bound.runtime.phase.store(STOPPED, Ordering::Release);
            if stopping.load(Ordering::Acquire) {
                Ok(())
            } else {
                result
            }
        });
        let result = original();
        stopping.store(true, Ordering::Release);
        if let Some(stream) = active
            .lock()
            .map_err(|_| io::Error::other("historical stream slot poisoned"))?
            .take()
        {
            let _ = stream.shutdown(Shutdown::Both);
        }
        let historical = worker
            .join()
            .map_err(|_| io::Error::other("historical read worker panicked"))?;
        result.and(historical)
    })
}
