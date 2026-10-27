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
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

#[path = "authority_host_admin_protocol.rs"]
mod protocol;
pub use protocol::*;

#[path = "authority_host_admin_deadline.rs"]
pub(crate) mod deadline;
pub(crate) use deadline::checked_step;

const PREPARED: u8 = 0;
const SERVING: u8 = 1;
const CLOSED: u8 = 2;

struct Lifetime {
    phase: AtomicU8,
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
    pub fn exchange(&self, raw: &[u8], before: Instant) -> io::Result<Vec<u8>> {
        actual_root()?;
        let request = decode(raw)?;
        let life = self.request_lifetime(&request)?;
        self.instance.verify_current()?;
        let end = before.min(Instant::now() + self.timeout);
        let remaining = end
            .checked_duration_since(Instant::now())
            .filter(|left| !left.is_zero())
            .ok_or_else(ended)?;
        let (reply, receive) = mpsc::sync_channel(1);
        self.sender
            .try_send(Pending {
                request,
                end,
                reply,
            })
            .map_err(|_| io::Error::other("original Root admin is busy or ended"))?;
        let result = receive.recv_timeout(remaining).map_err(|_| {
            io::Error::other("original Root admin outcome unavailable; never retry a mutation")
        })??;
        if life.phase.load(Ordering::Acquire) != SERVING || Instant::now() >= end {
            return Err(ended());
        }
        self.instance.verify_current()?;
        Ok(result)
    }

    fn request_lifetime(&self, request: &RootAdminRequest) -> io::Result<Arc<Lifetime>> {
        let life = self.lifetime.upgrade().ok_or_else(ended)?;
        if life.phase.load(Ordering::Acquire) != SERVING
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
            phase: AtomicU8::new(PREPARED),
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

    pub(crate) fn activate(&self) -> io::Result<()> {
        self.life
            .phase
            .compare_exchange(PREPARED, SERVING, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| ended())?;
        Ok(())
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
        if self.life.phase.load(Ordering::Acquire) == CLOSED {
            return Err(ended());
        }
        let stopping = AtomicBool::new(false);
        std::thread::scope(|scope| {
            let worker = scope.spawn(|| {
                let _worker_guard = Stop(&self.life, &stopping);
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
            let guard = Stop(&self.life, &stopping);
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
        let context = LiveRootAdminRequest {
            life: &self.life,
            expected: &pending.request.expected_instance,
            service,
            config,
            registration,
            owner,
            end: pending.end,
        };
        let response = checked_step(
            pending.end,
            || context.check_for(service),
            || service.admin_request(&context, &pending.request.action),
        )?;
        context.check_for(service)?;
        let raw = serde_json::to_vec(&response).map_err(io::Error::other)?;
        if raw.len() > ROOT_ADMIN_FRAME_BOUND {
            return Err(io::Error::other("original Root admin response bound"));
        }
        deadline::require_before(pending.end)?;
        Ok(raw)
    }
}

impl Drop for RootAdminRuntime {
    fn drop(&mut self) {
        self.life.phase.store(CLOSED, Ordering::Release);
    }
}

struct Stop<'a>(&'a Lifetime, &'a AtomicBool);
impl Drop for Stop<'_> {
    fn drop(&mut self) {
        self.0.phase.store(CLOSED, Ordering::Release);
        self.1.store(true, Ordering::Release);
    }
}

/// Borrowed only inside the original scoped worker. No outside constructor,
/// object/FD getter, serialization or ownership extension is available.
pub(crate) struct LiveRootAdminRequest<'a> {
    life: &'a Lifetime,
    expected: &'a RootAdminInstance,
    service: &'a HostAuthorityService,
    config: &'a HostAuthorityServiceConfig,
    registration: &'a HostAuthorityRegistration,
    owner: &'a OwnedFd,
    end: Instant,
}

impl LiveRootAdminRequest<'_> {
    pub(crate) fn before(&self) -> Instant {
        self.end
    }

    pub(crate) fn instance(&self) -> &RootAdminInstance {
        &self.life.instance
    }

    pub(crate) fn check_for(&self, service: &HostAuthorityService) -> io::Result<()> {
        actual_root()?;
        deadline::require_before(self.end)?;
        if !std::ptr::eq(service, self.service)
            || self.life.phase.load(Ordering::Acquire) != SERVING
            || self.expected != &self.life.instance
        {
            return Err(ended());
        }
        self.life.instance.verify_current()?;
        verify_pinned_process(
            self.registration,
            self.config.peer_uid,
            self.config.peer_gid,
            self.owner,
            self.end,
        )?;
        service.check_admin_lifetime(self.end)?;
        deadline::require_before(self.end)
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
