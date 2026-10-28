//! Recognize native deny normalization without confusing file and directory scope.

use super::ACCESS_DENIED_ACE_TYPE;
use super::CONTAINER_INHERIT_ACE;
use super::DenyAceKind;
use super::INHERIT_ONLY_ACE;
use super::INHERITED_ACE;
use super::OBJECT_INHERIT_ACE;
use super::acl_api_result;
use anyhow::Result;
use anyhow::anyhow;
use std::ffi::c_void;
use std::fs::File;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACCESS_DENIED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::ACL_SIZE_INFORMATION;
use windows_sys::Win32::Security::AclSizeInformation;
use windows_sys::Win32::Security::Authorization::EXPLICIT_ACCESS_W;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetEntriesInAclW;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_SID;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_UNKNOWN;
use windows_sys::Win32::Security::Authorization::TRUSTEE_W;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GENERIC_MAPPING;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetAclInformation;
use windows_sys::Win32::Security::MapGenericMask;
use windows_sys::Win32::Storage::FileSystem::BY_HANDLE_FILE_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_ID_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FileIdInfo;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandle;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandleEx;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;

#[derive(Clone, Copy)]
pub(super) enum DenyTarget {
    File,
    Directory,
}

impl DenyTarget {
    unsafe fn already_present(self, dacl: *mut ACL, sid: *mut c_void, kind: DenyAceKind) -> bool {
        match self {
            Self::Directory => kind.already_present(dacl, sid),
            Self::File => has_complete_deny(dacl, sid, kind.mask(), self),
        }
    }
}

// SAFETY: the caller retains a valid ACL (or null) and SID for the whole query.
pub(super) unsafe fn has_complete_deny(
    dacl: *mut ACL,
    sid: *mut c_void,
    mut required: u32,
    target: DenyTarget,
) -> bool {
    if dacl.is_null() {
        return false;
    }
    let mut info: ACL_SIZE_INFORMATION = std::mem::zeroed();
    if GetAclInformation(
        dacl,
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
    MapGenericMask(&mut required, &mapping);
    let (mut effective, mut containers, mut objects) = (0, 0, 0);
    let inheritance = (CONTAINER_INHERIT_ACE | OBJECT_INHERIT_ACE) as u8;
    for index in 0..info.AceCount {
        let mut entry: *mut c_void = std::ptr::null_mut();
        if GetAce(dacl, index, &mut entry) == 0 {
            return false;
        }
        let header = &*(entry as *const ACE_HEADER);
        // Preserve the leading-explicit-deny rule: an earlier allow, inherited
        // or unsupported ACE cannot be used to certify a later explicit deny.
        if header.AceType != ACCESS_DENIED_ACE_TYPE || header.AceFlags & INHERITED_ACE != 0 {
            return false;
        }
        // In particular, no-propagate must not certify arbitrary descendants.
        if header.AceFlags & !(inheritance | INHERIT_ONLY_ACE) != 0 {
            continue;
        }
        let ace = &*(entry as *const ACCESS_DENIED_ACE);
        let entry_sid = std::ptr::addr_of!(ace.SidStart) as *mut c_void;
        if EqualSid(entry_sid, sid) == 0 {
            continue;
        }
        let mut mask = ace.Mask;
        MapGenericMask(&mut mask, &mapping);
        if header.AceFlags & INHERIT_ONLY_ACE == 0 {
            effective |= mask;
        }
        if header.AceFlags & CONTAINER_INHERIT_ACE as u8 != 0 {
            containers |= mask;
        }
        if header.AceFlags & OBJECT_INHERIT_ACE as u8 != 0 {
            objects |= mask;
        }
        // SetSecurityInfo can split a recursive generic deny into an effective
        // mapped ACE and an inherit-only generic ACE. Both scopes must cover
        // every required right; an effective-only directory deny is incomplete.
        if effective & required == required
            && (matches!(target, DenyTarget::File)
                || (containers & required == required && objects & required == required))
        {
            return true;
        }
    }
    false
}

struct LocalAllocation(*mut c_void);

impl Drop for LocalAllocation {
    fn drop(&mut self) {
        if !self.0.is_null() {
            // SAFETY: this guard uniquely owns an allocation returned by the ACL APIs.
            unsafe { LocalFree(self.0 as HLOCAL) };
        }
    }
}

unsafe fn read_dacl(file: &File, path: &Path) -> Result<(LocalAllocation, *mut ACL)> {
    let mut descriptor = std::ptr::null_mut();
    let mut dacl = std::ptr::null_mut();
    let code = GetSecurityInfo(
        file.as_raw_handle() as HANDLE,
        SE_FILE_OBJECT,
        DACL_SECURITY_INFORMATION,
        std::ptr::null_mut(),
        std::ptr::null_mut(),
        &mut dacl,
        std::ptr::null_mut(),
        &mut descriptor,
    );
    let allocation = LocalAllocation(descriptor);
    acl_api_result(path, "GetSecurityInfo", code)?;
    Ok((allocation, dacl))
}

fn target_kind(file: &File, path: &Path) -> Result<DenyTarget> {
    // SAFETY: the live file handle and output buffer remain valid for the query.
    let mut information: BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
    if unsafe { GetFileInformationByHandle(file.as_raw_handle() as HANDLE, &mut information) } == 0
    {
        return Err(anyhow!(
            "GetFileInformationByHandle failed for {}: {}",
            path.display(),
            std::io::Error::last_os_error()
        ));
    }
    Ok(
        if information.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY == 0 {
            DenyTarget::File
        } else {
            DenyTarget::Directory
        },
    )
}

fn file_identity(file: &File, path: &Path) -> Result<(u64, [u8; 16])> {
    // The legacy 64-bit file index is not guaranteed unique on ReFS. Compare
    // FileIdInfo's full 128-bit identity and volume number while both handles live.
    let mut information: FILE_ID_INFO = unsafe { std::mem::zeroed() };
    // SAFETY: the buffer has the native structure's alignment and exact size.
    if unsafe {
        GetFileInformationByHandleEx(
            file.as_raw_handle() as HANDLE,
            FileIdInfo,
            (&mut information as *mut FILE_ID_INFO).cast(),
            std::mem::size_of::<FILE_ID_INFO>() as u32,
        )
    } == 0
    {
        return Err(anyhow!(
            "FileIdInfo failed for {}: {}",
            path.display(),
            std::io::Error::last_os_error()
        ));
    }
    if information.FileId.Identifier == [0; 16] {
        return Err(anyhow!(
            "FileIdInfo has no usable identity for {}",
            path.display()
        ));
    }
    Ok((
        information.VolumeSerialNumber,
        information.FileId.Identifier,
    ))
}

pub(super) fn open_repair_target(path: &Path, original: &File) -> Result<File> {
    let identity = file_identity(original, path)?;
    // ReOpenFile returned ERROR_ACCESS_DENIED for the real directory fixture.
    // Opening by name is usable only after matching the pinned original object;
    // an unsupported identity query or replacement must fail before any ACL write.
    let writable = File::options()
        .access_mode(READ_CONTROL | WRITE_DAC)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
        .open(path)?;
    if file_identity(&writable, path)? != identity {
        return Err(anyhow!(
            "ACL repair target identity changed for {}",
            path.display()
        ));
    }
    Ok(writable)
}

pub(super) unsafe fn add_deny_ace(
    path: &Path,
    sid: *mut c_void,
    kind: DenyAceKind,
) -> Result<bool> {
    let sharing = FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE;
    let file = File::options()
        .access_mode(READ_CONTROL)
        .share_mode(sharing)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
        .open(path)?;
    let target = target_kind(&file, path)?;
    let (_descriptor, dacl) = read_dacl(&file, path)?;
    if target.already_present(dacl, sid, kind) {
        return Ok(false);
    }
    // Request WRITE_DAC only after the read-only completeness fast path.
    let writable = open_repair_target(path, &file)?;
    let target = target_kind(&writable, path)?;
    let (_current_descriptor, current_dacl) = read_dacl(&writable, path)?;
    if target.already_present(current_dacl, sid, kind) {
        return Ok(false);
    }
    let entry = EXPLICIT_ACCESS_W {
        grfAccessPermissions: kind.mask(),
        grfAccessMode: super::DENY_ACCESS,
        grfInheritance: CONTAINER_INHERIT_ACE | OBJECT_INHERIT_ACE,
        Trustee: TRUSTEE_W {
            pMultipleTrustee: std::ptr::null_mut(),
            MultipleTrusteeOperation: 0,
            TrusteeForm: TRUSTEE_IS_SID,
            TrusteeType: TRUSTEE_IS_UNKNOWN,
            ptstrName: sid as *mut u16,
        },
    };
    let mut new_dacl = std::ptr::null_mut();
    let code = SetEntriesInAclW(1, &entry, current_dacl, &mut new_dacl);
    let _new_allocation = LocalAllocation(new_dacl.cast());
    acl_api_result(path, "SetEntriesInAclW", code)?;
    if new_dacl.is_null() {
        return Err(anyhow!("ACL repair returned a null DACL"));
    }
    let code = SetSecurityInfo(
        writable.as_raw_handle() as HANDLE,
        SE_FILE_OBJECT,
        DACL_SECURITY_INFORMATION,
        std::ptr::null_mut(),
        std::ptr::null_mut(),
        new_dacl,
        std::ptr::null_mut(),
    );
    acl_api_result(path, "SetSecurityInfo", code)?;
    Ok(true)
}
