//! Private, handle-relative durable state on local Windows NTFS volumes.
//!
//! The directory and every file have an explicit, protected, current-user-only
//! DACL. Existing insecure objects are rejected, never silently repaired. Child
//! opens and replacements are relative to the pinned directory handle. Reparse
//! points, hard-linked files and remote/unsupported volumes fail closed.
//!
//! Callers must sync the written file before `replace`, then call `sync_all` on
//! the returned directory. A failed post-rename sync is an indeterminate commit;
//! this module never turns an unsupported flush into a successful commit.

mod security;

use std::fs::File;
use std::io;
use std::mem::offset_of;
use std::mem::size_of;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::path::Path;
use std::ptr;
use windows_sys::Wdk::Foundation::OBJECT_ATTRIBUTES;
use windows_sys::Wdk::Storage::FileSystem::FILE_NON_DIRECTORY_FILE;
use windows_sys::Wdk::Storage::FileSystem::FILE_OPEN;
use windows_sys::Wdk::Storage::FileSystem::FILE_OPEN_IF;
use windows_sys::Wdk::Storage::FileSystem::FILE_OPEN_REPARSE_POINT;
use windows_sys::Wdk::Storage::FileSystem::FILE_RENAME_INFORMATION;
use windows_sys::Wdk::Storage::FileSystem::FILE_SYNCHRONOUS_IO_NONALERT;
use windows_sys::Wdk::Storage::FileSystem::FILE_WRITE_THROUGH;
use windows_sys::Wdk::Storage::FileSystem::FileFsDeviceInformation;
use windows_sys::Wdk::Storage::FileSystem::FileRenameInformation;
use windows_sys::Wdk::Storage::FileSystem::NtCreateFile;
use windows_sys::Wdk::Storage::FileSystem::NtQueryVolumeInformationFile;
use windows_sys::Wdk::Storage::FileSystem::NtSetInformationFile;
use windows_sys::Wdk::Storage::FileSystem::RtlNtStatusToDosErrorNoTeb;
use windows_sys::Wdk::System::SystemServices::FILE_FS_DEVICE_INFORMATION;
use windows_sys::Wdk::System::SystemServices::FILE_REMOTE_DEVICE;
use windows_sys::Win32::Foundation::ERROR_ALREADY_EXISTS;
use windows_sys::Win32::Foundation::GENERIC_READ;
use windows_sys::Win32::Foundation::GENERIC_WRITE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::OBJ_CASE_INSENSITIVE;
use windows_sys::Win32::Foundation::OBJ_DONT_REPARSE;
use windows_sys::Win32::Foundation::UNICODE_STRING;
use windows_sys::Win32::Storage::FileSystem::BY_HANDLE_FILE_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::CreateDirectoryW;
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_NORMAL;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_WRITE_THROUGH;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandle;
use windows_sys::Win32::Storage::FileSystem::GetVolumeInformationByHandleW;
use windows_sys::Win32::Storage::FileSystem::OPEN_EXISTING;
use windows_sys::Win32::Storage::FileSystem::SYNCHRONIZE;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK;
use windows_sys::Win32::System::SystemServices::FILE_PERSISTENT_ACLS;

/// Opening an existing file never truncates it or changes its security.
#[derive(Clone, Copy)]
pub enum Access {
    Read,
    Write,
    Create,
}

#[derive(Clone, Copy, PartialEq)]
enum EntryKind {
    Directory,
    File,
}

/// Create a private directory if absent, or validate and pin an existing one.
pub fn prepare_directory(root: &Path) -> io::Result<File> {
    let name = wide_path(root)?;
    let descriptor = security::Descriptor::current_user()?;
    let attributes = descriptor.attributes();
    // SAFETY: both pointers remain valid, NUL terminated and owned for the call.
    if unsafe { CreateDirectoryW(name.as_ptr(), &attributes) } == 0 {
        let error = io::Error::last_os_error();
        if error.raw_os_error() != Some(ERROR_ALREADY_EXISTS as i32) {
            return Err(error);
        }
    }
    // GENERIC_WRITE is required by FlushFileBuffers (File::sync_all). Opening a
    // directory read-only and ignoring its flush failure would lose durability.
    // SAFETY: the API borrows the live path and returns one newly owned handle.
    let handle = unsafe {
        CreateFileW(
            name.as_ptr(),
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            ptr::null(),
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_WRITE_THROUGH,
            ptr::null_mut(),
        )
    };
    if handle == INVALID_HANDLE_VALUE {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: CreateFileW succeeded; this is the sole owner of its handle.
    let directory = unsafe { File::from_raw_handle(handle) };
    validate(&directory, EntryKind::Directory)?;
    validate_local_ntfs(&directory)?;
    // Refuse an unusable durability backend before any authoritative mutation.
    directory.sync_all()?;
    Ok(directory)
}

/// Open one regular, private, unlinked-by-any-other-name state file.
pub fn open_private(directory: &File, name: &str, access: Access) -> io::Result<File> {
    validate(directory, EntryKind::Directory)?;
    let mut name = component(name)?;
    let byte_length = u16::try_from(name.len() * size_of::<u16>())
        .map_err(|_| unsafe_state("state name exceeds the NT path limit"))?;
    let object_name = UNICODE_STRING {
        Length: byte_length,
        MaximumLength: byte_length,
        Buffer: name.as_mut_ptr(),
    };
    let descriptor = security::Descriptor::current_user()?;
    let attributes = OBJECT_ATTRIBUTES {
        Length: size_of::<OBJECT_ATTRIBUTES>() as u32,
        RootDirectory: directory.as_raw_handle(),
        ObjectName: &object_name,
        Attributes: OBJ_CASE_INSENSITIVE | OBJ_DONT_REPARSE,
        SecurityDescriptor: descriptor.as_ptr().cast(),
        SecurityQualityOfService: ptr::null(),
    };
    let (rights, disposition) = match access {
        Access::Read => (GENERIC_READ, FILE_OPEN),
        Access::Write => (GENERIC_READ | GENERIC_WRITE | DELETE, FILE_OPEN),
        Access::Create => (GENERIC_READ | GENERIC_WRITE | DELETE, FILE_OPEN_IF),
    };
    let mut handle = ptr::null_mut();
    let mut status_block = IO_STATUS_BLOCK::default();
    // SAFETY: all buffers and borrowed handles remain live. Synchronous I/O
    // prevents the kernel from retaining pointers after this call returns.
    let status = unsafe {
        NtCreateFile(
            &mut handle,
            rights | SYNCHRONIZE,
            &attributes,
            &mut status_block,
            ptr::null(),
            FILE_ATTRIBUTE_NORMAL,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            disposition,
            FILE_NON_DIRECTORY_FILE
                | FILE_OPEN_REPARSE_POINT
                | FILE_SYNCHRONOUS_IO_NONALERT
                | FILE_WRITE_THROUGH,
            ptr::null(),
            /*ealength*/ 0,
        )
    };
    nt_result(status)?;
    if handle.is_null() || handle == INVALID_HANDLE_VALUE {
        return Err(unsafe_state("native open returned no file handle"));
    }
    // SAFETY: NtCreateFile succeeded and transferred this handle to the caller.
    let file = unsafe { File::from_raw_handle(handle) };
    validate(&file, EntryKind::File)?;
    Ok(file)
}

/// Errors, including insecure existing entries, must not look like absence.
pub fn entry_exists(directory: &File, name: &str) -> io::Result<bool> {
    match open_private(directory, name, Access::Read) {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error),
    }
}

/// Atomically replace one entry in the pinned directory with another.
///
/// The caller still owns the post-rename directory sync and its error semantics.
pub fn replace(directory: &File, source: &str, destination: &str) -> io::Result<()> {
    let source = open_private(directory, source, Access::Write)?;
    entry_exists(directory, destination)?;
    let destination = component(destination)?;
    let header_length = offset_of!(FILE_RENAME_INFORMATION, FileName);
    let byte_length = destination.len() * size_of::<u16>();
    let allocation_length = size_of::<FILE_RENAME_INFORMATION>() + byte_length;
    // usize backing storage supplies the alignment required by the native ABI.
    let mut buffer = vec![0usize; allocation_length.div_ceil(size_of::<usize>())];
    let information = buffer.as_mut_ptr().cast::<FILE_RENAME_INFORMATION>();
    // SAFETY: the aligned allocation contains the full fixed header and variable
    // UTF-16 tail. No Rust reference to its one-element tail is formed.
    unsafe {
        (*information).Anonymous.ReplaceIfExists = true;
        (*information).RootDirectory = directory.as_raw_handle();
        (*information).FileNameLength = byte_length as u32;
        ptr::copy_nonoverlapping(
            destination.as_ptr(),
            buffer.as_mut_ptr().cast::<u8>().add(header_length).cast(),
            destination.len(),
        );
    }
    let mut status_block = IO_STATUS_BLOCK::default();
    // SAFETY: source was opened with DELETE and synchronous I/O. The directory
    // and rename buffer remain live for the entire synchronous operation.
    nt_result(unsafe {
        NtSetInformationFile(
            source.as_raw_handle(),
            &mut status_block,
            information.cast(),
            allocation_length as u32,
            FileRenameInformation,
        )
    })
}

fn validate(file: &File, kind: EntryKind) -> io::Result<()> {
    let mut information = BY_HANDLE_FILE_INFORMATION::default();
    // SAFETY: the output is fully sized and the borrowed handle remains valid.
    if unsafe { GetFileInformationByHandle(file.as_raw_handle(), &mut information) } == 0 {
        return Err(io::Error::last_os_error());
    }
    let attributes = information.dwFileAttributes;
    if attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
        || (attributes & FILE_ATTRIBUTE_DIRECTORY != 0) != (kind == EntryKind::Directory)
        || (kind == EntryKind::File && information.nNumberOfLinks != 1)
    {
        return Err(unsafe_state(
            "reparse point, wrong type or hard-linked state",
        ));
    }
    security::validate_private(file)
}

fn validate_local_ntfs(directory: &File) -> io::Result<()> {
    let mut device = FILE_FS_DEVICE_INFORMATION::default();
    let mut status_block = IO_STATUS_BLOCK::default();
    // SAFETY: the sized output and directory handle are live until completion.
    nt_result(unsafe {
        NtQueryVolumeInformationFile(
            directory.as_raw_handle(),
            &mut status_block,
            (&raw mut device).cast(),
            size_of::<FILE_FS_DEVICE_INFORMATION>() as u32,
            FileFsDeviceInformation,
        )
    })?;
    let mut name = [0u16; 32];
    let mut flags = 0;
    // SAFETY: optional outputs are null; the filesystem-name buffer is sized.
    if unsafe {
        GetVolumeInformationByHandleW(
            directory.as_raw_handle(),
            ptr::null_mut(),
            /*nvolumenamesize*/ 0,
            ptr::null_mut(),
            ptr::null_mut(),
            &mut flags,
            name.as_mut_ptr(),
            name.len() as u32,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    if device.Characteristics & FILE_REMOTE_DEVICE != 0
        || flags & FILE_PERSISTENT_ACLS == 0
        || !name.starts_with(&[b'N' as u16, b'T' as u16, b'F' as u16, b'S' as u16, 0])
    {
        return Err(unsafe_state("private durable state requires local NTFS"));
    }
    Ok(())
}

fn component(name: &str) -> io::Result<Vec<u16>> {
    if name.is_empty()
        || name == "."
        || name == ".."
        || name.ends_with(['.', ' '])
        || name.contains(['\\', '/', ':', '\0'])
        || name.encode_utf16().count() > 255
    {
        return Err(unsafe_state(
            "state entry must be a single unambiguous component",
        ));
    }
    Ok(name.encode_utf16().collect())
}

fn wide_path(path: &Path) -> io::Result<Vec<u16>> {
    let mut name: Vec<u16> = path.as_os_str().encode_wide().collect();
    if name.is_empty() || name.contains(&0) {
        return Err(unsafe_state("invalid state directory path"));
    }
    name.push(0);
    Ok(name)
}

fn nt_result(status: i32) -> io::Result<()> {
    if status >= 0 {
        Ok(())
    } else {
        // SAFETY: this pure OS mapping accepts every NTSTATUS value.
        Err(io::Error::from_raw_os_error(unsafe {
            RtlNtStatusToDosErrorNoTeb(status) as i32
        }))
    }
}

fn unsafe_state(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::PermissionDenied, message)
}

#[cfg(test)]
#[path = "private_state_tests.rs"]
mod tests;
