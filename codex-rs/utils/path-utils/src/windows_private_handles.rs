use std::ffi::c_void;
use std::fs::File;
use std::io;
use std::mem::size_of;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Component;
use std::path::Path;
use std::path::Prefix;
use std::ptr;

use windows_sys::Win32::Foundation::GENERIC_READ;
use windows_sys::Win32::Foundation::GENERIC_WRITE;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::NTSTATUS;
use windows_sys::Win32::Foundation::RtlNtStatusToDosError;
use windows_sys::Win32::Foundation::UNICODE_STRING;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ADD_FILE;
use windows_sys::Win32::Storage::FileSystem::FILE_ADD_SUBDIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_NORMAL;
use windows_sys::Win32::Storage::FileSystem::FILE_DISPOSITION_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_LIST_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_EA;
use windows_sys::Win32::Storage::FileSystem::FILE_RENAME_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_TRAVERSE;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_EA;
use windows_sys::Win32::Storage::FileSystem::FileDispositionInfo;
use windows_sys::Win32::Storage::FileSystem::FileRenameInfoEx;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::SetFileInformationByHandle;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK;
use windows_sys::Win32::System::Kernel::OBJ_CASE_INSENSITIVE;
use windows_sys::Win32::System::Kernel::OBJ_DONT_REPARSE;
use windows_sys::Win32::System::WindowsProgramming::FILE_RENAME_FLAG_POSIX_SEMANTICS;
use windows_sys::Win32::System::WindowsProgramming::FILE_RENAME_FLAG_REPLACE_IF_EXISTS;

use super::Access;

const FILE_DIRECTORY_FILE: u32 = 1;
const FILE_NON_DIRECTORY_FILE: u32 = 0x40;
const FILE_OPEN: u32 = 1;
const FILE_CREATE: u32 = 2;
const FILE_OPEN_IF: u32 = 3;
const FILE_SYNCHRONOUS_IO_NONALERT: u32 = 0x20;
const FILE_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
const SYNCHRONIZE: u32 = 0x0010_0000;

#[repr(C)]
struct ObjectAttributes {
    length: u32,
    root_directory: HANDLE,
    object_name: *const UNICODE_STRING,
    attributes: u32,
    security_descriptor: *const c_void,
    security_quality_of_service: *const c_void,
}

#[link(name = "ntdll")]
unsafe extern "system" {
    fn NtCreateFile(
        handle: *mut HANDLE,
        desired_access: u32,
        attributes: *const ObjectAttributes,
        status: *mut IO_STATUS_BLOCK,
        allocation_size: *const i64,
        file_attributes: u32,
        share_access: u32,
        disposition: u32,
        options: u32,
        ea: *const c_void,
        ea_length: u32,
    ) -> NTSTATUS;
}

pub(super) fn directory(path: &Path, descriptor: *const c_void) -> io::Result<File> {
    directory_with(path, descriptor, DirectoryMode::Prepare)
}

#[derive(Clone, Copy)]
pub(super) enum DirectoryMode {
    Prepare,
    ReadOnlyExisting,
    WritableExisting,
}

pub(super) fn directory_with(
    path: &Path,
    descriptor: *const c_void,
    mode: DirectoryMode,
) -> io::Result<File> {
    if !path.is_absolute()
        || path
            .components()
            .any(|item| matches!(item, Component::ParentDir))
    {
        return Err(invalid_name());
    }
    let skip = match path.components().next() {
        Some(Component::Prefix(prefix)) => match prefix.kind() {
            Prefix::Disk(_) => 0,
            Prefix::VerbatimDisk(_) => 4,
            _ => return Err(invalid_name()),
        },
        _ => return Err(invalid_name()),
    };
    let mut name: Vec<u16> = "\\??\\".encode_utf16().collect();
    name.extend(path.as_os_str().encode_wide().skip(skip).map(|unit| {
        if unit == b'/' as u16 {
            b'\\' as u16
        } else {
            unit
        }
    }));
    let rights =
        FILE_LIST_DIRECTORY | FILE_TRAVERSE | FILE_READ_ATTRIBUTES | FILE_READ_EA | READ_CONTROL;
    let (rights, disposition) = match mode {
        DirectoryMode::ReadOnlyExisting => (rights, FILE_OPEN),
        DirectoryMode::Prepare | DirectoryMode::WritableExisting => (
            rights | FILE_ADD_FILE | FILE_ADD_SUBDIRECTORY | FILE_WRITE_ATTRIBUTES | FILE_WRITE_EA,
            if matches!(mode, DirectoryMode::Prepare) {
                FILE_OPEN_IF
            } else {
                FILE_OPEN
            },
        ),
    };
    open(
        /*root*/ 0,
        &mut name,
        // Spell out directory-specific rights. FILE_ADD_FILE supplies the
        // directory write right required by the real flush and child creation.
        rights,
        disposition,
        FILE_DIRECTORY_FILE,
        descriptor,
    )
}

pub(super) fn child(
    directory: &File,
    name: &str,
    access: Access,
    descriptor: *const c_void,
) -> io::Result<File> {
    let mut name = leaf(name)?;
    let (rights, disposition) = match access {
        Access::Read => (GENERIC_READ, FILE_OPEN),
        Access::Write => (GENERIC_READ | GENERIC_WRITE | DELETE, FILE_OPEN),
        Access::Create => (GENERIC_READ | GENERIC_WRITE | DELETE, FILE_OPEN_IF),
        Access::CreateNew => (GENERIC_READ | GENERIC_WRITE | DELETE, FILE_CREATE),
    };
    open(
        directory.as_raw_handle() as _,
        &mut name,
        rights,
        disposition,
        FILE_NON_DIRECTORY_FILE,
        descriptor,
    )
}

fn open(
    root: HANDLE,
    name: &mut [u16],
    rights: u32,
    disposition: u32,
    kind: u32,
    descriptor: *const c_void,
) -> io::Result<File> {
    if name.contains(&0) {
        return Err(invalid_name());
    }
    let length = u16::try_from(std::mem::size_of_val(name)).map_err(|_| invalid_name())?;
    let unicode = UNICODE_STRING {
        Length: length,
        MaximumLength: length,
        Buffer: name.as_mut_ptr(),
    };
    let attributes = ObjectAttributes {
        length: size_of::<ObjectAttributes>() as u32,
        root_directory: root,
        object_name: &unicode,
        attributes: OBJ_CASE_INSENSITIVE as u32 | OBJ_DONT_REPARSE as u32,
        security_descriptor: descriptor,
        security_quality_of_service: ptr::null(),
    };
    // SAFETY: All-zero IO_STATUS_BLOCK is valid output storage.
    let mut status = unsafe { std::mem::zeroed() };
    let mut handle = 0;
    let share = if kind == FILE_DIRECTORY_FILE {
        // Retain the directory's namespace binding as well as its handle.
        FILE_SHARE_READ | FILE_SHARE_WRITE
    } else {
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
    };
    // NtCreateFile's closed FILE_DIRECTORY_FILE compatibility list excludes
    // FILE_OPEN_REPARSE_POINT. OBJ_DONT_REPARSE remains set for every name
    // lookup; the returned handle is also checked for the reparse attribute.
    let options = if kind == FILE_DIRECTORY_FILE {
        kind | FILE_SYNCHRONOUS_IO_NONALERT
    } else {
        kind | FILE_SYNCHRONOUS_IO_NONALERT | FILE_OPEN_REPARSE_POINT
    };
    // SAFETY: All referenced buffers/descriptors stay live for this synchronous
    // call. No handle inheritance or backup/restore privilege is requested.
    let result = unsafe {
        NtCreateFile(
            &mut handle,
            rights | SYNCHRONIZE,
            &attributes,
            &mut status,
            ptr::null(),
            FILE_ATTRIBUTE_NORMAL,
            share,
            disposition,
            options,
            ptr::null(),
            /*ea_length*/ 0,
        )
    };
    if result < 0 {
        // SAFETY: The conversion accepts any NTSTATUS and owns no memory.
        return Err(io::Error::from_raw_os_error(
            unsafe { RtlNtStatusToDosError(result) } as i32,
        ));
    }
    if handle == 0 || handle == INVALID_HANDLE_VALUE {
        return Err(io::Error::other("NtCreateFile returned an invalid handle"));
    }
    // SAFETY: This successful call returned a fresh owned, non-null handle.
    Ok(File::from(unsafe {
        OwnedHandle::from_raw_handle(handle as _)
    }))
}

pub(super) fn replace(directory: &File, file: &File, destination: &str) -> io::Result<()> {
    let name = leaf(destination)?;
    // Include the complete header even for a one-character leaf: the flexible
    // array offset alone is smaller than sizeof(FILE_RENAME_INFO) on Win32/64.
    let bytes = size_of::<FILE_RENAME_INFO>() + name.len() * size_of::<u16>();
    // usize storage supplies the alignment required by FILE_RENAME_INFO. The
    // extra trailing zero also permits APIs that inspect a UTF-16 terminator.
    let mut buffer = vec![0_usize; (bytes + size_of::<u16>()).div_ceil(size_of::<usize>())];
    let info = buffer.as_mut_ptr().cast::<FILE_RENAME_INFO>();
    // SAFETY: The aligned allocation includes the header and complete flexible
    // filename array; both borrowed handles remain open throughout the call.
    unsafe {
        // Preserve Unix-style old-reader semantics explicitly. Unsupported
        // Windows/filesystem versions fail; there is no weaker rename fallback.
        (*info).Anonymous.Flags =
            FILE_RENAME_FLAG_REPLACE_IF_EXISTS | FILE_RENAME_FLAG_POSIX_SEMANTICS;
        (*info).RootDirectory = directory.as_raw_handle() as _;
        (*info).FileNameLength = (name.len() * size_of::<u16>()) as u32;
        ptr::copy_nonoverlapping(
            name.as_ptr(),
            ptr::addr_of_mut!((*info).FileName).cast(),
            name.len(),
        );
        if SetFileInformationByHandle(
            file.as_raw_handle() as _,
            FileRenameInfoEx,
            info.cast(),
            bytes as u32,
        ) == 0
        {
            return Err(io::Error::last_os_error());
        }
    }
    Ok(())
}

pub(super) fn remove(file: File) -> io::Result<()> {
    let information = FILE_DISPOSITION_INFO { DeleteFile: 1 };
    // SAFETY: The input matches FileDispositionInfo and the owned handle stays
    // live until the call completes. Deletion binds this object, not a pathname.
    if unsafe {
        SetFileInformationByHandle(
            file.as_raw_handle() as _,
            FileDispositionInfo,
            ptr::addr_of!(information).cast(),
            size_of::<FILE_DISPOSITION_INFO>() as u32,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

fn leaf(name: &str) -> io::Result<Vec<u16>> {
    if name.is_empty()
        || name == "."
        || name == ".."
        || name.len() > 255
        || !name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    {
        return Err(invalid_name());
    }
    Ok(name.encode_utf16().collect())
}

fn invalid_name() -> io::Error {
    io::Error::new(
        io::ErrorKind::InvalidInput,
        "private storage requires a local absolute root and a bounded single-component child name",
    )
}
