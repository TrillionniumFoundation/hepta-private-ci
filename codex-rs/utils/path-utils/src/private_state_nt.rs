//! Narrow NT file operations relative to a pinned directory handle.

use std::ffi::c_void;
use std::fs::File;
use std::io;
use std::mem::MaybeUninit;
use std::mem::offset_of;
use std::mem::size_of;
use std::mem::size_of_val;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::ptr;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::NTSTATUS;
use windows_sys::Win32::Foundation::RtlNtStatusToDosError;
use windows_sys::Win32::Foundation::UNICODE_STRING;
use windows_sys::Win32::Storage::FileSystem::BY_HANDLE_FILE_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_NORMAL;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_TRAVERSE;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandle;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK_0;
use windows_sys::Win32::System::Kernel::OBJ_CASE_INSENSITIVE;
use windows_sys::Win32::System::Kernel::OBJ_DONT_REPARSE;

const FILE_OPEN: u32 = 1;
const FILE_CREATE: u32 = 2;
const FILE_OPEN_IF: u32 = 3;
const FILE_DIRECTORY_FILE: u32 = 1;
const FILE_NON_DIRECTORY_FILE: u32 = 0x40;
const FILE_SYNCHRONOUS_IO_NONALERT: u32 = 0x20;
const FILE_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
const FILE_RENAME_INFORMATION: u32 = 10;

#[derive(Clone, Copy)]
pub(super) enum EntryKind {
    Directory,
    File,
}

#[derive(Clone, Copy)]
pub(super) enum Access {
    Read,
    /// Existing, read-only source; regular files deny sharing for writes/deletes.
    RetainRead,
    WriteExisting,
    Create,
    CreateNew,
}

#[repr(C)]
struct ObjectAttributes {
    length: u32,
    root_directory: HANDLE,
    object_name: *const UNICODE_STRING,
    attributes: u32,
    security_descriptor: *const c_void,
    security_quality_of_service: *const c_void,
}

#[repr(C)]
struct RenameInformation {
    replace_if_exists: u8,
    root_directory: HANDLE,
    file_name_length: u32,
    file_name: [u16; 1],
}

#[link(name = "ntdll")]
unsafe extern "system" {
    fn NtCreateFile(
        file_handle: *mut HANDLE,
        desired_access: u32,
        object_attributes: *const ObjectAttributes,
        io_status_block: *mut IO_STATUS_BLOCK,
        allocation_size: *const i64,
        file_attributes: u32,
        share_access: u32,
        create_disposition: u32,
        create_options: u32,
        ea_buffer: *const c_void,
        ea_length: u32,
    ) -> NTSTATUS;
    fn NtQueryVolumeInformationFile(
        file_handle: HANDLE,
        io_status_block: *mut IO_STATUS_BLOCK,
        information: *mut c_void,
        length: u32,
        information_class: u32,
    ) -> NTSTATUS;
    fn NtSetInformationFile(
        file_handle: HANDLE,
        io_status_block: *mut IO_STATUS_BLOCK,
        file_information: *const c_void,
        length: u32,
        information_class: u32,
    ) -> NTSTATUS;
}

pub(super) fn open(
    root: Option<&File>,
    name: &[u16],
    descriptor: *const c_void,
    kind: EntryKind,
    access: Access,
) -> io::Result<File> {
    let bytes = u16::try_from(name.len() * size_of::<u16>()).map_err(|_| super::invalid_path())?;
    let mut name = name.to_vec();
    let object_name = UNICODE_STRING {
        Length: bytes,
        MaximumLength: bytes,
        Buffer: name.as_mut_ptr(),
    };
    let attributes = ObjectAttributes {
        length: size_of::<ObjectAttributes>() as u32,
        root_directory: root.map_or(0, |file| file.as_raw_handle() as HANDLE),
        object_name: &object_name,
        attributes: OBJ_CASE_INSENSITIVE as u32 | OBJ_DONT_REPARSE as u32,
        security_descriptor: descriptor,
        security_quality_of_service: ptr::null(),
    };
    let (kind_flag, sharing) = match kind {
        EntryKind::Directory => (FILE_DIRECTORY_FILE, FILE_SHARE_READ | FILE_SHARE_WRITE),
        EntryKind::File => (
            FILE_NON_DIRECTORY_FILE,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        ),
    };
    let (desired_access, disposition) = match access {
        Access::Read | Access::RetainRead => (FILE_GENERIC_READ, FILE_OPEN),
        Access::WriteExisting => (FILE_ALL_ACCESS, FILE_OPEN),
        Access::Create => (FILE_ALL_ACCESS, FILE_OPEN_IF),
        Access::CreateNew => (FILE_ALL_ACCESS, FILE_CREATE),
    };
    let sharing = if matches!((kind, access), (EntryKind::File, Access::RetainRead)) {
        FILE_SHARE_READ
    } else {
        sharing
    };
    // Root handles prevent renaming the directory without requesting DELETE
    // themselves, so another owner can open it and observe the file-lock fence.
    let desired_access = match kind {
        EntryKind::Directory if matches!(access, Access::RetainRead) => {
            (desired_access | FILE_TRAVERSE) & !DELETE
        }
        EntryKind::Directory => desired_access & !DELETE,
        EntryKind::File => desired_access,
    };
    let mut status_block = IO_STATUS_BLOCK {
        Anonymous: IO_STATUS_BLOCK_0 { Status: 0 },
        Information: 0,
    };
    let mut handle = 0;
    // SAFETY: All structures and counted UTF-16 buffers outlive this synchronous
    // call. The root is borrowed from a live File, and descriptor is an immutable
    // owner descriptor retained by the sole private caller through this call.
    let status = unsafe {
        NtCreateFile(
            &mut handle,
            desired_access,
            &attributes,
            &mut status_block,
            ptr::null(),
            FILE_ATTRIBUTE_NORMAL,
            sharing,
            disposition,
            kind_flag | FILE_SYNCHRONOUS_IO_NONALERT | FILE_OPEN_REPARSE_POINT,
            ptr::null(),
            /*ea_length*/ 0,
        )
    };
    status_result(status)?;
    if handle == 0 || handle == INVALID_HANDLE_VALUE {
        return Err(io::Error::other("invalid private state handle"));
    }
    // SAFETY: Success transferred one valid owned handle; no other owner exists.
    Ok(File::from(unsafe {
        OwnedHandle::from_raw_handle(handle as *mut c_void)
    }))
}

/// Reject remote/mapped devices for the SQLite retained-source capability.
pub(super) fn require_local_disk(file: &File) -> io::Result<()> {
    // FILE_FS_DEVICE_INFORMATION / FileFsDeviceInformation from the Windows NT ABI.
    #[repr(C)]
    struct DeviceInformation { device_type: u32, characteristics: u32 }
    const FILE_FS_DEVICE_INFORMATION: u32 = 4;
    const FILE_DEVICE_DISK: u32 = 7;
    const FILE_REMOTE_DEVICE: u32 = 0x10;
    let mut information = DeviceInformation { device_type: 0, characteristics: 0 };
    let mut status_block = IO_STATUS_BLOCK {
        Anonymous: IO_STATUS_BLOCK_0 { Status: 0 },
        Information: 0,
    };
    // SAFETY: The live synchronous handle and the exact information-class
    // buffer remain valid through the call. No filesystem state is modified.
    let status = unsafe {
        NtQueryVolumeInformationFile(
            file.as_raw_handle() as HANDLE,
            &mut status_block,
            (&raw mut information).cast(),
            size_of::<DeviceInformation>() as u32,
            FILE_FS_DEVICE_INFORMATION,
        )
    };
    status_result(status)?;
    if status != 0
        || status_block.Information != size_of::<DeviceInformation>()
        || information.device_type != FILE_DEVICE_DISK
        || information.characteristics & FILE_REMOTE_DEVICE != 0
    {
        return Err(io::Error::new(io::ErrorKind::Unsupported, "SQLite retention requires a local disk filesystem"));
    }
    Ok(())
}

pub(super) fn validate_kind(file: &File, kind: EntryKind) -> io::Result<()> {
    let mut information = MaybeUninit::<BY_HANDLE_FILE_INFORMATION>::uninit();
    // SAFETY: The file handle is live and the output buffer has the documented size.
    if unsafe {
        GetFileInformationByHandle(file.as_raw_handle() as HANDLE, information.as_mut_ptr())
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: The successful API call initialized the entire output structure.
    let information = unsafe { information.assume_init() };
    let is_directory = information.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY != 0;
    let valid_kind = match kind {
        EntryKind::Directory => is_directory,
        EntryKind::File => !is_directory && information.nNumberOfLinks == 1,
    };
    if !valid_kind || information.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "state object is a link or has the wrong file type",
        ));
    }
    Ok(())
}

pub(super) fn rename(root: &File, source: &File, destination: &[u16]) -> io::Result<()> {
    let offset = offset_of!(RenameInformation, file_name);
    let size = offset + size_of_val(destination);
    let mut buffer = vec![0_usize; size.div_ceil(size_of::<usize>())];
    let information = buffer.as_mut_ptr().cast::<RenameInformation>();
    // SAFETY: The usize allocation supplies pointer alignment and enough bytes
    // for the header and counted name. Both borrowed handles remain live. The
    // name is one validated component, interpreted relative to the pinned root.
    unsafe {
        (*information).replace_if_exists = 1;
        (*information).root_directory = root.as_raw_handle() as HANDLE;
        (*information).file_name_length = size_of_val(destination) as u32;
        ptr::copy_nonoverlapping(
            destination.as_ptr(),
            buffer.as_mut_ptr().cast::<u8>().add(offset).cast::<u16>(),
            destination.len(),
        );
    }
    let mut status_block = IO_STATUS_BLOCK {
        Anonymous: IO_STATUS_BLOCK_0 { Status: 0 },
        Information: 0,
    };
    // SAFETY: The initialized buffer and handles outlive this synchronous call.
    let status = unsafe {
        NtSetInformationFile(
            source.as_raw_handle() as HANDLE,
            &mut status_block,
            information.cast(),
            size as u32,
            FILE_RENAME_INFORMATION,
        )
    };
    status_result(status)
}

fn status_result(status: NTSTATUS) -> io::Result<()> {
    if status < 0 {
        // SAFETY: Status conversion accepts any NTSTATUS value.
        Err(io::Error::from_raw_os_error(
            unsafe { RtlNtStatusToDosError(status) } as i32,
        ))
    } else {
        Ok(())
    }
}
