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

    pub(super) fn bind_original_independent_b(
        &self,
        runtime: crate::authority_host_runtime::RootIndependentBEvaluationRuntimeV1,
        config: &HostAuthorityServiceConfig,
    ) -> io::Result<crate::authority_host_runtime::BoundRootIndependentBEvaluationV1> {
        crate::authority_host_runtime::RootIndependentBEvaluationRuntimeV1::bind_original(
            runtime,
            config,
            &self.learning.socket_path,
            self.model
                .as_ref()
                .map(super::q24_model::BoundFactory::path),
            self.publication
                .as_ref()
                .map(super::generation_publication::BoundPublication::path),
        )
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
    serve_optional_with_end(
        learning,
        service,
        config,
        registration,
        owner,
        /*original_end*/ None,
        original,
    )
}

pub(super) fn serve_optional_until(
    learning: Option<&BoundLearning>,
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner: &OwnedFd,
    end: Instant,
    original: impl FnOnce() -> io::Result<()>,
) -> io::Result<()> {
    owner_alive(owner, end)?;
    let result = serve_optional_with_end(
        learning,
        service,
        config,
        registration,
        owner,
        Some(end),
        original,
    );
    owner_alive(owner, end)?;
    result
}

fn serve_optional_with_end(
    learning: Option<&BoundLearning>,
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner: &OwnedFd,
    original_end: Option<Instant>,
    original: impl FnOnce() -> io::Result<()>,
) -> io::Result<()> {
    let Some(learning) = learning else {
        return original();
    };
    let stopping = AtomicBool::new(false);
    let active = Mutex::new(None::<UnixStream>);
    let end =
        original_end.unwrap_or_else(|| Instant::now() + Duration::from_millis(config.lifetime_ms));
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
            let result = match original_end {
                Some(end) => service.serve_learning_checkpoint_until(
                    &learning.learning.backend,
                    stream,
                    policy,
                    owner.try_clone()?,
                    end,
                ),
                None => service.serve_learning_checkpoint(
                    &learning.learning.backend,
                    stream,
                    policy,
                    owner.try_clone()?,
                ),
            }
            .map_err(io::Error::other);
            if stopping.load(Ordering::Acquire) {
                Ok(())
            } else {
                result
            }
        });
        let run_model = || match original_end {
            Some(end) => super::q24_model::serve_optional_until(
                learning.model.as_ref(),
                service,
                config,
                registration,
                owner,
                end,
                original,
            ),
            None => super::q24_model::serve_optional(
                learning.model.as_ref(),
                service,
                config,
                registration,
                owner,
                original,
            ),
        };
        let result = match original_end {
            Some(end) => super::generation_publication::serve_optional_until(
                learning.publication.as_ref(),
                &learning.learning,
                service,
                config,
                registration,
                owner,
                end,
                run_model,
            ),
            None => super::generation_publication::serve_optional(
                learning.publication.as_ref(),
                &learning.learning,
                service,
                config,
                registration,
                owner,
                run_model,
            ),
        };
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
