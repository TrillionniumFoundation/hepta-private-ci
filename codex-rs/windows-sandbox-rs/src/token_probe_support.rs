//! Private Windows mechanism fixtures; production legacy admission stays closed.

pub(super) use crate::acl::add_deny_write_ace;
pub(super) use crate::acl::ensure_allow_mask_aces;
pub(super) use crate::acl::ensure_allow_write_aces;
pub(super) use crate::acl::fetch_dacl_handle;
pub(super) use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
pub(super) use windows_sys::Win32::Security::Authorization::SetNamedSecurityInfoW;
pub(super) use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
pub(super) use windows_sys::Win32::Storage::FileSystem::DELETE;

use super::super::create_write_restricted_token_for_mic_probe;
use anyhow::Result;
use anyhow::anyhow;
use std::ffi::c_void;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::ImpersonateLoggedOnUser;
use windows_sys::Win32::Security::RevertToSelf;

pub(super) struct Impersonation;

impl Impersonation {
    pub(super) unsafe fn enter(token: HANDLE) -> Result<Self> {
        if ImpersonateLoggedOnUser(token) == 0 {
            return Err(anyhow!(
                "ImpersonateLoggedOnUser failed: {}",
                GetLastError()
            ));
        }
        Ok(Self)
    }
}

impl Drop for Impersonation {
    fn drop(&mut self) {
        if unsafe { RevertToSelf() } == 0 {
            // Continuing on a reused test thread with the wrong token is unsafe.
            std::process::abort();
        }
    }
}

/// Construct only the token measured by the owned-fixture MIC experiment.
/// The public workspace factory still refuses unqualified legacy isolation.
///
/// # Safety
/// The caller owns the live primary token and SIDs and must close the result.
pub(super) unsafe fn write_restricted_probe_token_from(
    base_token: HANDLE,
    capabilities: &[*mut c_void],
) -> Result<HANDLE> {
    unsafe { create_write_restricted_token_for_mic_probe(base_token, capabilities) }
}
