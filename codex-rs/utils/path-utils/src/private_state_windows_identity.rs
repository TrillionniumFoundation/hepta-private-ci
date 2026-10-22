//! Read-only scope check for consumers using process-TokenUser ownership.

use std::io;

use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_NO_TOKEN;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenThreadToken;

/// Rejects any thread impersonation and any uncertainty about its absence.
/// This does not change tokens, privileges, ownership or access controls. Call
/// at acquisition and return boundaries when relying on process-user policy.
pub fn require_non_impersonating_thread() -> io::Result<()> {
    let mut token = 0;
    // SAFETY: current-thread pseudo handle and exclusively borrowed output are
    // valid for the synchronous query. OpenAsSelf does not change identity.
    let result = unsafe { OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, 1, &mut token) };
    let query = if result == 0 {
        // Read the error before another Win32 call can overwrite it.
        Err(unsafe { GetLastError() })
    } else {
        // SAFETY: a successful OpenThreadToken returned an owned token handle.
        unsafe { CloseHandle(token) };
        Ok(())
    };
    reject_impersonation(query)
}

fn reject_impersonation(query: Result<(), u32>) -> io::Result<()> {
    match query {
        Err(ERROR_NO_TOKEN) => Ok(()),
        Err(error) => Err(io::Error::from_raw_os_error(error as i32)),
        Ok(()) => Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "private custody does not support thread impersonation",
        )),
    }
}

#[cfg(test)]
#[path = "private_state_windows_identity_tests.rs"]
mod tests;
