//! Full-facade administration of a borrowed SAME live Root service.
//! The capability has no Root objects/FDs and cannot keep their owner alive.
use crate::HostAuthorityRegistration;
use crate::HostAuthorityService;
use crate::HostAuthorityServiceConfig;
use crate::authority_host_runtime::verify_pinned_process;
use std::io;
use std::io::Read;
use std::os::fd::OwnedFd;
use std::sync::Arc;
use std::sync::Weak;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

#[path = "authority_host_admin_protocol.rs"]
mod protocol;
pub use protocol::*;

struct Lifetime {
    serving: AtomicBool,
    instance: RootAdminInstance,
}

struct Pending {
    request: RootAdminRequest,
    end: Instant,
    reply: mpsc::SyncSender<io::Result<Vec<u8>>>,
}

/// Opaque, non-cloneable route into one borrowed original service. Only that
/// Prepared instance can mint it; no path, object, Arc or FD can be extracted.
pub struct RootAdminCapability {
    lifetime: Weak<Lifetime>,
    sender: mpsc::SyncSender<Pending>,
    instance: RootAdminInstance,
    timeout: Duration,
}

impl RootAdminCapability {
    /// Observation only. This public tuple cannot construct another capability.
    pub fn instance(&self) -> &RootAdminInstance {
        &self.instance
    }

    /// One bounded request, with no retries. A timeout after a mutation remains
    /// unknown; the caller must observe the original registry, never resend.
    pub fn exchange(&self, raw: &[u8]) -> io::Result<Vec<u8>> {
        actual_root()?;
        let request = decode(raw)?;
        let life = self.request_lifetime(&request)?;
        self.instance.verify_current()?;
        let end = Instant::now() + self.timeout;
        let (reply, receive) = mpsc::sync_channel(1);
        self.sender
            .try_send(Pending {
                request,
                end,
                reply,
            })
            .map_err(|_| io::Error::other("original Root admin is busy or ended"))?;
        let result = receive.recv_timeout(self.timeout).map_err(|_| {
            io::Error::other("original Root admin outcome unavailable; never retry a mutation")
        })??;
        if !life.serving.load(Ordering::Acquire) || Instant::now() >= end {
            return Err(ended());
        }
        self.instance.verify_current()?;
        Ok(result)
    }

    fn request_lifetime(&self, request: &RootAdminRequest) -> io::Result<Arc<Lifetime>> {
        let life = self.lifetime.upgrade().ok_or_else(ended)?;
        if !life.serving.load(Ordering::Acquire)
            || request.expected_instance != self.instance
            || life.instance != self.instance
        {
            return Err(ended());
        }
        Ok(life)
    }
}

pub(crate) struct RootAdminRuntime {
    life: Arc<Lifetime>,
    receiver: std::sync::Mutex<mpsc::Receiver<Pending>>,
}

impl RootAdminRuntime {
    pub(crate) fn mint(timeout: Duration) -> io::Result<(Self, RootAdminCapability)> {
        actual_root()?;
        let mut instance = RootAdminInstance::current()?;
        std::fs::File::open("/dev/urandom")?.read_exact(&mut instance.episode_nonce)?;
        if instance.episode_nonce == [0; 32] || timeout.is_zero() {
            return Err(ended());
        }
        let life = Arc::new(Lifetime {
            serving: AtomicBool::new(false),
            instance: instance.clone(),
        });
        let (sender, receiver) = mpsc::sync_channel(1);
        let capability = RootAdminCapability {
            lifetime: Arc::downgrade(&life),
            sender,
            instance,
            timeout,
        };
        Ok((
            Self {
                life,
                receiver: std::sync::Mutex::new(receiver),
            },
            capability,
        ))
    }

    pub(crate) fn activate(&self) {
        self.life.serving.store(true, Ordering::Release);
    }

    /// The scoped worker borrows all original objects. The capability owns
    /// none, and this closure cannot return until the worker is invalidated.
    pub(crate) fn run(
        &self,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        serve: impl FnOnce() -> io::Result<()>,
    ) -> io::Result<()> {
        let stopping = AtomicBool::new(false);
        std::thread::scope(|scope| {
            let worker = scope.spawn(|| {
                let receiver = self
                    .receiver
                    .lock()
                    .map_err(|_| io::Error::other("original Root admin receiver poisoned"))?;
                while !stopping.load(Ordering::Acquire) {
                    match receiver.recv_timeout(Duration::from_millis(10)) {
                        Ok(pending) => {
                            let result =
                                self.handle(service, config, registration, owner, &pending);
                            let _ = pending.reply.try_send(result);
                        }
                        Err(mpsc::RecvTimeoutError::Timeout) => {}
                        Err(mpsc::RecvTimeoutError::Disconnected) => break,
                    }
                }
                Ok::<(), io::Error>(())
            });
            struct Stop<'a>(&'a AtomicBool, &'a AtomicBool);
            impl Drop for Stop<'_> {
                fn drop(&mut self) {
                    self.0.store(false, Ordering::Release);
                    self.1.store(true, Ordering::Release);
                }
            }
            let guard = Stop(&self.life.serving, &stopping);
            let result = serve();
            drop(guard);
            worker
                .join()
                .map_err(|_| io::Error::other("original Root admin worker panicked"))??;
            result
        })
    }

    fn handle(
        &self,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        pending: &Pending,
    ) -> io::Result<Vec<u8>> {
        let check = || {
            actual_root()?;
            self.life.instance.verify_current()?;
            if !self.life.serving.load(Ordering::Acquire)
                || pending.request.expected_instance != self.life.instance
                || Instant::now() >= pending.end
            {
                return Err(ended());
            }
            verify_pinned_process(
                registration,
                config.peer_uid,
                config.peer_gid,
                owner,
                pending.end,
            )?;
            service.check_admin_lifetime()
        };
        check()?;
        let response = service.admin_request(&self.life.instance, &pending.request.action)?;
        check()?;
        let raw = serde_json::to_vec(&response).map_err(io::Error::other)?;
        if raw.len() > ROOT_ADMIN_FRAME_BOUND {
            return Err(io::Error::other("original Root admin response bound"));
        }
        Ok(raw)
    }
}

impl Drop for RootAdminRuntime {
    fn drop(&mut self) {
        self.life.serving.store(false, Ordering::Release);
    }
}

impl RootAdminInstance {
    fn current() -> io::Result<Self> {
        let stat = std::fs::read_to_string("/proc/self/stat")?;
        let start = stat
            .rsplit_once(") ")
            .and_then(|(_, fields)| fields.split_whitespace().nth(19))
            .and_then(|value| value.parse().ok())
            .filter(|value| *value > 0)
            .ok_or_else(ended)?;
        Ok(Self {
            boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
                .trim()
                .to_owned(),
            root_pid: std::process::id(),
            process_start_ticks: start,
            episode_nonce: [0; 32],
        })
    }

    fn verify_current(&self) -> io::Result<()> {
        let mut current = Self::current()?;
        current.episode_nonce = self.episode_nonce;
        if current != *self || self.episode_nonce == [0; 32] {
            return Err(ended());
        }
        Ok(())
    }
}

fn decode(raw: &[u8]) -> io::Result<RootAdminRequest> {
    if raw.is_empty() || raw.len() > ROOT_ADMIN_FRAME_BOUND {
        return Err(io::Error::other("original Root admin request bound"));
    }
    let request: RootAdminRequest = serde_json::from_slice(raw).map_err(io::Error::other)?;
    if request.schema_version != 1 {
        return Err(ended());
    }
    Ok(request)
}

fn actual_root() -> io::Result<()> {
    // SAFETY: credential observations have no borrowed memory.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "actual original Root required",
        ));
    }
    Ok(())
}

fn ended() -> io::Error {
    io::Error::other("original Root admin instance is not live")
}

#[cfg(test)]
#[path = "authority_host_admin_tests.rs"]
mod tests;
