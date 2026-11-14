use crate::token::get_logon_sid_bytes;
use crate::token_information::TokenInformation;
use anyhow::Result;
use anyhow::bail;
use std::ffi::c_void;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::TOKEN_DEFAULT_DACL;
use windows_sys::Win32::Security::TokenDefaultDacl;
use windows_sys::Win32::Security::TokenRestrictedSids;

const ACCESS_ALLOWED_ACE_TYPE: u8 = 0;
const GENERIC_ALL: u32 = 0x1000_0000;

/// Selects only object-write capabilities, excluding read caps and route markers.
///
/// The workspace token factory gives default-DACL grants exclusively to its
/// write capabilities and normal account identities. Intersecting these grants
/// with the restricting SID set keeps read and route identities out of private
/// desktop and window-station ACLs.
///
/// # Safety
/// The token must be valid and permit queries.
pub(crate) unsafe fn private_object_capabilities(token: HANDLE) -> Result<Vec<Vec<u8>>> {
    let information = unsafe { TokenInformation::query(token, TokenRestrictedSids)? };
    let sids = unsafe { information.group_sids()? };
    anyhow::ensure!(!sids.is_empty(), "sandbox token has no restricting SIDs");
    let logon_sid = unsafe { get_logon_sid_bytes(token)? };
    if sids.contains(&logon_sid) {
        // Retain the existing readonly-token object contract.
        return Ok(Vec::new());
    }
    let default_dacl = unsafe { TokenInformation::query(token, TokenDefaultDacl)? };
    let descriptor = default_dacl.as_ptr::<TOKEN_DEFAULT_DACL>()?;
    let acl = unsafe { (*descriptor).DefaultDacl };
    anyhow::ensure!(!acl.is_null(), "workspace token has no default DACL");
    let mut capabilities = Vec::new();
    for sid in sids {
        let mut full_access = false;
        for index in 0..unsafe { (*acl).AceCount } {
            let mut ace: *mut c_void = std::ptr::null_mut();
            if unsafe { GetAce(acl, u32::from(index), &mut ace) } == 0 {
                bail!("GetAce for workspace default DACL failed: {}", unsafe {
                    GetLastError()
                });
            }
            let header = unsafe { &*ace.cast::<ACE_HEADER>() };
            if header.AceType != ACCESS_ALLOWED_ACE_TYPE
                || usize::from(header.AceSize) < std::mem::size_of::<ACCESS_ALLOWED_ACE>()
            {
                continue;
            }
            let allowed = unsafe { &*ace.cast::<ACCESS_ALLOWED_ACE>() };
            if allowed.Mask & GENERIC_ALL == GENERIC_ALL
                && unsafe {
                    EqualSid(
                        std::ptr::addr_of!(allowed.SidStart).cast_mut().cast(),
                        sid.as_ptr().cast_mut().cast(),
                    )
                } != 0
            {
                full_access = true;
                break;
            }
        }
        if full_access {
            capabilities.push(sid);
        }
    }
    anyhow::ensure!(
        !capabilities.is_empty(),
        "workspace token has no private-object write capability"
    );
    Ok(capabilities)
}
