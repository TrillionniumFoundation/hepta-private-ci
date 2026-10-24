//! Actual same-object parent flush mechanism, never a namespace admission.

use crate::mechanism::identity;
use crate::volume::inspect_local_ntfs;
use std::fs::File;
use std::io;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::ptr;
use windows_sys::Win32::Foundation::GetHandleInformation;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_ID_DESCRIPTOR;
use windows_sys::Win32::Storage::FileSystem::FILE_ID_DESCRIPTOR_0;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FileIdType;
use windows_sys::Win32::Storage::FileSystem::OpenFileById;

pub(crate) fn flush_held_namespace(original: &File) -> io::Result<()> {
    let before = identity(original)?;
    if before.attributes & FILE_ATTRIBUTE_DIRECTORY == 0
        || before.attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "namespace flush requires an ordinary held directory",
        ));
    }
    let id = FILE_ID_DESCRIPTOR {
        dwSize: size_of::<FILE_ID_DESCRIPTOR>() as u32,
        Type: FileIdType,
        Anonymous: FILE_ID_DESCRIPTOR_0 {
            FileId: before.file_id as i64,
        },
    };
    // SAFETY: both the volume hint and the ID derive from the same retained
    // kernel object. NULL security attributes cannot make this handle inherited.
    // No DELETE access/sharing or OVERLAPPED flag is requested, and no pathname,
    // fallback, global-volume flush or alternate share mode is attempted.
    let raw = unsafe {
        OpenFileById(
            original.as_raw_handle() as HANDLE,
            &id,
            FILE_GENERIC_WRITE | FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            ptr::null(),
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
        )
    };
    if raw == 0 || raw == INVALID_HANDLE_VALUE {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: successful OpenFileById transferred this one newly owned handle.
    let writer = File::from(unsafe { OwnedHandle::from_raw_handle(raw as _) });
    let mut flags = u32::MAX;
    // SAFETY: the owned writer stays live throughout this fixed-size query.
    if unsafe { GetHandleInformation(raw, &mut flags) } == 0 {
        return Err(io::Error::last_os_error());
    }
    if flags != 0
        || identity(&writer)? != before
        || identity(original)? != before
        || inspect_local_ntfs(&writer)?.object != before
    {
        return Err(io::Error::other(
            "parent write handle identity or volume changed",
        ));
    }
    writer.sync_all()?;
    if identity(&writer)? != before
        || identity(original)? != before
        || inspect_local_ntfs(&writer)?.object != before
    {
        return Err(io::Error::other(
            "parent identity or volume changed after native flush",
        ));
    }
    Ok(())
}
