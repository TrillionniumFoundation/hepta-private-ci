//! Complete immutable facts of a retained Windows private-state handle.

use std::fs::File;
use std::io;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use std::ptr;

use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::ACL_SIZE_INFORMATION;
use windows_sys::Win32::Security::AclSizeInformation;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GetAclInformation;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_BASIC_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_ID_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_STANDARD_INFO;
use windows_sys::Win32::Storage::FileSystem::FileBasicInfo;
use windows_sys::Win32::Storage::FileSystem::FileIdInfo;
use windows_sys::Win32::Storage::FileSystem::FileStandardInfo;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandleEx;

use super::CurrentUser;
use super::dacl_grants_untrusted_access;
use super::unsafe_state;

/// Metadata facts only, with no writer or recovery authority. Fields are private
/// so consumers can compare snapshots but cannot manufacture a validated one.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PrivateStateSnapshot {
    volume: u64,
    file_id: [u8; 16],
    attributes: u32,
    directory: bool,
    links: u32,
    length: u64,
    allocation: i64,
    created: i64,
    written: i64,
    changed: i64,
    security: SecuritySnapshot,
}

impl PrivateStateSnapshot {
    pub fn is_directory(&self) -> bool {
        self.directory
    }

    pub fn len(&self) -> u64 {
        self.length
    }

    pub fn is_empty(&self) -> bool {
        self.length == 0
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct SecuritySnapshot {
    control: u16,
    revision: u32,
    owner: Vec<u8>,
    dacl: Vec<u8>,
}

/// Captures file ID, change/write times, length, links, attributes, and the exact
/// validated owner/DACL. Missing information fails closed. Last-access time is
/// intentionally excluded: reading the retained source is not a mutation.
pub fn private_state_snapshot(file: &File) -> io::Result<PrivateStateSnapshot> {
    let handle = file.as_raw_handle() as HANDLE;
    let mut basic: FILE_BASIC_INFO = unsafe { std::mem::zeroed() };
    let mut identity: FILE_ID_INFO = unsafe { std::mem::zeroed() };
    let mut standard: FILE_STANDARD_INFO = unsafe { std::mem::zeroed() };
    // SAFETY: each fixed-size Win32 buffer is valid and exclusively borrowed
    // for its synchronous call; the owned file remains live throughout.
    let complete = unsafe {
        GetFileInformationByHandleEx(
            handle,
            FileBasicInfo,
            (&mut basic as *mut FILE_BASIC_INFO).cast(),
            size_of::<FILE_BASIC_INFO>() as u32,
        ) != 0
            && GetFileInformationByHandleEx(
                handle,
                FileIdInfo,
                (&mut identity as *mut FILE_ID_INFO).cast(),
                size_of::<FILE_ID_INFO>() as u32,
            ) != 0
            && GetFileInformationByHandleEx(
                handle,
                FileStandardInfo,
                (&mut standard as *mut FILE_STANDARD_INFO).cast(),
                size_of::<FILE_STANDARD_INFO>() as u32,
            ) != 0
    };
    if !complete {
        return Err(io::Error::last_os_error());
    }
    let directory = standard.Directory != 0;
    if basic.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
        || (basic.FileAttributes & FILE_ATTRIBUTE_DIRECTORY != 0) != directory
        || standard.DeletePending != 0
        || !directory && standard.NumberOfLinks != 1
        || standard.EndOfFile < 0
        || standard.AllocationSize < 0
    {
        return Err(unsafe_state("retained private state metadata is unsafe"));
    }
    Ok(PrivateStateSnapshot {
        volume: identity.VolumeSerialNumber,
        file_id: identity.FileId.Identifier,
        attributes: basic.FileAttributes,
        directory,
        links: standard.NumberOfLinks,
        length: standard.EndOfFile as u64,
        allocation: standard.AllocationSize,
        created: basic.CreationTime,
        written: basic.LastWriteTime,
        changed: basic.ChangeTime,
        security: security_snapshot(file)?,
    })
}

fn security_snapshot(file: &File) -> io::Result<SecuritySnapshot> {
    let current_user = CurrentUser::read()?;
    let mut owner = ptr::null_mut();
    let mut dacl: *mut ACL = ptr::null_mut();
    let mut descriptor = ptr::null_mut();
    // GetSecurityInfo returns one LocalFree-owned descriptor. Validate and copy
    // this very descriptor, rather than validating a previous ACL observation.
    let status = unsafe {
        GetSecurityInfo(
            file.as_raw_handle() as HANDLE,
            1,
            OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            &mut owner,
            ptr::null_mut(),
            &mut dacl,
            ptr::null_mut(),
            &mut descriptor,
        )
    };
    let result = (|| {
        if status != ERROR_SUCCESS || descriptor.is_null() || owner.is_null() || dacl.is_null() {
            return Err(unsafe_state("retained private state security is incomplete"));
        }
        // The original private-state owner is authoritative for which ACEs are
        // trusted; recovery neither repairs permissions nor relaxes that policy.
        if unsafe {
            IsValidSid(owner) == 0
                || EqualSid(owner, current_user.sid()) == 0
                || dacl_grants_untrusted_access(dacl, current_user.sid())
        } {
            return Err(unsafe_state("retained private state owner or DACL is unsafe"));
        }
        let mut information: ACL_SIZE_INFORMATION = unsafe { std::mem::zeroed() };
        let mut control = 0_u16;
        let mut revision = 0_u32;
        if unsafe {
            GetAclInformation(
                dacl,
                (&mut information as *mut ACL_SIZE_INFORMATION).cast(),
                size_of::<ACL_SIZE_INFORMATION>() as u32,
                AclSizeInformation,
            ) == 0
                || GetSecurityDescriptorControl(descriptor, &mut control, &mut revision) == 0
        } {
            return Err(io::Error::last_os_error());
        }
        let owner_length = unsafe { GetLengthSid(owner) } as usize;
        let dacl_length = information.AclBytesInUse as usize;
        if owner_length == 0 || dacl_length < size_of::<ACL>() {
            return Err(unsafe_state("retained private security size is invalid"));
        }
        // SAFETY: Win32 validated this descriptor, SID, and exact in-use ACL
        // span above. Copy both before the single LocalFree below.
        let owner = unsafe { std::slice::from_raw_parts(owner.cast::<u8>(), owner_length) }.to_vec();
        let dacl = unsafe { std::slice::from_raw_parts(dacl.cast::<u8>(), dacl_length) }.to_vec();
        Ok(SecuritySnapshot {
            control,
            revision,
            owner,
            dacl,
        })
    })();
    if !descriptor.is_null() {
        unsafe { LocalFree(descriptor as HLOCAL) };
    }
    result
}

#[cfg(test)]
#[path = "private_state_windows_snapshot_tests.rs"]
mod tests;
