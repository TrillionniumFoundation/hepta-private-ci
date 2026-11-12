//! Late original enrollment and one initial connection share the exact
//! lifetime of the original Root listeners, not a detached replacement service.

use std::net::Shutdown;
use std::os::unix::net::UnixListener;
use std::os::unix::net::UnixStream;
use std::sync::atomic::AtomicBool;

use super::*;
use crate::authority_host_service::generation_initial::RegisteredGenerationInitial;

#[path = "authority_host_initial_enrollment_runtime.rs"]
mod enrollment;
#[path = "authority_host_initial_peer_runtime.rs"]
mod peer_ready;
use enrollment::InitialEnrollmentContext;

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
        end: Instant,
    ) -> io::Result<Self> {
        if Instant::now() >= end {
            return Err(io::Error::other("original Initial session expired"));
        }
        runtime
            .original_end
            .set(end)
            .map_err(|_| io::Error::other("original Initial deadline was already established"))?;
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
    let end = *initial
        .runtime
        .original_end
        .get()
        .ok_or_else(|| io::Error::other("original Initial deadline missing"))?;
    owner_alive(owner, end)?;
    initial
        .runtime
        .phase
        .compare_exchange(PREPARED, ACTIVE, Ordering::AcqRel, Ordering::Acquire)
        .map_err(|_| io::Error::other("original initial runtime already consumed"))?;
    std::thread::scope(|scope| {
        let worker = scope.spawn(|| {
            let context: InitialEnrollmentContext<'_> = InitialEnrollmentContext {
                initial,
                service,
                config,
                registration,
                owner,
                stopping: &stopping,
                end,
            };
            let (slot, run_start, ready_stream) =
                if let Some(deployment) = &initial.runtime.peer_deployment {
                    let Some(stream) = context.accept_original(&active)? else {
                        return Ok(());
                    };
                    let (slot, run_start) =
                        peer_ready::register_original_peer(&context, deployment, &stream)?;
                    (slot, run_start, Some(stream))
                } else {
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
                            Err(mpsc::TryRecvError::Empty) => {
                                std::thread::sleep(Duration::from_millis(5))
                            }
                            Err(mpsc::TryRecvError::Disconnected) => return Ok(()),
                        }
                    };
                    match context.enroll_original(submission.inputs, end) {
                        Ok((slot, run_start)) => {
                            if stopping.load(Ordering::Acquire)
                                || submission
                                    .acknowledgement
                                    .try_send(Ok(slot.profile.binding.clone()))
                                    .is_err()
                            {
                                RegisteredGenerationInitial::refuse_original_enrollment(&slot)?;
                                return Err(io::Error::other(
                                    "original initial enrollment acknowledgement lost",
                                ));
                            }
                            (slot, run_start, None)
                        }
                        Err(error) => {
                            let _ = submission.acknowledgement.try_send(Err(error.to_string()));
                            return Err(error);
                        }
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
                    let stream = match ready_stream {
                        Some(stream) => stream,
                        None => match context.accept_original(&active)? {
                            Some(stream) => stream,
                            None => return Ok(()),
                        },
                    };
                    let policy = context.peer_policy()?;
                    let result = service.serve_generation_initial(
                        &slot,
                        config,
                        registration,
                        stream,
                        policy,
                        owner.try_clone()?,
                        Some(&initial.runtime.peer_source_capture),
                        end,
                        run_start.as_ref(),
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
