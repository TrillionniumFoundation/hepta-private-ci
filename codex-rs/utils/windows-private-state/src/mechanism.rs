//! File mechanisms only: no owner ACL or durability qualification.

use crate::protected_descriptor::ProtectedDescriptor;
use std::ffi::OsStr;
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

use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::NTSTATUS;
use windows_sys::Win32::Foundation::RtlNtStatusToDosError;
use windows_sys::Win32::Foundation::UNICODE_STRING;
use windows_sys::Win32::Storage::FileSystem::BY_HANDLE_FILE_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_NORMAL;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_TRAVERSE;
use windows_sys::Win32::Storage::FileSystem::FILE_TYPE_DISK;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandle;
use windows_sys::Win32::Storage::FileSystem::GetFileType;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK_0;
use windows_sys::Win32::System::Kernel::OBJ_CASE_INSENSITIVE;
use windows_sys::Win32::System::Kernel::OBJ_DONT_REPARSE;

pub const FILE_OPEN: u32 = 1;
pub const FILE_CREATE: u32 = 2;
const FILE_DIRECTORY_FILE: u32 = 1;
const FILE_NON_DIRECTORY_FILE: u32 = 0x40;
const FILE_SYNCHRONOUS_IO_NONALERT: u32 = 0x20;
const SYNCHRONIZE_ACCESS: u32 = 0x0010_0000;

/// Diagnostic values from one synchronous native open attempt.
/// An observer receives no raw handle and runs only after successful handles are owned.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OpenObservation {
    pub relative_to_held_root: bool,
    pub access: u32,
    pub sharing: u32,
    pub disposition: u32,
    pub options: u32,
    pub ntstatus: i32,
    pub information: usize,
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

fn invalid(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message)
}

fn local_nt_path(path: &Path) -> io::Result<Vec<u16>> {
    if !path.is_absolute() {
        return Err(invalid("probe root must be absolute"));
    }
    let skip = match path.components().next() {
        Some(Component::Prefix(prefix)) => match prefix.kind() {
            Prefix::Disk(_) => 0,
            Prefix::VerbatimDisk(_) => 4,
            _ => return Err(invalid("probe only accepts local disk paths")),
        },
        _ => return Err(invalid("probe requires a local disk prefix")),
    };
    let mut name: Vec<u16> = OsStr::new("\\??\\").encode_wide().collect();
    name.extend(path.as_os_str().encode_wide().skip(skip).map(|unit| {
        if unit == u16::from(b'/') {
            u16::from(b'\\')
        } else {
            unit
        }
    }));
    Ok(name)
}

/// Encode one unambiguous relative leaf; this does not authorize object access.
pub fn leaf_name(name: &str) -> io::Result<Vec<u16>> {
    if name.is_empty()
        || matches!(name, "." | "..")
        || name.ends_with('.')
        || !name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-' | b'_'))
    {
        return Err(invalid("probe child must be one unambiguous leaf name"));
    }
    Ok(name.encode_utf16().collect())
}

enum ObjectOpen<'a> {
    Probe(u32),
    ProtectedDirectory(&'a ProtectedDescriptor),
}

fn open_nt(
    root: HANDLE,
    mut name: Vec<u16>,
    access: u32,
    sharing: u32,
    disposition: u32,
    open: ObjectOpen<'_>,
    observe: impl FnOnce(OpenObservation),
) -> io::Result<File> {
    let (options, security_descriptor) = match open {
        ObjectOpen::Probe(options) => (options, ptr::null()),
        ObjectOpen::ProtectedDirectory(descriptor) => (FILE_DIRECTORY_FILE, descriptor.as_ptr()),
    };
    let length = u16::try_from(name.len() * size_of::<u16>())
        .map_err(|_| invalid("probe name is too long"))?;
    let object_name = UNICODE_STRING {
        Length: length,
        MaximumLength: length,
        Buffer: name.as_mut_ptr(),
    };
    let attributes = ObjectAttributes {
        length: size_of::<ObjectAttributes>() as u32,
        root_directory: root,
        object_name: &object_name,
        attributes: OBJ_CASE_INSENSITIVE as u32 | OBJ_DONT_REPARSE as u32,
        security_descriptor,
        security_quality_of_service: ptr::null(),
    };
    let mut status_block = IO_STATUS_BLOCK {
        Anonymous: IO_STATUS_BLOCK_0 { Status: 0 },
        Information: 0,
    };
    let mut raw = 0;
    // SAFETY: the counted UTF-16 buffer and C-layout structures remain live
    // through this synchronous call. No handle is inherited by the child.
    let status = unsafe {
        NtCreateFile(
            &mut raw,
            access | SYNCHRONIZE_ACCESS,
            &attributes,
            &mut status_block,
            ptr::null(),
            FILE_ATTRIBUTE_NORMAL,
            sharing,
            disposition,
            options | FILE_SYNCHRONOUS_IO_NONALERT,
            ptr::null(),
            /*ea_length*/ 0,
        )
    };
    let result = if status < 0 {
        // SAFETY: this pure conversion accepts the returned NTSTATUS.
        let code = unsafe { RtlNtStatusToDosError(status) };
        Err(io::Error::from_raw_os_error(code as i32))
    } else if raw == 0 || raw == INVALID_HANDLE_VALUE {
        Err(io::Error::other("NtCreateFile returned an invalid handle"))
    } else {
        // SAFETY: successful NtCreateFile transfers one newly owned live handle.
        // Own it before any observer can log, allocate, or panic.
        let handle = unsafe { OwnedHandle::from_raw_handle(raw as *mut c_void) };
        Ok(File::from(handle))
    };
    observe(OpenObservation {
        relative_to_held_root: root != 0,
        access: access | SYNCHRONIZE_ACCESS,
        sharing,
        disposition,
        options: options | FILE_SYNCHRONOUS_IO_NONALERT,
        ntstatus: status,
        information: status_block.Information,
    });
    result
}

#[derive(Debug, Eq, PartialEq)]
/// Identity and type observed on a held disk handle, without an ACL guarantee.
pub struct Identity {
    pub volume: u32,
    pub file_id: u64,
    pub attributes: u32,
    pub links: u32,
}

/// Query the same held disk object without a path lookup.
pub fn identity(file: &File) -> io::Result<Identity> {
    let raw = file.as_raw_handle() as HANDLE;
    // SAFETY: raw is borrowed from the live File for both calls.
    if unsafe { GetFileType(raw) } != FILE_TYPE_DISK {
        return Err(invalid("probe requires a disk object"));
    }
    // SAFETY: BY_HANDLE_FILE_INFORMATION is a plain output structure.
    let mut information: BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
    if unsafe { GetFileInformationByHandle(raw, &mut information) } == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(Identity {
        volume: information.dwVolumeSerialNumber,
        file_id: (u64::from(information.nFileIndexHigh) << 32)
            | u64::from(information.nFileIndexLow),
        attributes: information.dwFileAttributes,
        links: information.nNumberOfLinks,
    })
}

/// Hold an existing local directory without following reparse components.
///
/// This mechanism neither creates nor validates a private owner security descriptor.
pub fn open_root(path: &Path, observe: impl FnOnce(OpenObservation)) -> io::Result<File> {
    let file = open_nt(
        /*root*/ 0,
        local_nt_path(path)?,
        FILE_GENERIC_READ | FILE_GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        FILE_OPEN,
        ObjectOpen::Probe(FILE_DIRECTORY_FILE),
        observe,
    )?;
    let info = identity(&file)?;
    if info.attributes & FILE_ATTRIBUTE_DIRECTORY == 0
        || info.attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
    {
        return Err(invalid("probe root is not an ordinary directory"));
    }
    Ok(file)
}

pub(crate) fn open_namespace_volume(
    path: &Path,
    observe: impl FnOnce(OpenObservation),
) -> io::Result<File> {
    open_nt(
        /*root*/ 0,
        local_nt_path(path)?,
        READ_CONTROL | FILE_READ_ATTRIBUTES | FILE_TRAVERSE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        FILE_OPEN,
        ObjectOpen::Probe(FILE_DIRECTORY_FILE),
        observe,
    )
}

pub(crate) fn open_namespace_child(
    root: &File,
    name: &OsStr,
    observe: impl FnOnce(OpenObservation),
) -> io::Result<File> {
    let name: Vec<u16> = name.encode_wide().collect();
    if name.is_empty()
        || name.len() > 255
        || name == [46]
        || name == [46, 46]
        || matches!(name.last(), Some(32 | 46))
        || name.iter().any(|unit| matches!(*unit, 0 | 47 | 58 | 92))
    {
        return Err(invalid(
            "namespace child must be one bounded literal component",
        ));
    }
    open_nt(
        root.as_raw_handle() as HANDLE,
        name,
        READ_CONTROL | FILE_READ_ATTRIBUTES | FILE_TRAVERSE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        FILE_OPEN,
        ObjectOpen::Probe(FILE_DIRECTORY_FILE),
        observe,
    )
}

/// Open a single-link regular leaf relative to a live held directory handle.
/// Native access/sharing flags are mechanisms, not a permission-profile admission.
pub fn open_relative(
    root: &File,
    name: &str,
    access: u32,
    sharing: u32,
    disposition: u32,
    observe: impl FnOnce(OpenObservation),
) -> io::Result<File> {
    let file = open_nt(
        root.as_raw_handle() as HANDLE,
        leaf_name(name)?,
        access,
        sharing,
        disposition,
        ObjectOpen::Probe(FILE_NON_DIRECTORY_FILE),
        observe,
    )?;
    let info = identity(&file)?;
    if info.attributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT) != 0
        || info.links != 1
    {
        return Err(invalid(
            "probe child must be a non-reparse single-link file",
        ));
    }
    Ok(file)
}

/// Open an existing directory leaf relative to a live held root without reparsing.
pub fn open_relative_directory(
    root: &File,
    name: &str,
    observe: impl FnOnce(OpenObservation),
) -> io::Result<File> {
    open_nt(
        root.as_raw_handle() as HANDLE,
        leaf_name(name)?,
        FILE_GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        FILE_OPEN,
        ObjectOpen::Probe(FILE_DIRECTORY_FILE),
        observe,
    )
}

pub(crate) fn create_protected_directory(
    root: &File,
    name: &str,
    descriptor: &ProtectedDescriptor,
    observe: impl FnOnce(OpenObservation),
) -> io::Result<File> {
    open_nt(
        root.as_raw_handle() as HANDLE,
        leaf_name(name)?,
        FILE_GENERIC_READ | FILE_GENERIC_WRITE | 0x0001_0000,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        FILE_CREATE,
        ObjectOpen::ProtectedDirectory(descriptor),
        observe,
    )
}
