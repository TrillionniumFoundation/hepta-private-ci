//! The no-reparse NT open pattern shared with exec-server's Windows backend.

use std::ffi::OsStr;
use std::ffi::c_void;
use std::fs::File;
use std::io;
use std::mem::offset_of;
use std::mem::size_of;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Component;
use std::path::Path;
use std::path::Prefix;
use std::ptr;

use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::NTSTATUS;
use windows_sys::Win32::Foundation::OBJ_CASE_INSENSITIVE;
use windows_sys::Win32::Foundation::OBJ_DONT_REPARSE;
use windows_sys::Win32::Foundation::RtlNtStatusToDosError;
use windows_sys::Win32::Foundation::UNICODE_STRING;
use windows_sys::Win32::Security::SECURITY_QUALITY_OF_SERVICE;
use windows_sys::Win32::Security::SecurityIdentification;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_NORMAL;
use windows_sys::Win32::Storage::FileSystem::FILE_DISPOSITION_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_RENAME_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FileDispositionInfo;
use windows_sys::Win32::Storage::FileSystem::FileRenameInfo;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::SetFileInformationByHandle;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK;

use crate::windows_security::OwnerSecurityDescriptor;

const FILE_DIRECTORY_FILE: u32 = 0x0000_0001;
const FILE_SYNCHRONOUS_IO_NONALERT: u32 = 0x0000_0020;
const FILE_NON_DIRECTORY_FILE: u32 = 0x0000_0040;
const SYNCHRONIZE_ACCESS: u32 = 0x0010_0000;
const STATUS_REPARSE_POINT_ENCOUNTERED: NTSTATUS = 0xC000_050B_u32 as i32;

pub(super) enum Kind {
    Directory,
    RegularFile,
}

pub(super) enum Access {
    Read,
    ReadWrite,
    Rename,
}

pub(super) enum Disposition {
    Existing,
    CreateNew,
    OpenOrCreate,
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
}

pub(super) fn open_absolute(
    path: &Path,
    access: Access,
    kind: Kind,
    disposition: Disposition,
    descriptor: Option<&OwnerSecurityDescriptor>,
) -> io::Result<File> {
    open(nt_path(path)?, None, access, kind, disposition, descriptor)
}

pub(super) fn open_child(
    directory: &File,
    name: &str,
    access: Access,
    kind: Kind,
    disposition: Disposition,
    descriptor: Option<&OwnerSecurityDescriptor>,
) -> io::Result<File> {
    open(
        child_name(name)?,
        Some(directory),
        access,
        kind,
        disposition,
        descriptor,
    )
}

fn open(
    mut name: Vec<u16>,
    directory: Option<&File>,
    access: Access,
    kind: Kind,
    disposition: Disposition,
    descriptor: Option<&OwnerSecurityDescriptor>,
) -> io::Result<File> {
    let length = u16::try_from(name.len() * size_of::<u16>())
        .map_err(|_| invalid_name("filesystem name is too long"))?;
    let object_name = UNICODE_STRING {
        Length: length,
        MaximumLength: length,
        Buffer: name.as_mut_ptr(),
    };
    let quality = SECURITY_QUALITY_OF_SERVICE {
        Length: size_of::<SECURITY_QUALITY_OF_SERVICE>() as u32,
        ImpersonationLevel: SecurityIdentification,
        ContextTrackingMode: 0,
        EffectiveOnly: true,
    };
    let attributes = ObjectAttributes {
        length: size_of::<ObjectAttributes>() as u32,
        root_directory: directory.map_or(ptr::null_mut(), AsRawHandle::as_raw_handle),
        object_name: &object_name,
        attributes: OBJ_CASE_INSENSITIVE | OBJ_DONT_REPARSE,
        security_descriptor: descriptor.map_or(ptr::null(), OwnerSecurityDescriptor::as_ptr),
        security_quality_of_service: (&raw const quality).cast(),
    };
    let desired_access = match access {
        Access::Read => FILE_GENERIC_READ,
        Access::ReadWrite => FILE_GENERIC_READ | FILE_GENERIC_WRITE,
        Access::Rename => FILE_READ_ATTRIBUTES | READ_CONTROL | DELETE,
    };
    let create_options = match kind {
        Kind::Directory => FILE_DIRECTORY_FILE,
        Kind::RegularFile => FILE_NON_DIRECTORY_FILE,
    };
    let create_disposition = match disposition {
        Disposition::Existing => 1,
        Disposition::CreateNew => 2,
        Disposition::OpenOrCreate => 3,
    };
    let mut io_status = IO_STATUS_BLOCK::default();
    let mut handle = ptr::null_mut();
    // SAFETY: all pointed-to buffers and the optional parent handle remain
    // live for this synchronous call. No inherited or path-based fallback is
    // used; OBJ_DONT_REPARSE covers every component resolved by the kernel.
    let status = unsafe {
        NtCreateFile(
            &mut handle,
            desired_access | SYNCHRONIZE_ACCESS,
            &attributes,
            &mut io_status,
            ptr::null(),
            FILE_ATTRIBUTE_NORMAL,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            create_disposition,
            create_options | FILE_SYNCHRONOUS_IO_NONALERT,
            ptr::null(),
            /*ea_length*/ 0,
        )
    };
    if status < 0 {
        if status == STATUS_REPARSE_POINT_ENCOUNTERED {
            return Err(invalid_name("state path contains a reparse point"));
        }
        // SAFETY: converting a status value does not dereference any pointer.
        return Err(io::Error::from_raw_os_error(
            unsafe { RtlNtStatusToDosError(status) } as i32,
        ));
    }
    if handle.is_null() || handle == INVALID_HANDLE_VALUE {
        return Err(io::Error::other("NT open returned no filesystem handle"));
    }
    // SAFETY: the successful open transferred one owned handle.
    Ok(File::from(unsafe { OwnedHandle::from_raw_handle(handle) }))
}

pub(super) fn replace(directory: &File, source: &File, destination: &str) -> io::Result<()> {
    let name = child_name(destination)?;
    let name_bytes = name.len() * size_of::<u16>();
    let size =
        (offset_of!(FILE_RENAME_INFO, FileName) + name_bytes).max(size_of::<FILE_RENAME_INFO>());
    let mut storage = vec![0_usize; size.div_ceil(size_of::<usize>())];
    let info = storage.as_mut_ptr().cast::<FILE_RENAME_INFO>();
    // SAFETY: the allocation is aligned for this pointer-containing struct,
    // includes the complete variable name, and outlives the synchronous call.
    unsafe {
        // Assign fields separately so all alignment padding and the unused
        // bytes of the BOOLEAN/flags union stay initialized to zero.
        (*info).Anonymous.ReplaceIfExists = true;
        (*info).RootDirectory = directory.as_raw_handle();
        (*info).FileNameLength =
            u32::try_from(name_bytes).map_err(|_| invalid_name("destination name is too long"))?;
        ptr::copy_nonoverlapping(
            name.as_ptr(),
            (&raw mut (*info).FileName).cast(),
            name.len(),
        );
        if SetFileInformationByHandle(
            source.as_raw_handle(),
            FileRenameInfo,
            storage.as_ptr().cast(),
            u32::try_from(size).map_err(|_| invalid_name("rename buffer is too large"))?,
        ) == 0
        {
            return Err(io::Error::last_os_error());
        }
    }
    Ok(())
}

pub(super) fn remove(file: &File) -> io::Result<()> {
    let info = FILE_DISPOSITION_INFO { DeleteFile: true };
    // SAFETY: the checked handle owns DELETE access. The fixed, initialized
    // disposition structure remains live for this synchronous call.
    if unsafe {
        SetFileInformationByHandle(
            file.as_raw_handle(),
            FileDispositionInfo,
            (&raw const info).cast(),
            size_of::<FILE_DISPOSITION_INFO>() as u32,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

fn nt_path(path: &Path) -> io::Result<Vec<u16>> {
    if !path.is_absolute()
        || path
            .components()
            .any(|part| matches!(part, Component::ParentDir))
    {
        return Err(invalid_name(
            "state path must be absolute without parent traversal",
        ));
    }
    let (prefix, offset) = match path.components().next() {
        Some(Component::Prefix(prefix)) => match prefix.kind() {
            Prefix::Disk(_) => ("\\??\\", 0),
            Prefix::VerbatimDisk(_) => ("\\??\\", 4),
            Prefix::UNC(_, _) => ("\\??\\UNC\\", 2),
            Prefix::VerbatimUNC(_, _) => ("\\??\\UNC\\", 8),
            _ => {
                return Err(invalid_name(
                    "state path must name a disk or UNC filesystem",
                ));
            }
        },
        _ => return Err(invalid_name("state path has no Windows filesystem prefix")),
    };
    let mut name: Vec<u16> = OsStr::new(prefix).encode_wide().collect();
    name.extend(path.as_os_str().encode_wide().skip(offset).map(|unit| {
        if unit == u16::from(b'/') {
            u16::from(b'\\')
        } else {
            unit
        }
    }));
    if name.contains(&0) {
        return Err(invalid_name("state path contains a NUL"));
    }
    Ok(name)
}

fn child_name(name: &str) -> io::Result<Vec<u16>> {
    if name.is_empty() || matches!(name, "." | "..") || name.contains(['/', '\\', ':', '\0']) {
        return Err(invalid_name(
            "state entry must be one filename without a stream name",
        ));
    }
    Ok(name.encode_utf16().collect())
}

fn invalid_name(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message)
}
