use std::io;
#[cfg(windows)]
use std::sync::Arc;
use std::sync::Mutex;
#[cfg(windows)]
use std::sync::OnceLock;

use crate::ProcessCleanupObservation;
use crate::direct_custody::RetainedChild;

/// Keeps the original Tokio child after the task observing it is cancelled or fails.
pub(crate) struct AsyncChild {
    pub(crate) child: tokio::sync::Mutex<tokio::process::Child>,
    #[cfg(windows)]
    original: OnceLock<Arc<std::os::windows::io::OwnedHandle>>,
}

impl AsyncChild {
    pub(crate) fn new(child: tokio::process::Child) -> Self {
        Self {
            child: tokio::sync::Mutex::new(child),
            #[cfg(windows)]
            original: OnceLock::new(),
        }
    }

    pub(crate) async fn wait(&self) -> io::Result<std::process::ExitStatus> {
        self.child.lock().await.wait().await
    }

    #[cfg(windows)]
    pub(crate) fn retain_original_handle(
        &self,
        handle: std::os::windows::io::BorrowedHandle<'_>,
    ) -> io::Result<Arc<std::os::windows::io::OwnedHandle>> {
        let handle = Arc::new(handle.try_clone_to_owned()?);
        self.original
            .set(Arc::clone(&handle))
            .map_err(|_| io::Error::other("original direct process handle already retained"))?;
        Ok(handle)
    }
}

impl RetainedChild for AsyncChild {
    fn observe_cleanup(&self) -> io::Result<ProcessCleanupObservation> {
        #[cfg(windows)]
        {
            use std::os::windows::io::AsHandle;
            use std::os::windows::io::BorrowedHandle;
            if let Some(handle) = self.original.get() {
                return observe_windows_handle(handle.as_handle());
            }
            // A duplicate may have failed after spawn. The original Child is
            // still retained; borrowing its handle does not reopen a PID.
            let Ok(child) = self.child.try_lock() else {
                return Ok(ProcessCleanupObservation::NoTerminalObservation);
            };
            let handle = child
                .raw_handle()
                .ok_or_else(|| io::Error::other("original direct process handle unavailable"))?;
            // The child guard keeps the source handle alive for this query.
            observe_windows_handle(unsafe { BorrowedHandle::borrow_raw(handle) })
        }
        #[cfg(not(windows))]
        {
            // Child/PID ownership can no longer be reconstructed after a wait
            // error. Do not query or signal a potentially reused numeric PID.
            Ok(ProcessCleanupObservation::NoTerminalObservation)
        }
    }
}

/// Keeps the actual portable child, including the project ConPTY implementation.
pub(crate) struct PortableChild {
    pub(crate) child: Mutex<Box<dyn portable_pty::Child + Send + Sync>>,
    #[cfg(windows)]
    original: OnceLock<Arc<std::os::windows::io::OwnedHandle>>,
}

impl PortableChild {
    pub(crate) fn new(child: Box<dyn portable_pty::Child + Send + Sync>) -> Self {
        Self {
            child: Mutex::new(child),
            #[cfg(windows)]
            original: OnceLock::new(),
        }
    }

    pub(crate) fn wait(&self) -> io::Result<portable_pty::ExitStatus> {
        self.child
            .lock()
            .map_err(|_| io::Error::other("original portable child lock is poisoned"))?
            .wait()
    }

    #[cfg(windows)]
    pub(crate) fn retain_original_handle(
        &self,
        handle: std::os::windows::io::BorrowedHandle<'_>,
    ) -> io::Result<()> {
        let handle = Arc::new(handle.try_clone_to_owned()?);
        self.original
            .set(handle)
            .map_err(|_| io::Error::other("original portable process handle already retained"))
    }
}

impl RetainedChild for PortableChild {
    fn observe_cleanup(&self) -> io::Result<ProcessCleanupObservation> {
        #[cfg(windows)]
        {
            use std::os::windows::io::AsHandle;
            use std::os::windows::io::BorrowedHandle;
            if let Some(handle) = self.original.get() {
                return observe_windows_handle(handle.as_handle());
            }
            let child = match self.child.try_lock() {
                Ok(child) => child,
                Err(std::sync::TryLockError::WouldBlock) => {
                    return Ok(ProcessCleanupObservation::NoTerminalObservation);
                }
                Err(std::sync::TryLockError::Poisoned(_)) => {
                    return Err(io::Error::other("original portable child lock is poisoned"));
                }
            };
            let handle = child
                .as_raw_handle()
                .ok_or_else(|| io::Error::other("original portable process handle unavailable"))?;
            // The original child remains held for the complete zero-wait query.
            observe_windows_handle(unsafe { BorrowedHandle::borrow_raw(handle) })
        }
        #[cfg(not(windows))]
        {
            Ok(ProcessCleanupObservation::NoTerminalObservation)
        }
    }
}

#[cfg(unix)]
pub(crate) struct BlockingChild {
    pub(crate) child: Mutex<std::process::Child>,
}

#[cfg(unix)]
impl BlockingChild {
    pub(crate) fn new(child: std::process::Child) -> Self {
        Self {
            child: Mutex::new(child),
        }
    }

    pub(crate) fn wait(&self) -> io::Result<std::process::ExitStatus> {
        self.child
            .lock()
            .map_err(|_| io::Error::other("original blocking child lock is poisoned"))?
            .wait()
    }
}

#[cfg(unix)]
impl RetainedChild for BlockingChild {
    fn observe_cleanup(&self) -> io::Result<ProcessCleanupObservation> {
        Ok(ProcessCleanupObservation::NoTerminalObservation)
    }
}

#[cfg(windows)]
fn observe_windows_handle(
    handle: std::os::windows::io::BorrowedHandle<'_>,
) -> io::Result<ProcessCleanupObservation> {
    use std::os::windows::io::AsRawHandle;
    use winapi::shared::winerror::WAIT_TIMEOUT;
    use winapi::um::processthreadsapi::GetExitCodeProcess;
    use winapi::um::synchapi::WaitForSingleObject;
    use winapi::um::winbase::WAIT_FAILED;
    use winapi::um::winbase::WAIT_OBJECT_0;
    let handle = handle.as_raw_handle().cast();
    match unsafe {
        WaitForSingleObject(handle, /*dwMilliseconds*/ 0)
    } {
        WAIT_TIMEOUT => Ok(ProcessCleanupObservation::NoTerminalObservation),
        WAIT_OBJECT_0 => {
            let mut code = 0;
            if unsafe { GetExitCodeProcess(handle, &mut code) } == 0 {
                return Err(io::Error::last_os_error());
            }
            Ok(ProcessCleanupObservation::OwnerTerminated {
                owner_exit_code: Some(code as i32),
            })
        }
        WAIT_FAILED => Err(io::Error::last_os_error()),
        _ => Err(io::Error::other("unexpected original process wait result")),
    }
}
