use crate::token::enable_single_privilege;
use crate::token::get_logon_sid_bytes;
use crate::token::get_user_sid_bytes;
use crate::token::set_default_dacl;
use crate::token_information::TokenInformation;
use anyhow::Result;
use anyhow::bail;
use std::ffi::c_void;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::CreateRestrictedToken;
use windows_sys::Win32::Security::DISABLE_MAX_PRIVILEGE;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::IsTokenRestricted;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::LUA_TOKEN;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::TokenGroups;

/// Restricts every access check, including DELETE and FILE_DELETE_CHILD.
///
/// Read capabilities and network route markers may satisfy only the explicit
/// object grants made for those identities. They never receive default-DACL
/// write grants. Ambient account and group identities satisfy only the normal
/// access check; none is an alternative to a capability in the second check.
///
/// # Safety
/// `base` must be a valid unrestricted primary token and all SID pointers must
/// remain valid for the call. The caller closes the returned owned token handle.
pub(crate) unsafe fn create_workspace_token(
    base: HANDLE,
    write_capabilities: &[*mut c_void],
    additional_restricting_sids: &[*mut c_void],
) -> Result<HANDLE> {
    anyhow::ensure!(
        !write_capabilities.is_empty(),
        "no write capability SIDs provided"
    );
    anyhow::ensure!(
        unsafe { IsTokenRestricted(base) } == 0,
        "workspace broker requires an unrestricted base token"
    );
    let groups = unsafe { TokenInformation::query(base, TokenGroups)? };
    let mut ambient_sids = unsafe { groups.group_sids()? };
    ambient_sids.push(unsafe { get_user_sid_bytes(base)? });
    let mut entries: Vec<SID_AND_ATTRIBUTES> = Vec::new();
    for &sid in write_capabilities.iter().chain(additional_restricting_sids) {
        anyhow::ensure!(
            !sid.is_null() && unsafe { IsValidSid(sid) } != 0,
            "invalid workspace restricting SID"
        );
        anyhow::ensure!(
            !ambient_sids
                .iter()
                .any(|ambient| unsafe { EqualSid(sid, ambient.as_ptr().cast_mut().cast()) != 0 }),
            "workspace restricting SIDs must not contain ambient token identities"
        );
        if !entries
            .iter()
            .any(|entry| unsafe { EqualSid(entry.Sid, sid) } != 0)
        {
            entries.push(SID_AND_ATTRIBUTES {
                Sid: sid,
                Attributes: 0,
            });
        }
    }
    let mut token = 0;
    if unsafe {
        CreateRestrictedToken(
            base,
            DISABLE_MAX_PRIVILEGE | LUA_TOKEN,
            /*disablesidcount*/ 0,
            std::ptr::null(),
            /*deleteprivilegecount*/ 0,
            std::ptr::null(),
            entries.len().try_into()?,
            entries.as_mut_ptr(),
            &mut token,
        )
    } == 0
    {
        bail!("CreateRestrictedToken workspace failed: {}", unsafe {
            GetLastError()
        });
    }
    let configure = || -> Result<()> {
        let mut logon = unsafe { get_logon_sid_bytes(base)? };
        let mut user = unsafe { get_user_sid_bytes(base)? };
        let mut default_dacl = vec![logon.as_mut_ptr().cast(), user.as_mut_ptr().cast()];
        default_dacl.extend_from_slice(write_capabilities);
        unsafe {
            set_default_dacl(token, &default_dacl)?;
            enable_single_privilege(token, "SeChangeNotifyPrivilege")
        }
    };
    if let Err(error) = configure() {
        unsafe {
            CloseHandle(token);
        }
        return Err(error);
    }
    Ok(token)
}

#[cfg(test)]
#[path = "workspace_token_tests.rs"]
mod tests;
