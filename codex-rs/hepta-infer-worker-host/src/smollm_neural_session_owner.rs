//! Two original-supervisor custodians, born before any model process.
//! Slot availability is never model completion, WholeU or resource-return proof.

use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::panic::AssertUnwindSafe;
use std::process::Child;
use std::process::Command;
use std::process::ExitStatus;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;
use std::sync::OnceLock;
use std::sync::TryLockError;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicI32;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::thread::Thread;
use std::time::Duration;
use std::time::Instant;

use tokio_util::sync::CancellationToken;

const CAPACITY: usize = 2;
const STACK_BYTES: usize = 1024 * 1024;
const ROOT_LOCK_ATTEMPTS: usize = 256;
static OWNERS: Mutex<[Option<Arc<Slot>>; CAPACITY]> = Mutex::new([const { None }; CAPACITY]);

fn reserve_roots(
    deadline: Instant,
    cancellation: &CancellationToken,
) -> Result<MutexGuard<'static, [Option<Arc<Slot>>; CAPACITY]>, String> {
    for _ in 0..ROOT_LOCK_ATTEMPTS {
        if cancellation.is_cancelled() || Instant::now() >= deadline {
            return Err("neural reaper preparation exceeded original startup".to_owned());
        }
        match OWNERS.try_lock() {
            Ok(roots) => {
                if cancellation.is_cancelled() || Instant::now() >= deadline {
                    return Err("neural reaper preparation exceeded original startup".to_owned());
                }
                return Ok(roots);
            }
            Err(TryLockError::Poisoned(_)) => {
                return Err("neural owner roots busy or poisoned".to_owned());
            }
            Err(TryLockError::WouldBlock) => {
                std::thread::park_timeout(
                    Duration::from_millis(1)
                        .min(deadline.saturating_duration_since(Instant::now())),
                );
            }
        }
    }
    Err("neural owner roots busy or poisoned".to_owned())
}

struct Lease {
    origin: Instant,
    cutoff_ns: AtomicU64,
    requested: AtomicBool,
}

impl Lease {
    fn cutoff(&self) -> Instant {
        self.origin + Duration::from_nanos(self.cutoff_ns.load(Ordering::Acquire))
    }
}

struct Payload {
    directory: Arc<File>,
    child: Option<Child>,
    lease: Arc<Lease>,
}

#[repr(u8)]
#[derive(Clone, Copy)]
enum Failure {
    None,
    ThreadCreate,
    ThreadPanic,
    ReadinessExpired,
    CleanupIo,
    CleanupPanic,
}

struct Slot {
    pid: u32,
    payload: Mutex<Option<Payload>>,
    generation: AtomicU64,
    ready: AtomicBool,
    failure: AtomicU8,
    os_error: AtomicI32,
    thread: OnceLock<Thread>,
    #[cfg(test)]
    panic_cleanup: AtomicBool,
}

pub(super) struct SupervisorOwner {
    slot: Arc<Slot>,
    generation: u64,
    lease: Arc<Lease>,
    startup_deadline: Instant,
    cancellation: CancellationToken,
}

impl SupervisorOwner {
    pub(super) fn prepare(
        directory: File,
        deadline: Instant,
        cancellation: &CancellationToken,
    ) -> Result<Self, String> {
        if cancellation.is_cancelled() || Instant::now() >= deadline {
            return Err("neural reaper preparation exceeded original startup".to_owned());
        }
        let lease = Arc::new(Lease {
            origin: Instant::now(),
            cutoff_ns: AtomicU64::new(super::SUPERVISOR_WALL_SECONDS * 1_000_000_000),
            requested: AtomicBool::new(false),
        });
        let mut roots = reserve_roots(deadline, cancellation)?;
        let mut fresh = false;
        let mut chosen = None;
        for entry in roots.iter_mut() {
            if let Some(slot) = entry {
                if slot.pid != std::process::id()
                    || slot.failure.load(Ordering::Acquire) != Failure::None as u8
                {
                    continue;
                }
                if let Ok(mut payload) = slot.payload.try_lock()
                    && payload.is_none()
                    && let Some(generation) = slot.generation.load(Ordering::Acquire).checked_add(1)
                {
                    slot.generation.store(generation, Ordering::Release);
                    *payload = Some(Payload {
                        directory: Arc::new(directory),
                        child: None,
                        lease: Arc::clone(&lease),
                    });
                    chosen = Some((Arc::clone(slot), generation));
                    break;
                }
            } else {
                let slot = Arc::new(Slot {
                    pid: std::process::id(),
                    payload: Mutex::new(Some(Payload {
                        directory: Arc::new(directory),
                        child: None,
                        lease: Arc::clone(&lease),
                    })),
                    generation: AtomicU64::new(1),
                    ready: AtomicBool::new(false),
                    failure: AtomicU8::new(Failure::None as u8),
                    os_error: AtomicI32::new(0),
                    thread: OnceLock::new(),
                    #[cfg(test)]
                    panic_cleanup: AtomicBool::new(false),
                });
                *entry = Some(Arc::clone(&slot)); // Strong root before thread creation.
                chosen = Some((slot, 1));
                fresh = true;
                break;
            }
        }
        drop(roots);
        let (slot, generation) = chosen.ok_or("neural supervisor owner capacity busy")?;
        let owner = Self {
            slot,
            generation,
            lease,
            startup_deadline: deadline,
            cancellation: cancellation.clone(),
        };
        if fresh {
            let start = std::panic::catch_unwind(AssertUnwindSafe(|| {
                #[cfg(test)]
                match REQUEST_FAILURE.get() {
                    1 => return Err(io::Error::from_raw_os_error(libc::EAGAIN)),
                    2 => panic!("controlled prebirth reaper request panic"),
                    _ => {}
                }
                let runtime = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()?;
                let slot = Arc::clone(&owner.slot);
                #[cfg(test)]
                let delay_ready = REQUEST_FAILURE.get() == 3;
                std::thread::Builder::new()
                    .name("hepta-model-custodian".to_owned())
                    .stack_size(STACK_BYTES)
                    .spawn(move || {
                        #[cfg(test)]
                        if delay_ready {
                            std::thread::sleep(Duration::from_millis(100));
                        }
                        run(slot, runtime)
                    })
            }));
            match start {
                Ok(Ok(handle)) => {
                    let _ = owner.slot.thread.set(handle.thread().clone());
                }
                Ok(Err(error)) => {
                    owner
                        .slot
                        .os_error
                        .store(error.raw_os_error().unwrap_or(0), Ordering::Release);
                    owner
                        .slot
                        .failure
                        .store(Failure::ThreadCreate as u8, Ordering::Release);
                    return Err("neural reaper thread unavailable before process birth".to_owned());
                }
                Err(_) => {
                    owner
                        .slot
                        .failure
                        .store(Failure::ThreadPanic as u8, Ordering::Release);
                    return Err("neural reaper request panicked before process birth".to_owned());
                }
            }
        }
        while !owner.slot.ready.load(Ordering::Acquire) {
            if cancellation.is_cancelled() || Instant::now() >= deadline {
                owner
                    .slot
                    .failure
                    .store(Failure::ReadinessExpired as u8, Ordering::Release);
                return Err("neural reaper readiness exceeded original startup".to_owned());
            }
            std::thread::sleep(Duration::from_millis(1));
        }
        Ok(owner)
    }

    fn payload(&self) -> Result<MutexGuard<'_, Option<Payload>>, String> {
        if self.slot.pid != std::process::id()
            || self.slot.generation.load(Ordering::Acquire) != self.generation
        {
            return Err("neural original supervisor owner differs".to_owned());
        }
        // Cleanup can wait for the original supervisor. A foreground operation
        // must never wait for that lock past its original execution deadline.
        let payload = self
            .slot
            .payload
            .try_lock()
            .map_err(|_| "neural supervisor owner busy or poisoned")?;
        if self.slot.generation.load(Ordering::Acquire) != self.generation {
            return Err("neural original supervisor owner differs".to_owned());
        }
        Ok(payload)
    }

    fn with_child<T>(
        &self,
        use_child: impl FnOnce(&mut Child) -> io::Result<T>,
    ) -> Result<T, String> {
        let mut payload = self.payload()?;
        let child = payload
            .as_mut()
            .and_then(|value| value.child.as_mut())
            .ok_or("neural supervisor missing")?;
        use_child(child).map_err(|error| error.to_string())
    }

    pub(super) fn directory(&self) -> Result<Arc<File>, String> {
        self.payload()?
            .as_ref()
            .map(|value| Arc::clone(&value.directory))
            .ok_or_else(|| "neural owner directory missing".to_owned())
    }

    pub(super) fn spawn(&self, command: &mut Command) -> Result<(), String> {
        let mut payload = self.payload()?;
        if self.cancellation.is_cancelled()
            || Instant::now() >= self.startup_deadline
            || !self.slot.ready.load(Ordering::Acquire)
            || self.slot.failure.load(Ordering::Acquire) != Failure::None as u8
            || self.lease.requested.load(Ordering::Acquire)
        {
            return Err("neural original custodian is unavailable".to_owned());
        }
        let payload = payload.as_mut().ok_or("neural owner reservation missing")?;
        if payload.child.is_some() {
            return Err("neural supervisor already born".to_owned());
        }
        // No fallible work between the returned original Child and its rooted slot.
        payload.child = Some(command.spawn().map_err(|error| error.to_string())?);
        Ok(())
    }

    pub(super) fn try_wait(&self) -> Result<Option<ExitStatus>, String> {
        self.with_child(Child::try_wait)
    }

    pub(super) fn cutoff(&self) -> Instant {
        self.lease.cutoff()
    }

    pub(super) fn release_verified_terminal(&self) -> Result<(), String> {
        let mut payload = self.payload()?;
        let child = payload
            .as_mut()
            .and_then(|value| value.child.as_mut())
            .ok_or("neural supervisor missing")?;
        if child
            .try_wait()
            .map_err(|error| error.to_string())?
            .is_none()
        {
            return Err("neural supervisor remains live".to_owned());
        }
        payload.take(); // Only after Session's original successful receipt checks.
        Ok(())
    }

    pub(super) fn request_cleanup(&self, cutoff: Instant) {
        if self.slot.pid != std::process::id() {
            return;
        }
        let nanos = cutoff
            .saturating_duration_since(self.lease.origin)
            .as_nanos();
        let nanos = u64::try_from(nanos).unwrap_or(u64::MAX);
        // Each reservation retains its own lease. A stale owner's Drop cannot
        // change a successor's cutoff, request bit or original Child.
        self.lease.cutoff_ns.fetch_min(nanos, Ordering::AcqRel);
        self.lease.requested.store(true, Ordering::Release);
        if let Some(thread) = self.slot.thread.get() {
            thread.unpark();
        }
    }
}

impl Drop for SupervisorOwner {
    fn drop(&mut self) {
        self.request_cleanup(self.cutoff());
    }
}

#[cfg(test)]
impl SupervisorOwner {
    pub(super) fn wait(&self) -> Result<ExitStatus, String> {
        self.with_child(Child::wait)
    }
    pub(super) fn id(&self) -> u32 {
        self.with_child(|child| Ok(child.id())).unwrap()
    }
    pub(super) fn take_stdin(&self) -> Option<std::process::ChildStdin> {
        self.with_child(|child| Ok(child.stdin.take())).unwrap()
    }
    pub(super) fn is_some(&self) -> bool {
        self.with_child(|_| Ok(())).is_ok()
    }
}

fn run(slot: Arc<Slot>, runtime: tokio::runtime::Runtime) {
    let _ = slot.thread.set(std::thread::current());
    slot.ready.store(true, Ordering::Release);
    loop {
        std::thread::park();
        if slot.failure.load(Ordering::Acquire) != Failure::None as u8 {
            loop {
                std::thread::park();
            }
        }
        // The root/payload stay outside the unwind boundary. Even a panic in
        // cleanup cannot move or drop the original Child out of its fixed slot.
        match std::panic::catch_unwind(AssertUnwindSafe(|| cleanup(&slot, &runtime))) {
            Ok(Ok(())) => {}
            Ok(Err(error)) => {
                slot.os_error
                    .store(error.raw_os_error().unwrap_or(0), Ordering::Release);
                slot.failure
                    .store(Failure::CleanupIo as u8, Ordering::Release);
            }
            Err(_) => {
                slot.failure
                    .store(Failure::CleanupPanic as u8, Ordering::Release);
            }
        }
        if slot.failure.load(Ordering::Acquire) != Failure::None as u8 {
            loop {
                std::thread::park();
            }
        }
    }
}

fn cleanup(slot: &Slot, runtime: &tokio::runtime::Runtime) -> io::Result<()> {
    use tokio::io::AsyncWriteExt;

    let mut guard = slot
        .payload
        .lock()
        .map_err(|_| io::Error::other("neural supervisor owner poisoned"))?;
    if !guard
        .as_ref()
        .is_some_and(|payload| payload.lease.requested.load(Ordering::Acquire))
    {
        return Ok(());
    }
    #[cfg(test)]
    assert!(
        !slot.panic_cleanup.swap(false, Ordering::SeqCst),
        "controlled cleanup panic with original owner rooted"
    );
    if let Some(payload) = guard.as_mut()
        && let Some(child) = payload.child.as_mut()
    {
        let socket = format!(
            "/proc/self/fd/{}/session/worker/model.sock",
            payload.directory.as_raw_fd()
        );
        runtime.block_on(async {
            loop {
                if child.try_wait()?.is_some() {
                    break;
                }
                let remaining = payload
                    .lease
                    .cutoff()
                    .saturating_duration_since(Instant::now());
                if remaining.is_zero() {
                    break;
                }
                let stop = async {
                    let mut connection = tokio::net::UnixStream::connect(&socket).await?;
                    connection.write_all(super::STOP).await
                };
                if matches!(
                    tokio::time::timeout(remaining.min(Duration::from_millis(250)), stop).await,
                    Ok(Ok(()))
                ) {
                    break;
                }
                tokio::time::sleep(
                    payload
                        .lease
                        .cutoff()
                        .saturating_duration_since(Instant::now())
                        .min(Duration::from_millis(20)),
                )
                .await;
            }
            Ok::<(), io::Error>(())
        })?;
        let status = child.wait()?;
        super::verify_terminal_receipt(&payload.directory, Some(status))
            .map_err(io::Error::other)?;
    }
    guard.take(); // Exact supervisor custody only; never a model/WholeU receipt.
    Ok(())
}

#[cfg(test)]
thread_local! { static REQUEST_FAILURE: std::cell::Cell<u8> = const { std::cell::Cell::new(0) }; }

#[cfg(test)]
#[path = "smollm_neural_session_owner_tests.rs"]
mod tests;
