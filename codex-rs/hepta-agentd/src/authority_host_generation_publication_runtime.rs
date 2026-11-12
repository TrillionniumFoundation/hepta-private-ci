//! Late original enrollment and one publication connection share the exact
//! lifetime of the original Root listeners, not a detached replacement service.

use std::net::Shutdown;
use std::os::unix::net::UnixListener;
use std::os::unix::net::UnixStream;
use std::sync::atomic::AtomicBool;

use super::*;

pub(in super::super) struct BoundPublication {
    runtime: PublicationRuntime,
    listener: UnixListener,
    device: u64,
    inode: u64,
}

impl BoundPublication {
    pub(in super::super) fn bind(
        runtime: PublicationRuntime,
        config: &HostAuthorityServiceConfig,
        learning_path: &Path,
        model_path: Option<&Path>,
    ) -> io::Result<Self> {
        let mut paths: Vec<_> = validate_runtime_lanes(config)?
            .into_iter()
            .map(|(_, path)| path)
            .collect();
        let learning = learning_path.to_path_buf();
        let model = model_path.map(Path::to_path_buf);
        paths.push(&learning);
        if let Some(model) = &model {
            paths.push(model);
        }
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
            return Err(io::Error::other("publication listener custody differs"));
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

impl Drop for BoundPublication {
    fn drop(&mut self) {
        self.runtime.phase.store(CLOSED, Ordering::Release);
        if std::fs::symlink_metadata(&self.runtime.socket)
            .is_ok_and(|entry| entry.dev() == self.device && entry.ino() == self.inode)
        {
            let _ = std::fs::remove_file(&self.runtime.socket);
        }
    }
}

pub(in super::super) fn serve_optional(
    publication: Option<&BoundPublication>,
    learning: &crate::authority_host_service::RegisteredHostLearningCheckpointV1,
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner: &OwnedFd,
    original: impl FnOnce() -> io::Result<()>,
) -> io::Result<()> {
    let Some(publication) = publication else {
        return original();
    };
    let stopping = AtomicBool::new(false);
    let active = Mutex::new(None::<UnixStream>);
    let end = Instant::now() + Duration::from_millis(config.lifetime_ms);
    publication
        .runtime
        .phase
        .compare_exchange(PREPARED, ACTIVE, Ordering::AcqRel, Ordering::Acquire)
        .map_err(|_| io::Error::other("original publication runtime already consumed"))?;
    std::thread::scope(|scope| {
        let worker = scope.spawn(|| {
            let receiver = publication
                .runtime
                .receiver
                .try_lock()
                .map_err(|_| io::Error::other("publication enrollment receiver busy"))?;
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
            let slot = service.enroll_generation_publication(
                config,
                registration,
                owner,
                learning,
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
                            "original publication enrollment acknowledgement lost",
                        ));
                    }
                    slot
                }
                Err(error) => {
                    let _ = submission.acknowledgement.try_send(Err(error.to_string()));
                    return Err(error);
                }
            };
            let stream = loop {
                if stopping.load(Ordering::Acquire) {
                    return Ok(());
                }
                owner_alive(owner, end)?;
                match publication.listener.accept() {
                    Ok((stream, _)) => break stream,
                    Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                        std::thread::sleep(Duration::from_millis(5));
                    }
                    Err(error) => return Err(error),
                }
            };
            verify_pinned_process(registration, config.peer_uid, config.peer_gid, owner, end)?;
            {
                let mut held = active
                    .lock()
                    .map_err(|_| io::Error::other("publication lane poisoned"))?;
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
                    .ok_or_else(|| io::Error::other("publication Root session expired"))?,
                request_bound: 16 * 1024,
                response_bound: 16 * 1024,
            };
            let result = service.serve_generation_publication(
                &slot,
                learning,
                config,
                registration,
                stream,
                policy,
                owner.try_clone()?,
            );
            if stopping.load(Ordering::Acquire) {
                Ok(())
            } else {
                result
            }
        });
        let result = original();
        stopping.store(true, Ordering::Release);
        publication.runtime.phase.store(CLOSED, Ordering::Release);
        if let Some(stream) = active
            .lock()
            .map_err(|_| io::Error::other("publication lane poisoned"))?
            .as_ref()
        {
            let _ = stream.shutdown(Shutdown::Both);
        }
        let served = worker
            .join()
            .map_err(|_| io::Error::other("publication lane panicked"))?;
        result.and(served)
    })
}

impl BoundPublication {
    pub(in super::super) fn activate_same_actor_phase(&self) -> io::Result<()> {
        self.runtime
            .phase
            .compare_exchange(PREPARED, ACTIVE, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| io::Error::other("original phase publication runtime already consumed"))?;
        Ok(())
    }

    pub(in super::super) fn serve_same_actor_phase_publication(
        &self,
        learning: &crate::authority_host_service::RegisteredHostLearningCheckpointV1,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        phase: &crate::authority_host_same_actor_q24_phase_publication::OriginalPhasePublicationContext<'_>,
    ) -> io::Result<()> {
        let _closing = crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop::new(phase.gate);
        let end = phase.gate.deadline().instant();
        let receiver = self
            .runtime
            .receiver
            .try_lock()
            .map_err(|_| io::Error::other("original phase publication receiver busy"))?;
        let submission = loop {
            let epoch = phase.gate.original_wait_epoch()?;
            owner_alive(owner, end)?;
            match receiver.try_recv() {
                Ok(value) => break value,
                Err(mpsc::TryRecvError::Empty) => phase.gate.wait_original_change(epoch)?,
                Err(mpsc::TryRecvError::Disconnected) => {
                    return Err(io::Error::other(
                        "original phase publication capability was dropped",
                    ));
                }
            }
        };
        let slot = service.enroll_generation_publication_for_phase(
            config,
            registration,
            owner,
            learning,
            submission.inputs,
            phase,
        );
        let slot = match slot {
            Ok(slot) => {
                phase.require_original(&slot)?;
                submission
                    .acknowledgement
                    .try_send(Ok(slot.profile.binding.clone()))
                    .map_err(|_| {
                        io::Error::other("original phase publication acknowledgement lost")
                    })?;
                phase.gate.notify_original_waiters();
                phase.require_original(&slot)?;
                slot
            }
            Err(error) => {
                let _ = submission.acknowledgement.try_send(Err(error.to_string()));
                phase.gate.notify_original_waiters();
                return Err(error);
            }
        };
        let stream = loop {
            let epoch = phase.gate.original_wait_epoch()?;
            owner_alive(owner, end)?;
            match self.listener.accept() {
                Ok((stream, _)) => break stream,
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                    phase.gate.wait_original_change(epoch)?;
                }
                Err(error) => return Err(error),
            }
        };
        verify_pinned_process(registration, config.peer_uid, config.peer_gid, owner, end)?;
        phase.require_original(&slot)?;
        service.serve_generation_publication_until(
            &slot,
            learning,
            config,
            registration,
            stream,
            HostAuthorityPeerPolicy {
                peer: HostIssuerPeer {
                    uid: config.peer_uid,
                    pid: registration.peer_pid,
                },
                timeout: Duration::from_millis(config.timeout_ms),
                lifetime: Duration::from_millis(config.lifetime_ms),
                request_bound: 16 * 1024,
                response_bound: 16 * 1024,
            },
            owner.try_clone()?,
            phase,
        )
    }
}

impl BoundPublication {
    pub(in super::super) fn serve_same_actor_phase_publication_for_retirement(
        &self,
        learning: &crate::authority_host_service::RegisteredHostLearningCheckpointV1,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        mode: (
            &crate::authority_host_same_actor_q24_phase_publication::OriginalPhasePublicationContext<'_>,
            &std::sync::Arc<crate::OriginalRootRetirementScope>,
        ),
    ) -> io::Result<(
        crate::authority_host_service::generation_publication::RegisteredGenerationPublication,
        crate::OriginalRootRetiredChannel,
    )> {
        let (phase, retirement) = mode;
        retirement.require_original(phase.gate)?;
        let mut closing = crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop::new(phase.gate);
        let end = phase.gate.deadline().instant();
        let receiver = self
            .runtime
            .receiver
            .try_lock()
            .map_err(|_| io::Error::other("original phase publication receiver busy"))?;
        let submission = loop {
            let epoch = phase.gate.original_wait_epoch()?;
            owner_alive(owner, end)?;
            match receiver.try_recv() {
                Ok(value) => break value,
                Err(mpsc::TryRecvError::Empty) => phase.gate.wait_original_change(epoch)?,
                Err(mpsc::TryRecvError::Disconnected) => {
                    return Err(io::Error::other(
                        "original phase publication capability was dropped",
                    ));
                }
            }
        };
        let slot = service.enroll_generation_publication_for_phase(
            config,
            registration,
            owner,
            learning,
            submission.inputs,
            phase,
        );
        let slot = match slot {
            Ok(slot) => {
                phase.require_original(&slot)?;
                submission
                    .acknowledgement
                    .try_send(Ok(slot.profile.binding.clone()))
                    .map_err(|_| {
                        io::Error::other("original phase publication acknowledgement lost")
                    })?;
                phase.gate.notify_original_waiters();
                phase.require_original(&slot)?;
                slot
            }
            Err(error) => {
                let _ = submission.acknowledgement.try_send(Err(error.to_string()));
                phase.gate.notify_original_waiters();
                return Err(error);
            }
        };
        let stream = loop {
            let epoch = phase.gate.original_wait_epoch()?;
            owner_alive(owner, end)?;
            match self.listener.accept() {
                Ok((stream, _)) => break stream,
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                    phase.gate.wait_original_change(epoch)?;
                }
                Err(error) => return Err(error),
            }
        };
        verify_pinned_process(registration, config.peer_uid, config.peer_gid, owner, end)?;
        phase.require_original(&slot)?;
        let retired = service.serve_generation_publication_for_root_retirement(
            &slot,
            learning,
            config,
            registration,
            stream,
            HostAuthorityPeerPolicy {
                peer: HostIssuerPeer {
                    uid: config.peer_uid,
                    pid: registration.peer_pid,
                },
                timeout: Duration::from_millis(config.timeout_ms),
                lifetime: Duration::from_millis(config.lifetime_ms),
                request_bound: 16 * 1024,
                response_bound: 16 * 1024,
            },
            owner.try_clone()?,
            (phase, retirement),
        )?;
        phase.require_original(&slot)?;
        closing.disarm();
        Ok((slot, retired))
    }
}
