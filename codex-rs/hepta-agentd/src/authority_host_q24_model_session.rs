//! Retain the separately enrolled factory in the original Root serve scope.

use std::net::Shutdown;
use std::os::unix::net::UnixListener;
use std::os::unix::net::UnixStream;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use super::*;
use crate::authority_host_service::q24_model::RegisteredQ24ModelFactory;

impl PreparedHostAuthoritySession {
    /// Open-only enrollment beside the already installed original learning
    /// owner. A missing/partial namespace never becomes a fresh reservation.
    pub fn with_registered_q24_model_factory(
        mut self,
        reservation_file: &Path,
    ) -> io::Result<Self> {
        let learning = self.learning.as_mut().ok_or_else(|| {
            io::Error::other("original learning enrollment required before Model factory")
        })?;
        if learning.q24_model.is_some() {
            return Err(io::Error::other("original Model factory already installed"));
        }
        learning.q24_model = Some(self.service.open_q24_model_factory(
            &self.config,
            &self.registration,
            &self.owner_pidfd,
            &learning.profile,
            reservation_file,
        )?);
        Ok(self)
    }

    /// Consume the only writable rights retained by this Root session. Its
    /// live service retains read-only observers and the protected registry CAS.
    pub fn take_q24_model_factory_offer(
        &mut self,
    ) -> io::Result<crate::RootQ24ModelFactoryOfferV1> {
        let factory = self
            .learning
            .as_mut()
            .and_then(|learning| learning.q24_model.as_mut())
            .ok_or_else(|| io::Error::other("registered original Model factory required"))?;
        self.service.seal_q24_model_factory_offer(
            &self.config,
            &self.registration,
            &self.owner_pidfd,
            factory,
        )
    }
}

pub(super) struct BoundFactory {
    factory: RegisteredQ24ModelFactory,
    listener: UnixListener,
    device: u64,
    inode: u64,
}

impl BoundFactory {
    pub(super) fn bind(
        factory: RegisteredQ24ModelFactory,
        config: &HostAuthorityServiceConfig,
        learning_path: &Path,
    ) -> io::Result<Self> {
        let mut paths: Vec<_> = validate_runtime_lanes(config)?
            .into_iter()
            .map(|(_, path)| path)
            .collect();
        let learning_path = learning_path.to_path_buf();
        paths.push(&learning_path);
        paths.push(&factory.socket_path);
        validate_lane_paths(&paths, config.peer_gid)?;
        let listener = UnixListener::bind(&factory.socket_path)?;
        let metadata = std::fs::symlink_metadata(&factory.socket_path)?;
        let bound = Self {
            factory,
            listener,
            device: metadata.dev(),
            inode: metadata.ino(),
        };
        if metadata.uid() != 0 || metadata.gid() != config.peer_gid {
            return Err(io::Error::other("factory socket original custody mismatch"));
        }
        std::fs::set_permissions(
            &bound.factory.socket_path,
            std::fs::Permissions::from_mode(0o660),
        )?;
        bound.listener.set_nonblocking(true)?;
        Ok(bound)
    }

    pub(super) fn path(&self) -> &Path {
        &self.factory.socket_path
    }
}

impl Drop for BoundFactory {
    fn drop(&mut self) {
        if std::fs::symlink_metadata(&self.factory.socket_path)
            .is_ok_and(|entry| entry.dev() == self.device && entry.ino() == self.inode)
        {
            let _ = std::fs::remove_file(&self.factory.socket_path);
        }
    }
}

pub(super) fn serve_optional(
    factory: Option<&BoundFactory>,
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner: &OwnedFd,
    original: impl FnOnce() -> io::Result<()>,
) -> io::Result<()> {
    let Some(factory) = factory else {
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
                match factory.listener.accept() {
                    Ok((stream, _)) => break stream,
                    Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                        std::thread::sleep(Duration::from_millis(5))
                    }
                    Err(error) => return Err(error),
                }
            };
            verify_pinned_process(registration, config.peer_uid, config.peer_gid, owner, end)?;
            {
                let mut held = active
                    .lock()
                    .map_err(|_| io::Error::other("factory lane poisoned"))?;
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
                    .ok_or_else(|| io::Error::other("factory session expired"))?,
                request_bound: 16 * 1024,
                response_bound: 16 * 1024,
            };
            let result = service.serve_q24_model_factory(
                &factory.factory,
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
        if let Some(stream) = active
            .lock()
            .map_err(|_| io::Error::other("factory lane poisoned"))?
            .as_ref()
        {
            let _ = stream.shutdown(Shutdown::Both);
        }
        let served = worker
            .join()
            .map_err(|_| io::Error::other("factory lane panicked"))?;
        result.and(served)
    })
}
