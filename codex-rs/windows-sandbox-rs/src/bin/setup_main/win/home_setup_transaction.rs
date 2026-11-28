pub(super) use codex_windows_sandbox::HomeSetupGuard;

#[cfg(test)]
use anyhow::Result;
#[cfg(test)]
use anyhow::ensure;
#[cfg(test)]
use codex_windows_sandbox::sandbox_dir;
#[cfg(test)]
use std::ffi::c_void;
#[cfg(test)]
use std::os::windows::io::AsRawHandle;
#[cfg(test)]
use std::os::windows::io::OwnedHandle;
#[cfg(test)]
use std::path::Path;
#[cfg(test)]
use windows_sys::Win32::Foundation::GetLastError;
#[cfg(test)]
use windows_sys::Win32::Foundation::HANDLE;

#[cfg(test)]
#[path = "home_setup_transaction_tests.rs"]
mod tests;
