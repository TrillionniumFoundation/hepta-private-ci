//! Native test setup only; never supplies the result of the operation under test.

use std::ffi::c_void;
use std::io;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::ptr;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::DuplicateTokenEx;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::SecurityAnonymous;
use windows_sys::Win32::Security::TOKEN_DUPLICATE;
use windows_sys::Win32::Security::TOKEN_IMPERSONATE;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_STATISTICS;
use windows_sys::Win32::Security::TokenImpersonation;
use windows_sys::Win32::Security::TokenStatistics;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::OpenProcessToken;

pub(super) fn anonymous_level_token() -> io::Result<OwnedHandle> {
    let mut raw = 0;
    // SAFETY: open only this process's token into live output storage.
    if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY | TOKEN_DUPLICATE, &mut raw) }
        == 0
    {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: successful open transfers one newly owned handle.
    let process = unsafe { OwnedHandle::from_raw_handle(raw as *mut c_void) };
    // Anonymous logon identity alone does not establish SecurityAnonymous level.
    // SAFETY: create a separate, non-inherited fixture token; no token is mutated.
    if unsafe {
        DuplicateTokenEx(
            process.as_raw_handle() as HANDLE,
            TOKEN_QUERY | TOKEN_IMPERSONATE,
            ptr::null(),
            SecurityAnonymous,
            TokenImpersonation,
            &mut raw,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: successful duplication transfers one newly owned handle.
    let token = unsafe { OwnedHandle::from_raw_handle(raw as *mut c_void) };
    let mut observed: TOKEN_STATISTICS = unsafe { std::mem::zeroed() };
    let mut returned = 0;
    // Verify the actual kernel-created token before installing it on the thread.
    // SAFETY: the query handle and fixed initialized output remain live.
    if unsafe {
        GetTokenInformation(
            token.as_raw_handle() as HANDLE,
            TokenStatistics,
            (&mut observed as *mut TOKEN_STATISTICS).cast(),
            size_of::<TOKEN_STATISTICS>() as u32,
            &mut returned,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    if returned as usize != size_of::<TOKEN_STATISTICS>()
        || observed.TokenType != TokenImpersonation
        || observed.ImpersonationLevel != SecurityAnonymous
    {
        return Err(io::Error::other(
            "fixture did not create an anonymous-level token",
        ));
    }
    eprintln!(
        "HEPTA_TOKEN_FIXTURE bytes={returned} type={} level={}",
        observed.TokenType, observed.ImpersonationLevel
    );
    Ok(token)
}
