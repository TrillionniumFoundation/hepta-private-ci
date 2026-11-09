//! Explicit delivery of an existing learning checkpoint by one retained Root.
//! The fixed authority lanes and their registration remain unchanged.

use super::*;
use std::net::Shutdown;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

#[cfg(test)]
#[path = "authority_host_learning_delivery_stop_tests.rs"]
mod tests;

/// Cancel only this additional listener/stream when the original serving scope
/// returns or unwinds. No process signal or authority-owner restart is involved.
struct StopLearning<'a> {
    stopped: &'a AtomicBool,
    active: &'a Mutex<Option<UnixStream>>,
}

impl Drop for StopLearning<'_> {
    fn drop(&mut self) {
        self.stopped.store(true, Ordering::Release);
        let active = match self.active.lock() {
            Ok(active) => active,
            Err(poisoned) => poisoned.into_inner(),
        };
        if let Some(stream) = active.as_ref() {
            let _ = stream.shutdown(Shutdown::Both);
        }
    }
}

impl PreparedHostAuthoritySession {
    /// Consume one already registered checkpoint beside this same original
    /// service. The trusted launcher supplies an anonymous Root-created carrier
    /// and its own retained pidfd; no store, signer or lease is initialized.
    ///
    /// This entry selects the original fixed lanes, not the separate native text
    /// profile. All original registration builders must finish before this call.
    /// `ready` releases the original handoff only after both listener sets bind;
    /// the learning handoff follows once. Missing complete learning ports still
    /// cause the ordinary daemon's explicit learning selection to refuse startup.
    pub fn serve_with_registered_learning_checkpoint(
        self,
        checkpoint: crate::LearningIterationCheckpointOwnerV1,
        endpoint: PathBuf,
        handoff: UnixDatagram,
        root_pidfd: OwnedFd,
        ready: impl FnOnce() -> io::Result<()>,
    ) -> io::Result<()> {
        let Self {
            config,
            registration,
            owner_pidfd,
            service,
            root_admin,
            ..
        } = self;
        let lanes = listeners::validate_runtime_lanes(&config)?;
        let mut paths: Vec<_> = lanes.iter().map(|(_, path)| *path).collect();
        paths.push(&endpoint);
        listeners::validate_lane_paths(&paths, config.peer_gid)?;
        // Share only this fully registered service, never another pathname open.
        let service = Arc::new(service);
        let profile = crate::RootLearningCheckpointProfileV1 {
            consumer: registration.clone(),
            peer_uid: config.peer_uid,
            peer_gid: config.peer_gid,
            endpoint: endpoint.clone(),
            timeout_ms: config.timeout_ms,
            lifetime_ms: config.lifetime_ms,
        };
        let learning =
            service.learning_checkpoint_profile(checkpoint, profile, owner_pidfd.try_clone()?)?;
        let sealed = learning.seal_handoff()?;
        let listener = listeners::bind_learning_listener(&endpoint, config.peer_gid)?;
        let bound = listeners::bind_runtime_lanes(&config, || {
            ready()?;
            crate::send_root_production_handoff(
                handoff,
                &sealed,
                &root_pidfd,
                Duration::from_millis(config.timeout_ms),
            )
            .map_err(io::Error::other)?;
            if let Some(admin) = &root_admin {
                admin.activate()?;
            }
            Ok(())
        })?;
        let end = Instant::now() + Duration::from_millis(config.lifetime_ms);
        let stopped = AtomicBool::new(false);
        let active = Mutex::new(None);
        std::thread::scope(|scope| {
            let worker = scope.spawn(|| {
                let stream = loop {
                    if stopped.load(Ordering::Acquire) {
                        return Ok(());
                    }
                    owner_alive(&owner_pidfd, end)?;
                    match listener.listener.accept() {
                        Ok((stream, _)) => break stream,
                        Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                            std::thread::sleep(Duration::from_millis(5));
                        }
                        Err(error) => return Err(error),
                    }
                };
                *active
                    .lock()
                    .map_err(|_| io::Error::other("learning stream lock poisoned"))? =
                    Some(stream.try_clone()?);
                // Close the accept/cancellation race before starting protocol I/O.
                let result = if stopped.load(Ordering::Acquire) {
                    Ok(())
                } else {
                    learning.serve(stream).map_err(io::Error::other)
                };
                drop(
                    active
                        .lock()
                        .map_err(|_| io::Error::other("learning stream lock poisoned"))?
                        .take(),
                );
                result
            });
            let stop = StopLearning {
                stopped: &stopped,
                active: &active,
            };
            let original = || {
                listeners::serve_bound_lanes(&service, &config, &registration, &owner_pidfd, bound)
            };
            let result = match &root_admin {
                Some(admin) => admin.run(&service, &config, &registration, &owner_pidfd, original),
                None => original(),
            };
            drop(stop);
            let learning = worker
                .join()
                .map_err(|_| io::Error::other("learning checkpoint lane panicked"))?;
            result.and(learning)
        })
    }
}
