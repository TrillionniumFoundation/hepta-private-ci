//! Late original enrollment and one initial connection share the exact
//! lifetime of the original Root listeners, not a detached replacement service.

use std::net::Shutdown;
use std::os::unix::net::UnixListener;
use std::os::unix::net::UnixStream;
use std::sync::atomic::AtomicBool;

use super::*;

pub(in super::super) struct BoundInitial {
    runtime: InitialRuntime,
    listener: UnixListener,
    device: u64,
    inode: u64,
}

impl BoundInitial {
    pub(in super::super) fn bind(
        runtime: InitialRuntime,
        config: &HostAuthorityServiceConfig,
    ) -> io::Result<Self> {
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
            return Err(io::Error::other("initial listener custody differs"));
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

impl Drop for BoundInitial {
    fn drop(&mut self) {
        self.runtime.phase.store(CLOSED, Ordering::Release);
        if let Some(source) = &self.runtime.source_capture {
            source.close();
        }
        if std::fs::symlink_metadata(&self.runtime.socket)
            .is_ok_and(|entry| entry.dev() == self.device && entry.ino() == self.inode)
        {
            let _ = std::fs::remove_file(&self.runtime.socket);
        }
    }
}

pub(in super::super) fn serve_optional(
    initial: Option<&BoundInitial>,
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner: &OwnedFd,
    original: impl FnOnce() -> io::Result<()>,
) -> io::Result<()> {
    let Some(initial) = initial else {
        return original();
    };
    let stopping = AtomicBool::new(false);
    let active = Mutex::new(None::<UnixStream>);
    let end = Instant::now() + Duration::from_millis(config.lifetime_ms);
    initial
        .runtime
        .phase
        .compare_exchange(PREPARED, ACTIVE, Ordering::AcqRel, Ordering::Acquire)
        .map_err(|_| io::Error::other("original initial runtime already consumed"))?;
    std::thread::scope(|scope| {
        let worker = scope.spawn(|| {
            let receiver = initial
                .runtime
                .receiver
                .try_lock()
                .map_err(|_| io::Error::other("initial enrollment receiver busy"))?;
            let submission = loop {
                if stopping.load(Ordering::Acquire) {
                    return Ok(());
                }
                owner_alive(owner, end)?;
                match receiver.try_recv() {
                    Ok(submission) => break submission,
                    Err(mpsc::TryRecvError::Empty) => std::thread::sleep(Duration::from_millis(5)),
                    Err(mpsc::TryRecvError::Disconnected) => return Ok(()),
                }
            };
            let slot = service.enroll_generation_initial(
                config,
                registration,
                owner,
                &initial.runtime.deployment,
                submission.inputs,
            );
            let slot = match slot {
                Ok(slot) => {
                    if stopping.load(Ordering::Acquire)
                        || submission
                            .acknowledgement
                            .try_send(Ok(slot.profile.binding.clone()))
                            .is_err()
                    {
                        return Err(io::Error::other(
                            "original initial enrollment acknowledgement lost",
                        ));
                    }
                    slot
                }
                Err(error) => {
                    let _ = submission.acknowledgement.try_send(Err(error.to_string()));
                    return Err(error);
                }
            };
            source_capture::serve_optional(
                initial.runtime.source_capture.as_ref(),
                source_capture::SourceCaptureContext {
                    service,
                    config,
                    registration,
                    owner,
                    slot: &slot,
                    stopping: &stopping,
                    end,
                },
                || {
                    let stream = loop {
                        if stopping.load(Ordering::Acquire) {
                            return Ok(());
                        }
                        owner_alive(owner, end)?;
                        match initial.listener.accept() {
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
                        end,
                    )?;
                    {
                        let mut held = active
                            .lock()
                            .map_err(|_| io::Error::other("initial lane poisoned"))?;
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
                        lifetime: end
                            .checked_duration_since(Instant::now())
                            .ok_or_else(|| io::Error::other("initial Root session expired"))?,
                        request_bound: 16 * 1024,
                        response_bound: 16 * 1024,
                    };
                    let result = service.serve_generation_initial(
                        &slot,
                        config,
                        registration,
                        stream,
                        policy,
                        owner.try_clone()?,
                        Some(&initial.runtime.peer_source_capture),
                    );
                    // The terminal client keeps its lifetime until Root closes.
                    // Releasing this cancellation clone lets it observe EOF.
                    active
                        .lock()
                        .map_err(|_| io::Error::other("initial lane poisoned"))?
                        .take();
                    if stopping.load(Ordering::Acquire) {
                        Ok(())
                    } else {
                        result
                    }
                },
            )
        });
        let result = original();
        stopping.store(true, Ordering::Release);
        initial.runtime.phase.store(CLOSED, Ordering::Release);
        if let Some(source) = &initial.runtime.source_capture {
            source.close();
        }
        if let Some(stream) = active
            .lock()
            .map_err(|_| io::Error::other("initial lane poisoned"))?
            .as_ref()
        {
            let _ = stream.shutdown(Shutdown::Both);
        }
        let served = worker
            .join()
            .map_err(|_| io::Error::other("initial lane panicked"))?;
        result.and(served)
    })
}
