//! Exact, launch-local handle inheritance. Original endpoints are never changed.
use anyhow::Result;
use anyhow::ensure;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use windows_sys::Win32::Foundation::DUPLICATE_SAME_ACCESS;
use windows_sys::Win32::Foundation::DuplicateHandle;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::System::Console::GetStdHandle;
use windows_sys::Win32::System::Console::STD_ERROR_HANDLE;
use windows_sys::Win32::System::Console::STD_INPUT_HANDLE;
use windows_sys::Win32::System::Console::STD_OUTPUT_HANDLE;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::STARTF_USESTDHANDLES;
use windows_sys::Win32::System::Threading::STARTUPINFOW;

pub(super) struct OwnedChildStdio {
    owned: Vec<OwnedHandle>,
    endpoints: [HANDLE; 3],
}

impl OwnedChildStdio {
    /// Keep only new exact duplicates inheritable until CreateProcess returns.
    /// An absent/closed ambient endpoint refuses instead of broad inheritance or
    /// changing a shared device ACL. Closed stdin uses the explicit EOF pipe.
    pub(super) fn duplicate(stdio: Option<(HANDLE, HANDLE, HANDLE)>) -> Result<Self> {
        let originals = match stdio {
            Some((stdin, stdout, stderr)) => [stdin, stdout, stderr],
            None => unsafe {
                [
                    GetStdHandle(STD_INPUT_HANDLE),
                    GetStdHandle(STD_OUTPUT_HANDLE),
                    GetStdHandle(STD_ERROR_HANDLE),
                ]
            },
        };
        let mut result = Self {
            owned: Vec::with_capacity(3),
            endpoints: [0; 3],
        };
        for (index, original) in originals.iter().copied().enumerate() {
            ensure!(
                original != 0 && original != INVALID_HANDLE_VALUE,
                "child stdio endpoint is closed or invalid"
            );
            if let Some(previous) = originals[..index]
                .iter()
                .position(|value| *value == original)
            {
                result.endpoints[index] = result.endpoints[previous];
                continue;
            }
            let mut duplicate = 0;
            // SAFETY: only this borrowed endpoint is duplicated; the original
            // remains owned by the caller. The returned duplicate is immediately
            // owned and is the only new handle admitted to HANDLE_LIST.
            let duplicated = unsafe {
                DuplicateHandle(
                    GetCurrentProcess(),
                    original,
                    GetCurrentProcess(),
                    &mut duplicate,
                    /*dwdesiredaccess*/ 0,
                    /*binherithandle*/ 1,
                    DUPLICATE_SAME_ACCESS,
                )
            };
            ensure!(
                duplicated != 0,
                "duplicate exact child stdio: {}",
                std::io::Error::last_os_error()
            );
            let owned = unsafe { OwnedHandle::from_raw_handle(duplicate as _) };
            result.endpoints[index] = owned.as_raw_handle() as HANDLE;
            result.owned.push(owned);
        }
        Ok(result)
    }

    pub(super) fn apply(&self, startup: &mut STARTUPINFOW) {
        startup.dwFlags |= STARTF_USESTDHANDLES;
        startup.hStdInput = self.endpoints[0];
        startup.hStdOutput = self.endpoints[1];
        startup.hStdError = self.endpoints[2];
    }

    pub(super) fn handle_list(&self) -> Vec<HANDLE> {
        self.owned
            .iter()
            .map(|handle| handle.as_raw_handle() as HANDLE)
            .collect()
    }
}

#[cfg(test)]
#[path = "owned_child_stdio_tests.rs"]
mod tests;
