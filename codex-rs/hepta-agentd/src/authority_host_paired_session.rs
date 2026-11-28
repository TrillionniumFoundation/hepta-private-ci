//! A single paired connection inside the original Root session serve scope.

use super::*;
use crate::authority_host_service::RegisteredPairedTrainingPlan;
use std::net::Shutdown;
use std::os::fd::AsRawFd;
use std::os::unix::net::UnixListener;
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

impl PreparedHostAuthoritySession {
    /// Retain two already held descriptors under this same Root writer.
    /// No content is read and no enrollment, policy or effect is created.
    pub fn with_original_paired_training_plan(
        mut self,
        profile_file: &Path,
        failure: File,
        correction: File,
    ) -> io::Result<Self> {
        if self.paired_training.is_some() {
            return Err(io::Error::other(
                "original paired training already configured",
            ));
        }
        self.paired_training = Some(self.service.prepare_original_paired_training(
            &self.config,
            &self.registration,
            &self.owner_pidfd,
            profile_file,
            failure,
            correction,
        )?);
        Ok(self)
    }

    /// Seal public pins only; the original listener and all live owners remain
    /// mandatory. Transfer uses a separate purpose and the same held Root pidfd.
    pub fn seal_paired_training_bootstrap(&self) -> io::Result<File> {
        let paired = self
            .paired_training
            .as_ref()
            .ok_or_else(|| io::Error::other("original paired training plan required"))?;
        self.service.seal_original_paired_training(
            &self.config,
            &self.registration,
            &self.owner_pidfd,
            paired,
        )
    }
}

pub(super) struct BoundPaired {
    owner: Option<RegisteredPairedTrainingPlan>,
    listener: UnixListener,
    path: PathBuf,
    device: u64,
    inode: u64,
}

impl BoundPaired {
    pub(super) fn bind(
        owner: RegisteredPairedTrainingPlan,
        config: &HostAuthorityServiceConfig,
        learning_path: Option<&Path>,
    ) -> io::Result<Self> {
        let mut paths: Vec<_> = validate_runtime_lanes(config)?
            .into_iter()
            .map(|(_, path)| path)
            .collect();
        paths.extend(learning_path);
        paths.push(&owner.socket_path);
        validate_lane_paths(&paths, config.peer_gid)?;
        let listener = UnixListener::bind(&owner.socket_path)?;
        let metadata = std::fs::symlink_metadata(&owner.socket_path)?;
        let bound = Self {
            path: owner.socket_path.clone(),
            owner: Some(owner),
            listener,
            device: metadata.dev(),
            inode: metadata.ino(),
        };
        if metadata.uid() != 0 || metadata.gid() != config.peer_gid {
            return Err(io::Error::other("paired socket custody mismatch"));
        }
        std::fs::set_permissions(&bound.path, std::fs::Permissions::from_mode(0o660))?;
        bound.listener.set_nonblocking(true)?;
        Ok(bound)
    }

    pub(super) fn path(&self) -> &Path {
        &self.path
    }
}

impl Drop for BoundPaired {
    fn drop(&mut self) {
        if std::fs::symlink_metadata(&self.path)
            .is_ok_and(|entry| entry.dev() == self.device && entry.ino() == self.inode)
        {
            let _ = std::fs::remove_file(&self.path);
        }
    }
}

struct StopPairedLane<'a> {
    stopping: &'a AtomicBool,
    active: &'a Mutex<Option<UnixStream>>,
}

impl Drop for StopPairedLane<'_> {
    fn drop(&mut self) {
        self.stopping.store(true, Ordering::Release);
        let held = self
            .active
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        if let Some(stream) = held.as_ref() {
            let _ = stream.shutdown(Shutdown::Both);
        }
    }
}

fn is_original_peer(stream: &UnixStream, peer: HostIssuerPeer, gid: u32) -> io::Result<bool> {
    let mut actual = libc::ucred {
        pid: 0,
        uid: 0,
        gid: 0,
    };
    let expected = std::mem::size_of_val(&actual) as libc::socklen_t;
    let mut length = expected;
    // SAFETY: the live stream and initialized credential/length buffers remain
    // borrowed for this one correctly sized SO_PEERCRED observation.
    let result = unsafe {
        libc::getsockopt(
            stream.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            (&mut actual as *mut libc::ucred).cast(),
            &mut length,
        )
    };
    if result != 0 {
        return Err(io::Error::last_os_error());
    }
    if length != expected || actual.pid <= 0 {
        return Err(io::Error::other(
            "paired peer credential size or PID invalid",
        ));
    }
    Ok(actual.uid == peer.uid && actual.gid == gid && actual.pid as u32 == peer.pid)
}

pub(super) fn serve_optional(
    paired: Option<BoundPaired>,
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    original_owner: &OwnedFd,
    original: impl FnOnce() -> io::Result<()>,
) -> io::Result<()> {
    let Some(mut paired) = paired else {
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
                owner_alive(original_owner, end)?;
                match paired.listener.accept() {
                    Ok((stream, _)) => {
                        if !is_original_peer(
                            &stream,
                            HostIssuerPeer {
                                uid: config.peer_uid,
                                pid: registration.peer_pid,
                            },
                            config.peer_gid,
                        )? {
                            continue;
                        }
                        verify_pinned_process(
                            registration,
                            config.peer_uid,
                            config.peer_gid,
                            original_owner,
                            end,
                        )?;
                        break stream;
                    }
                    Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                        std::thread::sleep(Duration::from_millis(5));
                    }
                    Err(error) => return Err(error),
                }
            };
            let owner = paired
                .owner
                .take()
                .ok_or_else(|| io::Error::other("paired listener already consumed"))?;
            {
                let mut held = active
                    .lock()
                    .map_err(|_| io::Error::other("paired lane poisoned"))?;
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
                    .ok_or_else(|| io::Error::other("original paired session expired"))?,
                request_bound: crate::paired_preparation::material_protocol::FRAME_BOUND,
                response_bound: crate::paired_preparation::material_protocol::FRAME_BOUND,
            };
            let result = service
                .serve_original_paired_training_plan(
                    owner.plan,
                    owner.failure,
                    owner.correction,
                    stream,
                    policy,
                    original_owner.try_clone()?,
                )
                .map_err(io::Error::other);
            if stopping.load(Ordering::Acquire) {
                Ok(())
            } else {
                result
            }
        });
        // This local drops before scope joins on both return and unwinding.
        let stop = StopPairedLane {
            stopping: &stopping,
            active: &active,
        };
        let result = original();
        drop(stop);
        let paired = worker
            .join()
            .map_err(|_| io::Error::other("paired lane panicked"))?;
        result.and(paired)
    })
}

#[cfg(test)]
#[path = "authority_host_paired_session_tests.rs"]
mod tests;
