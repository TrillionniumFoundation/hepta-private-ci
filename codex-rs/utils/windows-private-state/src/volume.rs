//! Same-handle volume observations, without namespace or private-owner authority.

use crate::mechanism::Identity;
use crate::mechanism::identity;
use std::ffi::c_void;
use std::fs::File;
use std::io;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::ptr;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::NTSTATUS;
use windows_sys::Win32::Foundation::RtlNtStatusToDosError;
use windows_sys::Win32::Storage::FileSystem::FILE_DEVICE_DISK;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::GetVolumeInformationByHandleW;
use windows_sys::Win32::Storage::FileSystem::ReOpenFile;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK_0;

// FILE_FS_DEVICE_INFORMATION and FS_INFORMATION_CLASS, ntifs.h / [MS-FSCC].
const FILE_FS_DEVICE_INFORMATION_CLASS: u32 = 4;
const FILE_REMOTE_DEVICE: u32 = 0x10;
const FILE_PERSISTENT_ACLS: u32 = 0x8;
const SYNCHRONIZE_ACCESS: u32 = 0x0010_0000;

#[repr(C)]
struct DeviceInformation {
    device_type: u32,
    characteristics: u32,
}

#[link(name = "ntdll")]
unsafe extern "system" {
    fn NtQueryVolumeInformationFile(
        file: HANDLE,
        io_status: *mut IO_STATUS_BLOCK,
        information: *mut c_void,
        length: u32,
        information_class: u32,
    ) -> NTSTATUS;
}

/// Facts read from one held object. This is not a trusted-parent capability.
#[derive(Debug, Eq, PartialEq)]
pub struct LocalNtfsObservation {
    pub object: Identity,
    pub filesystem_flags: u32,
    pub device_characteristics: u32,
}

/// Require local NTFS with persistent ACLs on the same held filesystem object.
///
/// A drive letter, filesystem name, or disk device type alone is insufficient.
/// This does not validate an ancestor, owner descriptor, or durability guarantee.
pub fn inspect_local_ntfs(file: &File) -> io::Result<LocalNtfsObservation> {
    let object = identity(file)?;
    // An arbitrary caller File can be overlapped. Reopen the held object itself,
    // without any path lookup, as synchronous (no FILE_FLAG_OVERLAPPED). Sharing
    // here cannot relax the sharing restrictions of the still-live original.
    // SAFETY: the original handle remains borrowed and live through ReOpenFile.
    let raw = unsafe {
        ReOpenFile(
            file.as_raw_handle() as HANDLE,
            FILE_READ_ATTRIBUTES | SYNCHRONIZE_ACCESS,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
        )
    };
    if raw == 0 || raw == INVALID_HANDLE_VALUE {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: successful ReOpenFile transfers one newly owned live handle.
    let synchronous = File::from(unsafe { OwnedHandle::from_raw_handle(raw as *mut c_void) });
    if identity(&synchronous)? != object {
        return Err(io::Error::other("reopened object identity changed"));
    }
    let mut device = DeviceInformation {
        device_type: u32::MAX,
        characteristics: u32::MAX,
    };
    let mut completion = IO_STATUS_BLOCK {
        Anonymous: IO_STATUS_BLOCK_0 { Status: -1 },
        Information: 0,
    };
    // SAFETY: ReOpenFile created a synchronous, non-overlapped handle. The I/O
    // manager completes its operation before this call returns, so both output
    // structures stay live until completion, including an internally pending I/O.
    let status = unsafe {
        NtQueryVolumeInformationFile(
            raw,
            &mut completion,
            ptr::from_mut(&mut device).cast(),
            size_of::<DeviceInformation>() as u32,
            FILE_FS_DEVICE_INFORMATION_CLASS,
        )
    };
    if status < 0 {
        // SAFETY: this conversion accepts the returned NTSTATUS.
        return Err(io::Error::from_raw_os_error(
            unsafe { RtlNtStatusToDosError(status) } as i32,
        ));
    }
    // Only STATUS_SUCCESS and the exact complete, initialized structure count.
    // Informational statuses, short output, and unsupported device types fail.
    if status != 0
        || unsafe { completion.Anonymous.Status } != 0
        || completion.Information != size_of::<DeviceInformation>()
        || device.device_type != FILE_DEVICE_DISK
        || device.characteristics & FILE_REMOTE_DEVICE != 0
    {
        return Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "held object did not report a complete local disk device",
        ));
    }
    let mut serial = 0;
    let mut flags = 0;
    let mut name = [0_u16; 16];
    // SAFETY: raw is still the same live borrowed handle; each output points to
    // initialized storage of its specified capacity. No volume label is requested.
    if unsafe {
        GetVolumeInformationByHandleW(
            raw,
            ptr::null_mut(),
            /*nvolumenamesize*/ 0,
            &mut serial,
            ptr::null_mut(),
            &mut flags,
            name.as_mut_ptr(),
            name.len() as u32,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    let end = name.iter().position(|unit| *unit == 0);
    if end != Some(4)
        || name[..4]
            != [
                u16::from(b'N'),
                u16::from(b'T'),
                u16::from(b'F'),
                u16::from(b'S'),
            ]
        || flags & FILE_PERSISTENT_ACLS == 0
        || serial != object.volume
        || identity(&synchronous)? != object
        || identity(file)? != object
    {
        return Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "held object did not report matching NTFS volume identity and ACLs",
        ));
    }
    Ok(LocalNtfsObservation {
        object,
        filesystem_flags: flags,
        device_characteristics: device.characteristics,
    })
}
