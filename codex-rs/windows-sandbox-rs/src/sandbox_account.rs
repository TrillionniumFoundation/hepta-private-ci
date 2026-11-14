use crate::sandbox_account_witness::LeaseClosedEvent;
use crate::sandbox_account_witness::SandboxAccountLeaseWitness;
use anyhow::Context;
use anyhow::Result;
use std::io;
use std::marker::PhantomData;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::rc::Rc;
use std::sync::mpsc;
use std::thread;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::WAIT_ABANDONED;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::System::Threading::CreateMutexW;
use windows_sys::Win32::System::Threading::INFINITE;
use windows_sys::Win32::System::Threading::ReleaseMutex;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

// Every CODEX_HOME provisions the same machine accounts. A per-home or
// process-local lock cannot protect credentials from another launch's rotation.
const ACCOUNT_MUTEX_NAME: &str = "Global\\CodexSandboxAccountLifecycleV1";
pub(crate) const SETUP_MUTATION_MUTEX_NAME: &str = "Global\\CodexSandboxAccountMutationV1";

/// Keeps setup, credential refresh and runner logon in one machine-wide lease.
///
/// The dedicated thread owns the Windows mutex until this movable guard drops.
/// This permits the caller's async/blocking handoff without releasing a mutex
/// from a different thread. Kernel abandonment recovers a crashed owner; the
/// next owner still reloads and validates credentials before launching a runner.
pub(crate) struct SandboxAccountLease {
    release: Option<mpsc::Sender<()>>,
    owner: Option<thread::JoinHandle<()>>,
    witness: SandboxAccountLeaseWitness,
}

impl SandboxAccountLease {
    pub(crate) fn acquire() -> Result<Self> {
        let (ready_tx, ready_rx) = mpsc::sync_channel(1);
        let (release_tx, release_rx) = mpsc::channel();
        let owner = thread::Builder::new()
            .name("codex-sandbox-account".to_string())
            .spawn(move || {
                let acquired = (|| -> Result<_> {
                    let lifecycle = AccountMutex::acquire(ACCOUNT_MUTEX_NAME)?;
                    // A helper may survive its parent process. Drain mutations
                    // before reading credentials; late helpers recheck a closed
                    // event and parent identity while holding this same mutex.
                    drop(AccountMutex::acquire(SETUP_MUTATION_MUTEX_NAME)?);
                    let closed_event = LeaseClosedEvent::create()?;
                    Ok((lifecycle, closed_event))
                })();
                let (guard, closed_event) = match acquired {
                    Ok(value) => value,
                    Err(error) => {
                        let _ = ready_tx.send(Err(error));
                        return;
                    }
                };
                if ready_tx.send(Ok(closed_event.witness())).is_ok() {
                    // A closed channel also releases the lease on unwind.
                    let _ = release_rx.recv();
                }
                drop(closed_event);
                drop(guard);
            })
            .context("start sandbox account lease owner")?;
        let ready = ready_rx
            .recv()
            .context("sandbox account lease owner stopped before acquisition")
            .and_then(|result| result.context("acquire machine sandbox account lease"));
        match ready {
            Ok(witness) => Ok(Self {
                release: Some(release_tx),
                owner: Some(owner),
                witness,
            }),
            Err(error) => {
                drop(release_tx);
                let _ = owner.join();
                Err(error)
            }
        }
    }

    pub(crate) fn witness(&self) -> SandboxAccountLeaseWitness {
        self.witness.clone()
    }
}

impl Drop for SandboxAccountLease {
    fn drop(&mut self) {
        drop(self.release.take());
        if let Some(owner) = self.owner.take()
            && owner.join().is_err()
        {
            crate::logging::debug_log("sandbox account lease owner panicked", None);
        }
    }
}

pub(crate) struct AccountMutex(OwnedHandle, PhantomData<Rc<()>>);

impl AccountMutex {
    pub(crate) fn acquire(name: &str) -> io::Result<Self> {
        let name = crate::winutil::to_wide(name);
        // A preexisting inaccessible mutex is an error, never an unlocked fallback.
        let handle = unsafe {
            CreateMutexW(std::ptr::null(), /*binitialowner*/ 0, name.as_ptr())
        };
        if handle == 0 {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: CreateMutexW returned a new owned handle.
        let handle = unsafe { OwnedHandle::from_raw_handle(handle as _) };
        match unsafe { WaitForSingleObject(handle.as_raw_handle() as HANDLE, INFINITE) } {
            WAIT_OBJECT_0 | WAIT_ABANDONED => Ok(Self(handle, PhantomData)),
            _ => Err(io::Error::last_os_error()),
        }
    }
}

impl Drop for AccountMutex {
    fn drop(&mut self) {
        // This value stays on the exact thread that acquired the mutex.
        if unsafe { ReleaseMutex(self.0.as_raw_handle() as HANDLE) } == 0 {
            crate::logging::debug_log(
                &format!(
                    "release sandbox account lease failed: {}",
                    io::Error::last_os_error()
                ),
                None,
            );
        }
    }
}

#[cfg(test)]
#[path = "sandbox_account_tests.rs"]
mod tests;
