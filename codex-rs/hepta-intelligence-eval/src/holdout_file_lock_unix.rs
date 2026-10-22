use super::*;
use std::collections::BTreeMap;
use std::os::unix::fs::MetadataExt;
use std::sync::Mutex;
use std::sync::atomic::AtomicU32;
use std::sync::atomic::Ordering;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct Identity(u64, u64);

#[derive(Clone, Copy)]
pub(super) struct Lease {
    identity: Identity,
    nonce: u64,
    pid: u32,
}

struct Registry {
    leases: BTreeMap<Identity, u64>,
    next_nonce: u64,
}

impl Registry {
    const fn new() -> Self {
        Self {
            leases: BTreeMap::new(),
            next_nonce: 0,
        }
    }

    fn reserve(&mut self, identity: Identity, pid: u32) -> Result<Lease, TryLockError> {
        if self.leases.contains_key(&identity) {
            return Err(TryLockError::WouldBlock);
        }
        let nonce = self
            .next_nonce
            .checked_add(1)
            .ok_or_else(|| TryLockError::Error(io::Error::other("holdout lock lease exhausted")))?;
        self.next_nonce = nonce;
        self.leases.insert(identity, nonce);
        Ok(Lease {
            identity,
            nonce,
            pid,
        })
    }

    // Keeping a failed release registered quarantines this identity. Never
    // make a new owner eligible before the old OS lock is known released.
    fn release(&mut self, lease: Lease, unlock: impl FnOnce() -> io::Result<()>) {
        if self.leases.get(&lease.identity) == Some(&lease.nonce) && unlock().is_ok() {
            self.leases.remove(&lease.identity);
        }
    }
}

static ORIGIN: AtomicU32 = AtomicU32::new(0);
static REGISTRY: Mutex<Registry> = Mutex::new(Registry::new());

fn check_origin(origin: &AtomicU32, pid: u32) -> io::Result<()> {
    match origin.compare_exchange(0, pid, Ordering::Relaxed, Ordering::Relaxed) {
        Ok(_) => Ok(()),
        Err(owner) if owner == pid => Ok(()),
        Err(_) => Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "holdout locks require exec before use in an inherited process",
        )),
    }
}

pub(super) fn acquire(file: File) -> Result<AcquiredFile, TryLockError> {
    let pid = std::process::id();
    // This gate must precede metadata work and especially every access to
    // the mutex: fork can inherit it while another parent thread holds it.
    check_origin(&ORIGIN, pid).map_err(TryLockError::Error)?;
    let metadata = file.metadata().map_err(TryLockError::Error)?;
    let identity = Identity(metadata.dev(), metadata.ino());
    let mut registry = REGISTRY
        .lock()
        .map_err(|_| TryLockError::Error(io::Error::other("holdout lock registry poisoned")))?;
    let lease = registry.reserve(identity, pid)?;
    // All allocation/reservation precedes the syscall. A successful lock
    // is immediately represented by this guard, before any fallible I/O.
    let mut acquired = AcquiredFile { file, lease: None };
    match acquired.file.try_lock() {
        Ok(()) => acquired.lease = Some(lease),
        Err(error) => {
            registry.leases.remove(&identity);
            return Err(error);
        }
    }
    Ok(acquired)
}

pub(super) fn check(lease: Lease) -> io::Result<()> {
    if lease.pid != std::process::id() {
        return Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "inherited holdout owner",
        ));
    }
    Ok(())
}

pub(super) fn release(file: &File, lease: Lease) {
    release_registered(&REGISTRY, file, lease);
}

fn release_registered(registry: &Mutex<Registry>, file: &File, lease: Lease) {
    // Never touch an inherited mutex, or unlock a parent's shared OFD.
    if check(lease).is_err() {
        return;
    }
    // Poison is fail-closed: preserve reservations, close only, no panic.
    if let Ok(mut registry) = registry.lock() {
        registry.release(lease, || file.unlock());
    }
}

#[cfg(test)]
#[path = "holdout_file_lock_registry_tests.rs"]
mod tests;
