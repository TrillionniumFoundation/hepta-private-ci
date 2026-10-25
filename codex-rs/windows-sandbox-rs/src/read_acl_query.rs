//! Existing-object, synchronous, non-inheritable query handles only.
use anyhow::Result;
use anyhow::ensure;
use std::ffi::OsStr;
use std::ffi::c_void;
use std::fs::File;
use std::mem::size_of;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::FromRawHandle;
use std::path::Component;
use std::path::Path;
use std::path::Prefix;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::NTSTATUS;
use windows_sys::Win32::Foundation::RtlNtStatusToDosError;
use windows_sys::Win32::Foundation::UNICODE_STRING;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::SYNCHRONIZE;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK_0;
use windows_sys::Win32::System::Kernel::OBJ_CASE_INSENSITIVE;
use windows_sys::Win32::System::Kernel::OBJ_DONT_REPARSE;

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
    fn NtOpenFile(
        file_handle: *mut HANDLE,
        access: u32,
        attributes: *const ObjectAttributes,
        status: *mut IO_STATUS_BLOCK,
        share: u32,
        options: u32,
    ) -> NTSTATUS;
}

pub(crate) fn open(path: &Path) -> Result<File> {
    ensure!(
        path.is_absolute() && path.parent().is_some(),
        "read proof requires a local non-volume root"
    );
    let skip = match path.components().next() {
        Some(Component::Prefix(prefix)) if matches!(prefix.kind(), Prefix::Disk(_)) => 0,
        Some(Component::Prefix(prefix)) if matches!(prefix.kind(), Prefix::VerbatimDisk(_)) => 4,
        _ => anyhow::bail!("read proof requires a local disk prefix"),
    };
    let mut name: Vec<u16> = OsStr::new("\\??\\").encode_wide().collect();
    name.extend(path.as_os_str().encode_wide().skip(skip).map(|unit| {
        if unit == b'/' as u16 {
            b'\\' as u16
        } else {
            unit
        }
    }));
    ensure!(!name.contains(&0), "embedded NUL in read proof root");
    let length = u16::try_from(name.len() * 2)?;
    let mut name = UNICODE_STRING {
        Length: length,
        MaximumLength: length,
        Buffer: name.as_mut_ptr(),
    };
    let attributes = ObjectAttributes {
        length: size_of::<ObjectAttributes>() as _,
        root_directory: 0,
        object_name: &mut name,
        attributes: OBJ_CASE_INSENSITIVE as u32 | OBJ_DONT_REPARSE as u32,
        security_descriptor: std::ptr::null(),
        security_quality_of_service: std::ptr::null(),
    };
    let mut io = IO_STATUS_BLOCK {
        Anonymous: IO_STATUS_BLOCK_0 { Status: 0 },
        Information: 0,
    };
    let mut raw = 0;
    // SAFETY: synchronous existing-object open; all inputs/outputs stay live
    // through completion. No OBJ_INHERIT, DELETE sharing, creation or mutation.
    let status = unsafe {
        NtOpenFile(
            &mut raw,
            READ_CONTROL | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
            &attributes,
            &mut io,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            /*options*/ 0x20,
        )
    };
    if status < 0 {
        return Err(std::io::Error::from_raw_os_error(
            unsafe { RtlNtStatusToDosError(status) } as _
        )
        .into());
    }
    ensure!(
        raw != 0 && raw != INVALID_HANDLE_VALUE,
        "invalid read proof query handle"
    );
    // SAFETY: successful NtOpenFile transfers one handle; no alias escapes.
    let file = unsafe { File::from_raw_handle(raw as _) };
    ensure!(
        status == 0 && unsafe { io.Anonymous.Status } == 0,
        "incomplete synchronous read proof open"
    );
    Ok(file)
}
