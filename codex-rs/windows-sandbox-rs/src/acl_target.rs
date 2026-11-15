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
use std::os::windows::io::AsRawHandle;
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
use windows_sys::Win32::Storage::FileSystem::FILE_ID_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FileIdInfo;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandleEx;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::SYNCHRONIZE;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;
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

/// Obtains ACL-write authority for the retained directory itself. Win32
/// ReOpenFile rejects directory handles on the supported native runner, so
/// directory upgrades use the NT relative-object open, with an empty name.
/// The caller's WRITE_DAC check still applies; no pathname or privilege fallback
/// is used, and both handles must report the same volume and file identity.
pub(crate) fn reopen_directory_for_acl_write(path: &Path, directory: &File) -> Result<File> {
    ensure_not_reparse(path, directory)?;
    let expected_identity = file_identity(directory)?;
    let mut empty_name = [0_u16];
    let object_name = UNICODE_STRING {
        Length: 0,
        MaximumLength: size_of::<u16>() as u16,
        Buffer: empty_name.as_mut_ptr(),
    };
    let attributes = ObjectAttributes {
        length: size_of::<ObjectAttributes>() as u32,
        root_directory: directory.as_raw_handle() as HANDLE,
        object_name: &object_name,
        attributes: OBJ_DONT_REPARSE as u32,
        security_descriptor: ptr::null(),
        security_quality_of_service: ptr::null(),
    };
    let mut status_block = IO_STATUS_BLOCK {
        Anonymous: IO_STATUS_BLOCK_0 { Status: 0 },
        Information: 0,
    };
    let mut handle = 0;
    // SAFETY: RootDirectory is retained throughout this synchronous call. The
    // empty relative name refers to that object, not a newly resolved name.
    // All input/output buffers remain live until the open has completed.
    let status = unsafe {
        NtCreateFile(
            &mut handle,
            READ_CONTROL | WRITE_DAC | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
            &attributes,
            &mut status_block,
            ptr::null(),
            FILE_ATTRIBUTE_NORMAL,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            FILE_OPEN,
            FILE_DIRECTORY_FILE | FILE_OPEN_REPARSE_POINT | FILE_SYNCHRONOUS_IO_NONALERT,
            ptr::null(),
            /*ea_length*/ 0,
        )
    };
    if status < 0 {
        let code = unsafe { RtlNtStatusToDosError(status) };
        return Err(std::io::Error::from_raw_os_error(code as i32)).with_context(|| {
            format!(
                "NtCreateFile(WRITE_DAC) failed for {}: {code} (retained directory)",
                path.display()
            )
        });
    }
    ensure!(
        handle != 0 && handle != INVALID_HANDLE_VALUE,
        "NtCreateFile returned an invalid retained-directory ACL handle"
    );
    let writable = unsafe { File::from_raw_handle(handle as *mut c_void) };
    ensure_not_reparse(path, &writable)?;
    ensure!(
        writable.metadata()?.is_dir() && file_identity(&writable)? == expected_identity,
        "retained-directory ACL handle identity changed: {}",
        path.display()
    );
    Ok(writable)
}

fn file_identity(file: &File) -> Result<(u64, [u8; 16])> {
    // SAFETY: FILE_ID_INFO is a plain output structure, and its exact byte size
    // is passed to the kernel while the owned file handle remains live.
    let mut identity: FILE_ID_INFO = unsafe { std::mem::zeroed() };
    let result = unsafe {
        GetFileInformationByHandleEx(
            file.as_raw_handle() as HANDLE,
            FileIdInfo,
            (&raw mut identity).cast(),
            size_of::<FILE_ID_INFO>() as u32,
        )
    };
    if result == 0 {
        return Err(std::io::Error::last_os_error()).context("query retained ACL file identity");
    }
    Ok((identity.VolumeSerialNumber, identity.FileId.Identifier))
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
