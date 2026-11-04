//! Read-only existing identities for bounded cold recovery.
//!
//! These handles never create or repair a source. Their observations are not
//! current-cut authentication or an independent writer fence.

use super::HandleKind;
use super::child_path;
use super::directory;
use super::final_path;
use super::unsafe_state;
use super::validate_handle;
use std::ffi::c_void;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::mem::size_of;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::path::Component;
use std::path::Path;
use std::path::Prefix;
use std::ptr;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetSecurityDescriptorLength;
use windows_sys::Win32::Security::IsValidSecurityDescriptor;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::CREATE_NEW;
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::FILE_BASIC_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_ID_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_STANDARD_INFO;
use windows_sys::Win32::Storage::FileSystem::FileBasicInfo;
use windows_sys::Win32::Storage::FileSystem::FileIdInfo;
use windows_sys::Win32::Storage::FileSystem::FileStandardInfo;
use windows_sys::Win32::Storage::FileSystem::GetDriveTypeW;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandleEx;
use windows_sys::Win32::Storage::FileSystem::GetVolumeInformationByHandleW;

// GetDriveTypeW's DRIVE_FIXED result (WinBase.h / windows-sys WindowsProgramming).
const DRIVE_FIXED: u32 = 3;

/// One retained object's identity, mutation metadata, owner and DACL.
///
/// Equality excludes access time, which a read may update. This is a bounded
/// observation; callers must revalidate before and after reading retained bytes.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PrivateStateSnapshot {
    volume: u64,
    file_id: [u8; 16],
    attributes: u32,
    links: u32,
    length: i64,
    created: i64,
    written: i64,
    changed: i64,
    descriptor: Vec<u8>,
}

/// Open a pre-existing private directory for inspection, without FILE_OPEN_IF.
pub fn open_existing_private_state_directory(root: &Path) -> io::Result<File> {
    let file = directory::open_existing(root)?;
    validate_handle(&file, HandleKind::Directory)?;
    require_local_ntfs(&file)?;
    Ok(file)
}

/// Retain an existing private directory with the write right needed for a real
/// directory flush. Missing paths and unsafe descriptors are never repaired.
pub fn open_existing_private_state_directory_for_sync(root: &Path) -> io::Result<File> {
    let file = directory::open_existing_writable(root)?;
    validate_handle(&file, HandleKind::Directory)?;
    require_local_ntfs(&file)?;
    Ok(file)
}

/// Open one existing private regular child read-only, with no write/delete
/// sharing. Existing live writers cause refusal rather than a sharing fallback.
pub fn open_frozen_private_state_child(directory: &File, name: &str) -> io::Result<File> {
    require_literal_leaf(name)?;
    let before = private_state_directory_snapshot(directory)?;
    let path = child_path(directory, name)?;
    let file = OpenOptions::new()
        .read(true)
        .share_mode(FILE_SHARE_READ)
        .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
        .open(&path)?;
    validate_handle(&file, HandleKind::File)?;
    let opened = final_path(&file)?;
    if opened.parent() != path.parent()
        || opened.file_name() != path.file_name()
        || private_state_directory_snapshot(directory)? != before
    {
        return Err(unsafe_state(
            "recovery child changed its retained namespace",
        ));
    }
    Ok(file)
}

/// Create a new private materialization leaf. An occupied name is always a
/// failure; this never opens, truncates, repairs or adopts existing state.
pub fn create_new_private_state_child(directory: &File, name: &str) -> io::Result<File> {
    require_literal_leaf(name)?;
    validate_handle(directory, HandleKind::Directory)?;
    let path = child_path(directory, name)?;
    let wide = super::wide_path(&path)?;
    let file = super::with_private_security(|security| {
        let handle = unsafe {
            CreateFileW(
                wide.as_ptr(),
                FILE_GENERIC_READ | FILE_GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                security,
                CREATE_NEW,
                FILE_FLAG_OPEN_REPARSE_POINT,
                0,
            )
        };
        if handle == INVALID_HANDLE_VALUE {
            return Err(io::Error::last_os_error());
        }
        Ok(unsafe { File::from_raw_handle(handle as *mut c_void) })
    })?;
    validate_handle(&file, HandleKind::File)?;
    validate_handle(directory, HandleKind::Directory)?;
    let opened = final_path(&file)?;
    if opened.parent() != path.parent() || opened.file_name() != path.file_name() {
        return Err(unsafe_state(
            "materialized child escaped its retained directory",
        ));
    }
    Ok(file)
}

fn require_literal_leaf(name: &str) -> io::Result<()> {
    if name.is_empty()
        || name.encode_utf16().count() > 255
        || matches!(name, "." | "..")
        || (name.ends_with('.') || name.ends_with(' '))
        || name
            .chars()
            .any(|character| matches!(character, '\0' | '/' | '\\' | ':'))
    {
        return Err(unsafe_state(
            "recovery child must be one literal normal leaf",
        ));
    }
    Ok(())
}

/// Observe a retained private directory without changing its permissions.
pub fn private_state_directory_snapshot(file: &File) -> io::Result<PrivateStateSnapshot> {
    snapshot(file, HandleKind::Directory)
}

/// Observe a retained private regular file without changing its permissions.
pub fn private_state_file_snapshot(file: &File) -> io::Result<PrivateStateSnapshot> {
    snapshot(file, HandleKind::File)
}

fn require_local_ntfs(file: &File) -> io::Result<()> {
    let path = final_path(file)?;
    let drive = match path.components().next() {
        Some(Component::Prefix(prefix)) => match prefix.kind() {
            Prefix::Disk(drive) | Prefix::VerbatimDisk(drive) => drive,
            _ => return Err(unsafe_state("recovery requires a local NTFS volume")),
        },
        _ => return Err(unsafe_state("recovery requires an absolute disk path")),
    };
    let root = [u16::from(drive), u16::from(b':'), u16::from(b'\\'), 0];
    // The real handle's filesystem and its resolved drive must both qualify.
    // A UNC or mapped network drive never becomes a local recovery source.
    if unsafe { GetDriveTypeW(root.as_ptr()) } != DRIVE_FIXED {
        return Err(unsafe_state("recovery requires a fixed local volume"));
    }
    let mut filesystem = [0_u16; 32];
    let result = unsafe {
        GetVolumeInformationByHandleW(
            file.as_raw_handle() as HANDLE,
            ptr::null_mut(),
            0,
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
            filesystem.as_mut_ptr(),
            filesystem.len() as u32,
        )
    };
    if result == 0 {
        return Err(io::Error::last_os_error());
    }
    let length = filesystem
        .iter()
        .position(|unit| *unit == 0)
        .unwrap_or(filesystem.len());
    if !String::from_utf16_lossy(&filesystem[..length]).eq_ignore_ascii_case("NTFS") {
        return Err(unsafe_state("recovery requires the retained NTFS object"));
    }
    Ok(())
}

fn snapshot(file: &File, kind: HandleKind) -> io::Result<PrivateStateSnapshot> {
    validate_handle(file, kind)?;
    let mut basic: FILE_BASIC_INFO = unsafe { std::mem::zeroed() };
    let mut standard: FILE_STANDARD_INFO = unsafe { std::mem::zeroed() };
    let mut identity: FILE_ID_INFO = unsafe { std::mem::zeroed() };
    // All buffers are initialized, correctly aligned fixed Win32 structures.
    for (class, buffer, size) in [
        (
            FileBasicInfo,
            (&mut basic as *mut FILE_BASIC_INFO).cast::<c_void>(),
            size_of::<FILE_BASIC_INFO>(),
        ),
        (
            FileStandardInfo,
            (&mut standard as *mut FILE_STANDARD_INFO).cast::<c_void>(),
            size_of::<FILE_STANDARD_INFO>(),
        ),
        (
            FileIdInfo,
            (&mut identity as *mut FILE_ID_INFO).cast::<c_void>(),
            size_of::<FILE_ID_INFO>(),
        ),
    ] {
        if unsafe {
            GetFileInformationByHandleEx(file.as_raw_handle() as HANDLE, class, buffer, size as u32)
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
    }
    if standard.DeletePending != 0 || standard.EndOfFile < 0 {
        return Err(unsafe_state(
            "recovery object is deleted or has invalid length",
        ));
    }
    struct Descriptor(*mut c_void);
    impl Drop for Descriptor {
        fn drop(&mut self) {
            if !self.0.is_null() {
                unsafe { LocalFree(self.0) };
            }
        }
    }
    let mut raw = ptr::null_mut();
    let code = unsafe {
        GetSecurityInfo(
            file.as_raw_handle() as HANDLE,
            1,
            OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
            &mut raw,
        )
    };
    let descriptor = Descriptor(raw);
    if code != 0 || descriptor.0.is_null() {
        return Err(unsafe_state("recovery descriptor read failed"));
    }
    let length = unsafe { GetSecurityDescriptorLength(descriptor.0) } as usize;
    if !(20..=1_048_576).contains(&length)
        || unsafe { IsValidSecurityDescriptor(descriptor.0) } == 0
    {
        return Err(unsafe_state("recovery descriptor is malformed"));
    }
    let bytes = unsafe { std::slice::from_raw_parts(descriptor.0.cast::<u8>(), length) }.to_vec();
    validate_handle(file, kind)?;
    Ok(PrivateStateSnapshot {
        volume: identity.VolumeSerialNumber,
        file_id: identity.FileId.Identifier,
        attributes: basic.FileAttributes,
        links: standard.NumberOfLinks,
        length: standard.EndOfFile,
        created: basic.CreationTime,
        written: basic.LastWriteTime,
        changed: basic.ChangeTime,
        descriptor: bytes,
    })
}

#[cfg(test)]
#[path = "private_state_windows_recovery_tests.rs"]
mod tests;
