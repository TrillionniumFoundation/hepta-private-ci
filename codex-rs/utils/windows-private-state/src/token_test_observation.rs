//! Test-only bounded observations; these never supply the expected result.

use std::ffi::c_void;
use std::fmt::Debug;
use std::io;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_STATISTICS;
use windows_sys::Win32::Security::TokenStatistics;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenThreadToken;

pub(super) fn observe<T, E: Debug>(result: &Result<T, E>) {
    // Print the original result without requiring/exposing a successful SID or
    // retained principal. Cap even unexpected Debug text before writing it.
    let error: String = format!("{:?}", result.as_ref().err())
        .chars()
        .take(256)
        .collect();
    eprintln!("HEPTA_TOKEN_QUERY original_error={error}");
    let mut raw = 0;
    // Independent read-only fixture diagnosis, after the original operation.
    // Never fall back to a process token or manufacture its result/errno.
    if unsafe {
        OpenThreadToken(
            GetCurrentThread(),
            TOKEN_QUERY,
            /*openasself*/ 1,
            &mut raw,
        )
    } == 0
    {
        let error = io::Error::last_os_error();
        eprintln!(
            "HEPTA_TOKEN_QUERY OpenThreadToken error={:?}",
            error.raw_os_error()
        );
        return;
    }
    // SAFETY: successful open transfers one live non-inherited query handle.
    let token = unsafe { OwnedHandle::from_raw_handle(raw as *mut c_void) };
    let mut statistics: TOKEN_STATISTICS = unsafe { std::mem::zeroed() };
    let mut length = 0;
    // SAFETY: the query-only fixture handle and fixed output remain live.
    if unsafe {
        GetTokenInformation(
            token.as_raw_handle() as HANDLE,
            TokenStatistics,
            (&mut statistics as *mut TOKEN_STATISTICS).cast(),
            size_of::<TOKEN_STATISTICS>() as u32,
            &mut length,
        )
    } == 0
    {
        let error = io::Error::last_os_error();
        eprintln!(
            "HEPTA_TOKEN_QUERY TokenStatistics error={:?}",
            error.raw_os_error()
        );
    } else {
        eprintln!(
            "HEPTA_TOKEN_QUERY TokenStatistics bytes={length} type={} level={}",
            statistics.TokenType, statistics.ImpersonationLevel
        );
    }
}
