//! Test-only native tokens for in-process checks on owned temporary objects.
//! These fixtures do not qualify legacy process admission and must never be
//! used to launch a child process or access unrelated filesystem objects.

use super::DISABLE_MAX_PRIVILEGE;
use super::LUA_TOKEN;
use super::RestrictingIdentity;
use super::WRITE_RESTRICTED;
use super::create_token_with_caps_and_explicit_flags_from;
use super::create_token_with_caps_from;
use anyhow::Result;
use std::ffi::c_void;
use windows_sys::Win32::Foundation::HANDLE;

/// # Safety
/// The caller must retain a live base token and SIDs, close the returned token,
/// and limit impersonated operations to its owned directory or private desktop.
pub(crate) unsafe fn workspace_token_for_owned_objects(
    base_token: HANDLE,
    capabilities: &[*mut c_void],
) -> Result<HANDLE> {
    unsafe {
        // Preserve this original counterexample fixture's enforcement mode.
        // The independent fully-restricted diagnostics use their own constructor.
        create_token_with_caps_and_explicit_flags_from(
            base_token,
            capabilities,
            &[],
            RestrictingIdentity::Exclude,
            DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED,
        )
    }
}

/// # Safety
/// The same owned-object and handle-lifetime restrictions apply. Including the
/// existing identity checks the desktop mechanism, not filesystem isolation.
pub(crate) unsafe fn readonly_token_for_owned_objects(
    base_token: HANDLE,
    capabilities: &[*mut c_void],
) -> Result<HANDLE> {
    unsafe {
        create_token_with_caps_from(base_token, capabilities, &[], RestrictingIdentity::Include)
    }
}
