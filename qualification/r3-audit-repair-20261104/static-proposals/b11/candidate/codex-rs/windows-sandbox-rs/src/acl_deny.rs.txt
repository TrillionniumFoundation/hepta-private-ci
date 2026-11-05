//! Recognize the native file/directory deny representation on the queried object.
//!
//! The query and optional update retain the same filesystem object. This does not
//! serialize other DACL writers or establish custody of its pathname/ancestors.

use super::*;
use anyhow::Context;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Storage::FileSystem::FILE_STANDARD_INFO;
use windows_sys::Win32::Storage::FileSystem::FileStandardInfo;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandleEx;
use windows_sys::Win32::Storage::FileSystem::ReOpenFile;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;

#[derive(Clone, Copy)]
pub(super) enum DenyObjectScope {
    File,
    Directory,
}

struct LocalAllocation(*mut c_void);

impl Drop for LocalAllocation {
    fn drop(&mut self) {
        if !self.0.is_null() {
            // SAFETY: this guard owns only allocations returned by the ACL APIs.
            unsafe { LocalFree(self.0 as HLOCAL) };
        }
    }
}

// SAFETY: both pointers remain valid throughout the query. The scope must come
// from the same object whose DACL was retrieved, not a separate path lookup.
pub(super) unsafe fn dacl_has_complete_deny_for_object(
    p_dacl: *mut ACL,
    psid: *mut c_void,
    kind: DenyAceKind,
    scope: DenyObjectScope,
) -> bool {
    // Keep the existing strict, recursively effective public query unchanged.
    if kind.already_present(p_dacl, psid) {
        return true;
    }
    if p_dacl.is_null() {
        return false;
    }
    let mut info: ACL_SIZE_INFORMATION = std::mem::zeroed();
    if GetAclInformation(
        p_dacl,
        &mut info as *mut _ as *mut c_void,
        std::mem::size_of::<ACL_SIZE_INFORMATION>() as u32,
        AclSizeInformation,
    ) == 0
    {
        return false;
    }
    let mapping = GENERIC_MAPPING {
        GenericRead: FILE_GENERIC_READ,
        GenericWrite: FILE_GENERIC_WRITE,
        GenericExecute: FILE_GENERIC_EXECUTE,
        GenericAll: FILE_ALL_ACCESS,
    };
    let mut required_mask = kind.mask();
    MapGenericMask(&mut required_mask, &mapping);
    let mut effective = false;
    let mut descendants = false;
    let inherited_scope = (OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE) as u8 | INHERIT_ONLY_ACE;
    for i in 0..info.AceCount {
        let mut p_ace = std::ptr::null_mut();
        if GetAce(p_dacl, i, &mut p_ace) == 0 {
            return false;
        }
        let header = &*(p_ace as *const ACE_HEADER);
        if header.AceType != ACCESS_DENIED_ACE_TYPE || header.AceFlags & INHERITED_ACE != 0 {
            return false;
        }
        let ace = &*(p_ace as *const ACCESS_DENIED_ACE);
        let sid = std::ptr::addr_of!(ace.SidStart).cast_mut().cast();
        let mut mask = ace.Mask;
        MapGenericMask(&mut mask, &mapping);
        if EqualSid(sid, psid) == 0 || mask & required_mask != required_mask {
            continue;
        }
        // Each half must independently cover the whole mask for this same SID.
        // Never accumulate partial rights, inherited entries, or no-propagate.
        if header.AceFlags == 0 {
            effective = true;
        } else if header.AceFlags == inherited_scope {
            descendants = true;
        }
        match scope {
            DenyObjectScope::File if effective => return true,
            DenyObjectScope::Directory if effective && descendants => return true,
            DenyObjectScope::File | DenyObjectScope::Directory => {}
        }
    }
    false
}

pub(super) unsafe fn add_deny_ace(
    path: &Path,
    psid: *mut c_void,
    kind: DenyAceKind,
) -> Result<bool> {
    let raw = CreateFileW(
        to_wide(path).as_ptr(),
        READ_CONTROL,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        std::ptr::null_mut(),
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS,
        /*htemplatefile*/ 0,
    );
    if raw == INVALID_HANDLE_VALUE {
        return Err(std::io::Error::last_os_error())
            .with_context(|| format!("CreateFileW for deny query failed for {}", path.display()));
    }
    let object = OwnedHandle::from_raw_handle(raw as _);
    let handle = object.as_raw_handle() as HANDLE;
    let mut info: FILE_STANDARD_INFO = std::mem::zeroed();
    if GetFileInformationByHandleEx(
        handle,
        FileStandardInfo,
        &mut info as *mut _ as *mut c_void,
        std::mem::size_of::<FILE_STANDARD_INFO>() as u32,
    ) == 0
    {
        return Err(std::io::Error::last_os_error()).with_context(|| {
            format!("GetFileInformationByHandleEx failed for {}", path.display())
        });
    }
    let scope = if info.Directory != 0 {
        DenyObjectScope::Directory
    } else {
        DenyObjectScope::File
    };
    let mut descriptor = LocalAllocation(std::ptr::null_mut());
    let mut dacl = std::ptr::null_mut();
    let code = GetSecurityInfo(
        handle,
        SE_FILE_OBJECT,
        DACL_SECURITY_INFORMATION,
        std::ptr::null_mut(),
        std::ptr::null_mut(),
        &mut dacl,
        std::ptr::null_mut(),
        &mut descriptor.0,
    );
    acl_api_result(path, "GetSecurityInfo", code)?;
    if dacl_has_complete_deny_for_object(dacl, psid, kind, scope) {
        return Ok(false);
    }

    // Reopen this object, not its path. No-op callers never require WRITE_DAC.
    let raw_write = ReOpenFile(
        handle,
        WRITE_DAC,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        FILE_FLAG_BACKUP_SEMANTICS,
    );
    if raw_write == INVALID_HANDLE_VALUE {
        return Err(std::io::Error::last_os_error())
            .with_context(|| format!("ReOpenFile for deny repair failed for {}", path.display()));
    }
    let writable = OwnedHandle::from_raw_handle(raw_write as _);
    let entry = EXPLICIT_ACCESS_W {
        grfAccessPermissions: kind.mask(),
        grfAccessMode: DENY_ACCESS,
        grfInheritance: CONTAINER_INHERIT_ACE | OBJECT_INHERIT_ACE,
        Trustee: TRUSTEE_W {
            pMultipleTrustee: std::ptr::null_mut(),
            MultipleTrusteeOperation: 0,
            TrusteeForm: TRUSTEE_IS_SID,
            TrusteeType: TRUSTEE_IS_UNKNOWN,
            ptstrName: psid.cast(),
        },
    };
    let mut new_dacl = std::ptr::null_mut();
    let code = SetEntriesInAclW(/*ccountofexplicitentries*/ 1, &entry, dacl, &mut new_dacl);
    let allocation = LocalAllocation(new_dacl.cast());
    acl_api_result(path, "SetEntriesInAclW", code)?;
    let code = SetSecurityInfo(
        writable.as_raw_handle() as HANDLE,
        SE_FILE_OBJECT,
        DACL_SECURITY_INFORMATION,
        std::ptr::null_mut(),
        std::ptr::null_mut(),
        allocation.0.cast(),
        std::ptr::null_mut(),
    );
    acl_api_result(path, "SetSecurityInfo", code).map(|()| true)
}
