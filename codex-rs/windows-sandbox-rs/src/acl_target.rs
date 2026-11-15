use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use std::ffi::OsStr;
use std::ffi::c_void;
use std::fs::File;
use std::mem::size_of;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::fs::MetadataExt;
use std::os::windows::io::FromRawHandle;
use std::path::Component;
use std::path::Path;
use std::path::Prefix;
use std::ptr;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::NTSTATUS;
use windows_sys::Win32::Foundation::RtlNtStatusToDosError;
use windows_sys::Win32::Foundation::UNICODE_STRING;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_NORMAL;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::SYNCHRONIZE;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK_0;
use windows_sys::Win32::System::Kernel::OBJ_CASE_INSENSITIVE;
use windows_sys::Win32::System::Kernel::OBJ_DONT_REPARSE;

const FILE_OPEN: u32 = 1;
const FILE_OPEN_IF: u32 = 3;
const FILE_DIRECTORY_FILE: u32 = 1;
const FILE_SYNCHRONOUS_IO_NONALERT: u32 = 0x20;
const FILE_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
const STATUS_REPARSE_POINT_ENCOUNTERED: NTSTATUS = 0xC000_050B_u32 as i32;

#[derive(Clone, Copy)]
pub(crate) enum Disposition {
    Existing,
    DirectoryIfMissing,
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

/// Opens an ACL target without following reparses in any component. Creation
/// applies only to the final directory and runs under the effective caller.
/// ACL queries and mutations must continue through the returned object handle.
pub(crate) fn open(
    path: &Path,
    access: u32,
    sharing: u32,
    disposition: Disposition,
) -> Result<File> {
    let mut name = nt_path(path)?;
    let length = u16::try_from((name.len() - 1) * size_of::<u16>())
        .context("sandbox ACL path is too long")?;
    let maximum_length =
        u16::try_from(name.len() * size_of::<u16>()).context("sandbox ACL path is too long")?;
    let object_name = UNICODE_STRING {
        Length: length,
        MaximumLength: maximum_length,
        Buffer: name.as_mut_ptr(),
    };
    let attributes = ObjectAttributes {
        length: size_of::<ObjectAttributes>() as u32,
        root_directory: 0,
        object_name: &object_name,
        attributes: OBJ_CASE_INSENSITIVE as u32 | OBJ_DONT_REPARSE as u32,
        security_descriptor: ptr::null(),
        security_quality_of_service: ptr::null(),
    };
    let (creation, options) = match disposition {
        Disposition::Existing => (FILE_OPEN, FILE_OPEN_REPARSE_POINT),
        Disposition::DirectoryIfMissing => (FILE_OPEN_IF, FILE_DIRECTORY_FILE),
    };
    let mut status_block = IO_STATUS_BLOCK {
        Anonymous: IO_STATUS_BLOCK_0 { Status: 0 },
        Information: 0,
    };
    let mut handle = 0;
    // SAFETY: all referenced buffers remain live until the synchronous open
    // completes; no handle or buffer is inherited or exposed to a child.
    let status = unsafe {
        NtCreateFile(
            &mut handle,
            access | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
            &attributes,
            &mut status_block,
            ptr::null(),
            FILE_ATTRIBUTE_NORMAL,
            sharing,
            creation,
            options | FILE_SYNCHRONOUS_IO_NONALERT,
            ptr::null(),
            /*ea_length*/ 0,
        )
    };
    if status < 0 {
        if status == STATUS_REPARSE_POINT_ENCOUNTERED {
            bail!(
                "sandbox ACL path contains a reparse point: {}",
                path.display()
            );
        }
        let code = unsafe { RtlNtStatusToDosError(status) };
        return Err(std::io::Error::from_raw_os_error(code as i32))
            .with_context(|| format!("NtCreateFile sandbox ACL target {}", path.display()));
    }
    ensure!(
        handle != 0 && handle != INVALID_HANDLE_VALUE,
        "NtCreateFile returned an invalid sandbox ACL handle"
    );
    let file = unsafe { File::from_raw_handle(handle as *mut c_void) };
    ensure_not_reparse(path, &file)?;
    Ok(file)
}

pub(crate) fn ensure_not_reparse(path: &Path, file: &File) -> Result<()> {
    ensure!(
        file.metadata()?.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT == 0,
        "sandbox ACL path contains a reparse point: {}",
        path.display()
    );
    Ok(())
}

fn nt_path(path: &Path) -> Result<Vec<u16>> {
    ensure!(
        path.is_absolute(),
        "sandbox ACL path must be absolute: {}",
        path.display()
    );
    let mut components = path.components();
    let Some(Component::Prefix(prefix)) = components.next() else {
        bail!(
            "sandbox ACL path has no filesystem prefix: {}",
            path.display()
        );
    };
    let prefix = match prefix.kind() {
        Prefix::Disk(letter) | Prefix::VerbatimDisk(letter) => {
            format!("\\??\\{}:\\", char::from(letter)).into()
        }
        Prefix::UNC(server, share) | Prefix::VerbatimUNC(server, share) => {
            let mut prefix = std::ffi::OsString::from("\\??\\UNC\\");
            prefix.push(server);
            prefix.push("\\");
            prefix.push(share);
            prefix.push("\\");
            prefix
        }
        _ => bail!(
            "sandbox ACL path must name a disk or UNC share: {}",
            path.display()
        ),
    };
    let mut name: Vec<_> = prefix.encode_wide().collect();
    for component in components {
        match component {
            Component::RootDir => {}
            Component::Normal(part) => {
                if name.last().copied() != Some(u16::from(b'\\')) {
                    name.extend(OsStr::new("\\").encode_wide());
                }
                name.extend(part.encode_wide());
            }
            _ => bail!(
                "sandbox ACL path contains a relative component: {}",
                path.display()
            ),
        }
    }
    ensure!(!name.contains(&0), "sandbox ACL path contains a NUL");
    name.push(0);
    Ok(name)
}
