//! A dedicated learning listener inside the same retained Root serve scope.

use std::net::Shutdown;
use std::os::unix::net::UnixListener;
use std::os::unix::net::UnixStream;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use super::*;
use crate::authority_host_service::RegisteredHostLearningCheckpointV1;

impl PreparedHostAuthoritySession {
    /// Reopen the separately registered learning owner from Root0600 scope
    /// configuration. No missing state is initialized and no signer is made.
    pub fn with_registered_learning(mut self, profile_file: &Path) -> io::Result<Self> {
        if self.learning.is_some() {
            return Err(io::Error::other(
                "original learning owner already installed",
            ));
        }
        self.learning = Some(self.service.open_registered_learning_checkpoint(
            &self.config,
            &self.registration,
            &self.owner_pidfd,
            profile_file,
        )?);
        Ok(self)
    }

    /// Seal the exact learning scope beside the original five-lane handoff.
    /// The caller transfers the same held Root pidfd; serving retains this
    /// owner and its dedicated listener for the original session lifetime.
    pub fn seal_learning_bootstrap(&self) -> io::Result<File> {
        let learning = self
            .learning
            .as_ref()
            .ok_or_else(|| io::Error::other("registered learning owner required"))?;
        self.service.seal_learning_checkpoint(
            &self.config,
            &self.registration,
            &self.owner_pidfd,
            learning,
        )
    }
}

pub(super) struct BoundLearning {
    learning: RegisteredHostLearningCheckpointV1,
    model: Option<super::q24_model::BoundFactory>,
    publication: Option<super::generation_publication::BoundPublication>,
    listener: UnixListener,
    device: u64,
    inode: u64,
}

impl BoundLearning {
    pub(super) fn bind(
        mut learning: RegisteredHostLearningCheckpointV1,
        config: &HostAuthorityServiceConfig,
        publication: Option<super::generation_publication::PublicationRuntime>,
    ) -> io::Result<Self> {
        let mut paths: Vec<_> = validate_runtime_lanes(config)?
            .into_iter()
            .map(|(_, path)| path)
            .collect();
        paths.push(&learning.socket_path);
        validate_lane_paths(&paths, config.peer_gid)?;
        let model = learning
            .q24_model
            .take()
            .map(|factory| {
                super::q24_model::BoundFactory::bind(factory, config, &learning.socket_path)
            })
            .transpose()?;
        let publication = publication
            .map(|runtime| {
                super::generation_publication::BoundPublication::bind(
                    runtime,
                    config,
                    &learning.socket_path,
                    model.as_ref().map(super::q24_model::BoundFactory::path),
                )
            })
            .transpose()?;
        let listener = UnixListener::bind(&learning.socket_path)?;
        let metadata = std::fs::symlink_metadata(&learning.socket_path)?;
        let bound = Self {
            learning,
            model,
            publication,
            listener,
            device: metadata.dev(),
            inode: metadata.ino(),
        };
        if metadata.uid() != 0 || metadata.gid() != config.peer_gid {
            return Err(io::Error::other("learning socket custody mismatch"));
        }
        std::fs::set_permissions(
            &bound.learning.socket_path,
            std::fs::Permissions::from_mode(0o660),
        )?;
        bound.listener.set_nonblocking(true)?;
        Ok(bound)
    }

    pub(super) fn contains_path(&self, path: &Path) -> bool {
        self.publication
            .as_ref()
            .is_some_and(|lane| lane.path() == path)
            || self.learning.socket_path == path
            || self
                .model
                .as_ref()
                .is_some_and(|model| model.path() == path)
    }
}

impl Drop for BoundLearning {
    fn drop(&mut self) {
        if std::fs::symlink_metadata(&self.learning.socket_path)
            .is_ok_and(|entry| entry.dev() == self.device && entry.ino() == self.inode)
        {
            let _ = std::fs::remove_file(&self.learning.socket_path);
        }
    }
}

pub(super) fn serve_optional(
    learning: Option<&BoundLearning>,
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner: &OwnedFd,
    original: impl FnOnce() -> io::Result<()>,
) -> io::Result<()> {
    let Some(learning) = learning else {
        return original();
    };
    let stopping = AtomicBool::new(false);
    let active = Mutex::new(None::<UnixStream>);
    let end = Instant::now() + Duration::from_millis(config.lifetime_ms);
    std::thread::scope(|scope| {
        let worker = scope.spawn(|| {
            let stream = loop {
                if stopping.load(Ordering::Acquire) {
                    return Ok(());
                }
                owner_alive(owner, end)?;
                match learning.listener.accept() {
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
                    .map_err(|_| io::Error::other("learning lane poisoned"))?;
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
                    .ok_or_else(|| io::Error::other("learning session expired"))?,
                request_bound: 16 * 1024,
                response_bound: 16 * 1024,
            };
            let result = service
                .serve_learning_checkpoint(
                    &learning.learning.backend,
                    stream,
                    policy,
                    owner.try_clone()?,
                )
                .map_err(io::Error::other);
            if stopping.load(Ordering::Acquire) {
                Ok(())
            } else {
                result
            }
        });
        let result = super::generation_publication::serve_optional(
            learning.publication.as_ref(),
            &learning.learning,
            service,
            config,
            registration,
            owner,
            || {
                super::q24_model::serve_optional(
                    learning.model.as_ref(),
                    service,
                    config,
                    registration,
                    owner,
                    original,
                )
            },
        );
        stopping.store(true, Ordering::Release);
        if let Some(stream) = active
            .lock()
            .map_err(|_| io::Error::other("learning lane poisoned"))?
            .as_ref()
        {
            let _ = stream.shutdown(Shutdown::Both);
        }
        let learned = worker
            .join()
            .map_err(|_| io::Error::other("learning lane panicked"))?;
        result.and(learned)
    })
}

impl BoundLearning {
    pub(super) fn serve_same_actor_phase_learning(
        &self,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        phase: &crate::authority_host_same_actor_q24_phase_publication::OriginalPhasePublicationContext<'_>,
        ready: impl FnOnce() -> io::Result<()>,
    ) -> io::Result<()> {
        let factory = self
            .model
            .as_ref()
            .ok_or_else(|| io::Error::other("same-actor phase original Model factory missing"))?;
        let publication = self.publication.as_ref().ok_or_else(|| {
            io::Error::other("same-actor phase original publication route missing")
        })?;
        publication.activate_same_actor_phase()?;
        std::thread::scope(|scope| {
            let closing =
                crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop::new(phase.gate);
            let model = scope.spawn(|| {
                factory.serve_same_actor_phase_factory(
                    service,
                    config,
                    registration,
                    owner,
                    phase.gate,
                )
            });
            let published = scope.spawn(|| {
                publication.serve_same_actor_phase_publication(
                    &self.learning,
                    service,
                    config,
                    registration,
                    owner,
                    phase,
                )
            });
            let learned = (|| {
                phase.gate.require_open()?;
                phase.record.require_scoped()?;
                ready()?;
                phase.gate.require_open()?;
                let end = phase.gate.deadline().instant();
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
                phase.record.require_scoped()?;
                service
                    .serve_learning_checkpoint_until(
                        &self.learning.backend,
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
                        phase.gate,
                    )
                    .map_err(io::Error::other)
            })();
            // Close before joining on success, error or an uncertain lane.
            drop(closing);
            let model = model
                .join()
                .map_err(|_| io::Error::other("original phase Model worker panicked"))?;
            let published = published
                .join()
                .map_err(|_| io::Error::other("original phase publication worker panicked"))?;
            learned.and(model).and(published)
        })
    }
}


pub(super) struct OriginalRootScopedChannelsJoined {
    learning: crate::OriginalRootRetiredChannel,
    model: crate::OriginalRootRetiredChannel,
    publication: crate::OriginalRootRetiredChannel,
    // Retain the actual CURRENT/target/selection/FinalUse readers after its
    // worker returns. This object is never reconstructed from a wire digest.
    _publication_owner:
        crate::authority_host_service::generation_publication::RegisteredGenerationPublication,
}

impl OriginalRootScopedChannelsJoined {
    pub(super) fn require_original(
        &self,
        retirement: &crate::OriginalRootRetirementScope,
    ) -> io::Result<()> {
        self.learning.require_original(
            retirement, crate::OriginalRootRetirementPurpose::Learning,
        )?;
        self.model.require_original(
            retirement, crate::OriginalRootRetirementPurpose::Model,
        )?;
        self.publication.require_original(
            retirement, crate::OriginalRootRetirementPurpose::Publication,
        )
    }
}

impl BoundLearning {
    pub(super) fn serve_same_actor_phase_learning_for_retirement(
        &self,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        mode: (
            &crate::authority_host_same_actor_q24_phase_publication::OriginalPhasePublicationContext<'_>,
            &std::sync::Arc<crate::OriginalRootRetirementScope>,
        ),
        ready: impl FnOnce() -> io::Result<()>,
    ) -> io::Result<OriginalRootScopedChannelsJoined> {
        let (phase, retirement) = mode;
        retirement.require_original(phase.gate)?;
        let factory = self
            .model
            .as_ref()
            .ok_or_else(|| io::Error::other("same-actor phase original Model factory missing"))?;
        let publication = self.publication.as_ref().ok_or_else(|| {
            io::Error::other("same-actor phase original publication route missing")
        })?;
        publication.activate_same_actor_phase()?;
        std::thread::scope(|scope| {
            let mut closing =
                crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop::new(phase.gate);
            let model = scope.spawn(|| {
                factory.serve_same_actor_phase_factory_for_retirement(
                    service,
                    config,
                    registration,
                    owner,
                    retirement,
                )
            });
            let published = scope.spawn(|| {
                publication.serve_same_actor_phase_publication_for_retirement(
                    &self.learning,
                    service,
                    config,
                    registration,
                    owner,
                    (phase, retirement),
                )
            });
            let learned = (|| {
                phase.gate.require_open()?;
                phase.record.require_scoped()?;
                ready()?;
                phase.gate.require_open()?;
                let end = phase.gate.deadline().instant();
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
                phase.record.require_scoped()?;
                service
                    .serve_learning_checkpoint_for_root_retirement(
                        &self.learning.backend,
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
                        retirement,
                    )
                    .map_err(io::Error::other)
            })();
            if learned.is_err() {
                phase.gate.close();
            }
            let model = model
                .join()
                .map_err(|_| io::Error::other("original phase Model worker panicked"))
                .and_then(|result| result);
            if model.is_err() {
                phase.gate.close();
            }
            let published = published
                .join()
                .map_err(|_| io::Error::other("original phase publication worker panicked"))
                .and_then(|result| result);
            if published.is_err() {
                phase.gate.close();
            }
            // All actual spawned workers have been joined, even when one
            // result failed. No error is reclassified as a clean EOF.
            let learned = learned?;
            let model = model?;
            let (publication_owner, publication) = published?;
            let joined = OriginalRootScopedChannelsJoined {
                learning: learned,
                model,
                publication,
                _publication_owner: publication_owner,
            };
            joined.require_original(retirement)?;
            closing.disarm();
            Ok(joined)
        })
    }
}
