//! Test-only Windows mechanism probes, not a private-state backend.
//! No owner ACL policy, immutable executable fallback, or durability receipt is
//! implemented here. The three authoritative stores remain unsupported.

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

use serde_json::Value;
use serde_json::json;
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
use windows_sys::Win32::Storage::FileSystem::FILE_RENAME_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_RENAME_INFO_0;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_TYPE_DISK;
use windows_sys::Win32::Storage::FileSystem::FileRenameInfo;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandle;
use windows_sys::Win32::Storage::FileSystem::GetFileType;
use windows_sys::Win32::Storage::FileSystem::GetVolumeInformationByHandleW;
use windows_sys::Win32::Storage::FileSystem::SetFileInformationByHandle;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK_0;
use windows_sys::Win32::System::Kernel::OBJ_CASE_INSENSITIVE;
use windows_sys::Win32::System::Kernel::OBJ_DONT_REPARSE;

pub(super) const FILE_OPEN: u32 = 1;
pub(super) const FILE_CREATE: u32 = 2;
const FILE_DIRECTORY_FILE: u32 = 1;
const FILE_NON_DIRECTORY_FILE: u32 = 0x40;
const FILE_SYNCHRONOUS_IO_NONALERT: u32 = 0x20;
const SYNCHRONIZE_ACCESS: u32 = 0x0010_0000;

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
    fn NtFlushBuffersFileEx(
        file_handle: HANDLE,
        flags: u32,
        parameters: *const c_void,
        parameters_size: u32,
        io_status_block: *mut IO_STATUS_BLOCK,
    ) -> NTSTATUS;
}

pub(super) fn emit(stage: &str, result: Value) {
    println!(
        "HEPTA_PRIVATE_STATE_NATIVE_PROBE {}",
        json!({"stage": stage, "result": result, "owner_supported": false, "power_loss_qualified": false})
    );
}

pub(super) fn record_io<T>(stage: &str, result: &io::Result<T>) {
    let details = match result {
        Ok(_) => json!({"ok": true}),
        Err(error) => {
            json!({"ok": false, "os_error": error.raw_os_error(), "error": error.to_string()})
        }
    };
    emit(stage, details);
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

fn leaf_name(name: &str) -> io::Result<Vec<u16>> {
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

fn open_nt(
    root: HANDLE,
    mut name: Vec<u16>,
    access: u32,
    sharing: u32,
    disposition: u32,
    options: u32,
) -> io::Result<File> {
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
        // Fixtures carry no authority or secret material. Private ACL creation
        // and validation remain a separate prerequisite, not a claim here.
        security_descriptor: ptr::null(),
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
    emit(
        "NtCreateFile",
        json!({
            "relative_to_held_root": root != 0, "access": access | SYNCHRONIZE_ACCESS,
            "sharing": sharing, "disposition": disposition, "options": options | FILE_SYNCHRONOUS_IO_NONALERT,
            "ntstatus": format!("0x{:08x}", status as u32), "information": status_block.Information
        }),
    );
    if status < 0 {
        // SAFETY: this pure conversion accepts the returned NTSTATUS.
        let code = unsafe { RtlNtStatusToDosError(status) };
        return Err(io::Error::from_raw_os_error(code as i32));
    }
    if raw == 0 || raw == INVALID_HANDLE_VALUE {
        return Err(io::Error::other("NtCreateFile returned an invalid handle"));
    }
    // SAFETY: successful NtCreateFile transfers one newly owned live handle.
    let handle = unsafe { OwnedHandle::from_raw_handle(raw as *mut c_void) };
    Ok(File::from(handle))
}

#[derive(Debug, Eq, PartialEq)]
pub(super) struct Identity {
    pub volume: u32,
    pub file_id: u64,
    pub attributes: u32,
    pub links: u32,
}

pub(super) fn identity(file: &File) -> io::Result<Identity> {
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

pub(super) fn open_root(path: &Path) -> io::Result<File> {
    let file = open_nt(
        /*root*/ 0,
        local_nt_path(path)?,
        FILE_GENERIC_READ | FILE_GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        FILE_OPEN,
        FILE_DIRECTORY_FILE,
    )?;
    let info = identity(&file)?;
    if info.attributes & FILE_ATTRIBUTE_DIRECTORY == 0
        || info.attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
    {
        return Err(invalid("probe root is not an ordinary directory"));
    }
    Ok(file)
}

pub(super) fn open_relative(
    root: &File,
    name: &str,
    access: u32,
    sharing: u32,
    disposition: u32,
) -> io::Result<File> {
    let file = open_nt(
        root.as_raw_handle() as HANDLE,
        leaf_name(name)?,
        access,
        sharing,
        disposition,
        FILE_NON_DIRECTORY_FILE,
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

pub(super) fn open_relative_directory(root: &File, name: &str) -> io::Result<File> {
    open_nt(
        root.as_raw_handle() as HANDLE,
        leaf_name(name)?,
        FILE_GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        FILE_OPEN,
        FILE_DIRECTORY_FILE,
    )
}

pub(super) fn rename_relative(root: &File, source: &File, name: &str) -> io::Result<()> {
    #[repr(C)]
    struct RenameBuffer {
        flags: FILE_RENAME_INFO_0,
        root: HANDLE,
        length: u32,
        name: [u16; 64],
    }
    let name = leaf_name(name)?;
    if name.len() >= 64 {
        return Err(invalid("probe rename leaf is too long"));
    }
    // C layout and fixed backing storage avoid unaligned flexible-array writes.
    if offset_of!(RenameBuffer, name) != offset_of!(FILE_RENAME_INFO, FileName) {
        return Err(io::Error::other("FILE_RENAME_INFO layout mismatch"));
    }
    let mut information = RenameBuffer {
        flags: FILE_RENAME_INFO_0 { Flags: 1 },
        root: root.as_raw_handle() as HANDLE,
        length: (name.len() * size_of::<u16>()) as u32,
        name: [0; 64],
    };
    information.name[..name.len()].copy_from_slice(&name);
    let bytes = offset_of!(RenameBuffer, name) + (name.len() + 1) * size_of::<u16>();
    // SAFETY: the live source/root handles and C-layout buffer cover every byte
    // specified. Only ReplaceIfExists is set; no POSIX/readonly-ignore fallback.
    let result = unsafe {
        SetFileInformationByHandle(
            source.as_raw_handle() as HANDLE,
            FileRenameInfo,
            (&raw const information).cast(),
            bytes as u32,
        )
    };
    let result = if result == 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(())
    };
    record_io("held_root_relative_rename", &result);
    result
}

pub(super) fn native_flush(file: &File) -> io::Result<()> {
    let mut status_block = IO_STATUS_BLOCK {
        Anonymous: IO_STATUS_BLOCK_0 { Status: 0 },
        Information: 0,
    };
    // SAFETY: flags=0 and the null/zero optional buffer are the documented
    // normal flush request. The File remains live until synchronous return.
    let status = unsafe {
        NtFlushBuffersFileEx(
            file.as_raw_handle() as HANDLE,
            /*flags*/ 0,
            ptr::null(),
            /*parameters_size*/ 0,
            &mut status_block,
        )
    };
    emit(
        "NtFlushBuffersFileEx_directory",
        json!({"flags": 0, "ntstatus": format!("0x{:08x}", status as u32)}),
    );
    if status < 0 {
        // SAFETY: this conversion accepts the returned native status value.
        let code = unsafe { RtlNtStatusToDosError(status) };
        Err(io::Error::from_raw_os_error(code as i32))
    } else {
        Ok(())
    }
}

pub(super) fn record_filesystem(root: &File) -> io::Result<String> {
    let mut name = [0_u16; 256];
    let mut serial = 0;
    let mut flags = 0;
    // SAFETY: buffers have their declared lengths; the borrowed handle is live.
    let result = unsafe {
        GetVolumeInformationByHandleW(
            root.as_raw_handle() as HANDLE,
            ptr::null_mut(),
            /*nvolumenamesize*/ 0,
            &mut serial,
            ptr::null_mut(),
            &mut flags,
            name.as_mut_ptr(),
            name.len() as u32,
        )
    };
    if result == 0 {
        return Err(io::Error::last_os_error());
    }
    let end = name
        .iter()
        .position(|unit| *unit == 0)
        .unwrap_or(name.len());
    let name = String::from_utf16_lossy(&name[..end]);
    emit(
        "filesystem",
        json!({"name": name, "volume_serial": serial, "flags": flags}),
    );
    Ok(name)
}
