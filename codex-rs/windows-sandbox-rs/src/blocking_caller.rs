use anyhow::Context;
use anyhow::Result;
use std::marker::PhantomData;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::rc::Rc;
use windows_sys::Win32::Foundation::ERROR_NO_TOKEN;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::TOKEN_IMPERSONATE;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenThreadToken;
use windows_sys::Win32::System::Threading::SetThreadToken;

/// Retains the effective caller while synchronous setup moves to a worker.
pub(crate) struct CapturedCaller {
    token: Option<OwnedHandle>,
}

impl CapturedCaller {
    pub(crate) fn capture() -> Result<Self> {
        let mut token = 0;
        if unsafe {
            OpenThreadToken(
                GetCurrentThread(),
                TOKEN_QUERY | TOKEN_IMPERSONATE,
                /*openasself*/ 1,
                &mut token,
            )
        } != 0
        {
            // SAFETY: successful OpenThreadToken returns an owned impersonation handle.
            Ok(Self {
                token: Some(unsafe { OwnedHandle::from_raw_handle(token as _) }),
            })
        } else {
            let error = std::io::Error::last_os_error();
            if error.raw_os_error() == Some(ERROR_NO_TOKEN as i32) {
                Ok(Self { token: None })
            } else {
                Err(error).context("capture sandbox setup caller token")
            }
        }
    }

    pub(crate) fn enter(self) -> Result<CallerImpersonation> {
        let previous = Self::capture()?;
        let entered = unsafe {
            match self.token.as_ref() {
                Some(token) => SetThreadToken(std::ptr::null(), token.as_raw_handle() as HANDLE),
                None => RevertToSelf(),
            }
        };
        if entered == 0 {
            return Err(std::io::Error::last_os_error())
                .context("restore sandbox caller on blocking worker");
        }
        Ok(CallerImpersonation {
            previous,
            _same_thread: PhantomData,
        })
    }
}

pub(crate) struct CallerImpersonation {
    previous: CapturedCaller,
    _same_thread: PhantomData<Rc<()>>,
}

impl Drop for CallerImpersonation {
    fn drop(&mut self) {
        let restored = unsafe {
            match self.previous.token.as_ref() {
                Some(token) => SetThreadToken(std::ptr::null(), token.as_raw_handle() as HANDLE),
                None => RevertToSelf(),
            }
        };
        if restored == 0 {
            // A pooled worker must never continue another request under this caller.
            crate::logging::debug_log("failed to restore blocking worker caller token", None);
            std::process::abort();
        }
    }
}
