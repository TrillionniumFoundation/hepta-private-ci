//! Native ACL fixtures. These tokens exercise object ACLs without claiming a
//! filesystem sandbox: production workspace launches use the dedicated-account broker.

use anyhow::Result;
use anyhow::bail;
use std::ffi::c_void;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::CreateRestrictedToken;
use windows_sys::Win32::Security::DISABLE_MAX_PRIVILEGE;
use windows_sys::Win32::Security::LUA_TOKEN;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::WRITE_RESTRICTED;

/// Returns an owned token handle restricted to the supplied object capability.
///
/// # Safety
/// The base token and SID pointers must be valid; the caller closes the result.
pub(crate) unsafe fn capability_acl_fixture_token(
    base_token: HANDLE,
    capabilities: &[*mut c_void],
) -> Result<HANDLE> {
    let mut restricting = capabilities
        .iter()
        .map(|sid| SID_AND_ATTRIBUTES {
            Sid: *sid,
            Attributes: 0,
        })
        .collect::<Vec<_>>();
    let mut token = 0;
    if unsafe {
        CreateRestrictedToken(
            base_token,
            DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED,
            /*disablesidcount*/ 0,
            std::ptr::null(),
            /*deleteprivilegecount*/ 0,
            std::ptr::null(),
            restricting.len().try_into()?,
            restricting.as_mut_ptr(),
            &mut token,
        )
    } == 0
    {
        bail!("CreateRestrictedToken ACL fixture failed: {}", unsafe {
            GetLastError()
        });
    }
    Ok(token)
}
