//! Acquire the private directory without a separate path check or creation.

use std::ffi::c_void;
use std::fs::File;
use std::io;
use std::mem::size_of;
use std::os::windows::io::FromRawHandle;
use std::path::Path;
use std::path::PathBuf;
use std::ptr;

use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::NTSTATUS;
use windows_sys::Win32::Foundation::RtlNtStatusToDosError;
use windows_sys::Win32::Foundation::UNICODE_STRING;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_NORMAL;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK_0;
use windows_sys::Win32::System::Kernel::OBJ_CASE_INSENSITIVE;
use windows_sys::Win32::System::Kernel::OBJ_DONT_REPARSE;

use super::unsafe_state;
use super::wide_path;
use super::with_private_security;

const FILE_CREATE: u32 = 2;
const FILE_OPEN_IF: u32 = 3;
const FILE_DIRECTORY_FILE: u32 = 1;
const FILE_SYNCHRONOUS_IO_NONALERT: u32 = 0x20;
const FILE_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
const SYNCHRONIZE: u32 = 0x0010_0000;
const STATUS_REPARSE_POINT_ENCOUNTERED: NTSTATUS = 0xC000_050B_u32 as i32;

// Match the existing windows-sandbox no_reparse_dir NtCreateFile ABI. Keep the
// creation descriptor, synchronous File access and sharing policy of this owner.
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

enum DirectoryOpen {
    Create,
    CreateNew,
    ExistingRead,
    ExistingReadWrite,
    ExistingPathIdentity,
}

/// Return the final spelling of an existing file or directory opened without
/// reparse traversal. The handle pins the actual object while its name is read;
/// case and 8.3 aliases are never compared by lowercasing path strings.
///
/// This path observation does not qualify a private owner/DACL or retain a
/// recovery guard for the caller. Those checks remain at the owning API.
pub fn canonical_existing_path_without_reparse(path: &Path) -> io::Result<PathBuf> {
    let file = open_with_mode(path, DirectoryOpen::ExistingPathIdentity)?;
    if winapi_util::file::information(&file)?.file_attributes()
        & u64::from(FILE_ATTRIBUTE_REPARSE_POINT)
        != 0
    {
        return Err(unsafe_state("identity path is a reparse point"));
    }
    super::final_path(&file)
}

pub(super) fn open(root: &Path) -> io::Result<File> {
    open_with_mode(root, DirectoryOpen::Create)
}

pub(super) fn create_new(root: &Path) -> io::Result<File> {
    open_with_mode(root, DirectoryOpen::CreateNew)
}

pub(super) fn open_existing(root: &Path) -> io::Result<File> {
    open_with_mode(root, DirectoryOpen::ExistingRead)
}

pub(super) fn open_existing_writable(root: &Path) -> io::Result<File> {
    open_with_mode(root, DirectoryOpen::ExistingReadWrite)
}

fn open_with_mode(root: &Path, mode: DirectoryOpen) -> io::Result<File> {
    let mut name = wide_path(root)?;
    // Convert the already absolute Win32 verbatim spelling to the NT namespace.
    // This retains long paths and UNC (\\?\UNC\... -> \??\UNC\...) without
    // canonicalizing through a redirect before the protected open.
    name[1] = u16::from(b'?');
    for unit in &mut name {
        if *unit == u16::from(b'/') {
            *unit = u16::from(b'\\');
        }
    }
    let maximum_length = u16::try_from(name.len() * size_of::<u16>()).map_err(|_| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "private state path is too long",
        )
    })?;
    let object_name = UNICODE_STRING {
        Length: maximum_length - size_of::<u16>() as u16,
        MaximumLength: maximum_length,
        Buffer: name.as_mut_ptr(),
    };
    with_private_security(|security| {
        let attributes = ObjectAttributes {
            length: size_of::<ObjectAttributes>() as u32,
            root_directory: 0,
            object_name: &object_name,
            attributes: OBJ_CASE_INSENSITIVE as u32 | OBJ_DONT_REPARSE as u32,
            // Applied only if the leaf is created. Existing security is never
            // repaired; the caller validates the exact returned handle.
            security_descriptor: match mode {
                DirectoryOpen::Create | DirectoryOpen::CreateNew => security.lpSecurityDescriptor,
                DirectoryOpen::ExistingRead
                | DirectoryOpen::ExistingReadWrite
                | DirectoryOpen::ExistingPathIdentity => ptr::null(),
            },
            security_quality_of_service: ptr::null(),
        };
        let mut io_status = IO_STATUS_BLOCK {
            Anonymous: IO_STATUS_BLOCK_0 { Status: 0 },
            Information: 0,
        };
        let mut handle = 0;
        #[cfg(test)]
        tests::before_open()?;
        let status = unsafe {
            NtCreateFile(
                &mut handle,
                match mode {
                    DirectoryOpen::ExistingPathIdentity => FILE_READ_ATTRIBUTES | SYNCHRONIZE,
                    DirectoryOpen::ExistingRead => FILE_GENERIC_READ,
                    DirectoryOpen::Create
                    | DirectoryOpen::CreateNew
                    | DirectoryOpen::ExistingReadWrite => FILE_GENERIC_READ | FILE_GENERIC_WRITE,
                },
                &attributes,
                &mut io_status,
                ptr::null(),
                FILE_ATTRIBUTE_NORMAL,
                // Retain the original no-delete-sharing pin until File drops.
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                match mode {
                    DirectoryOpen::Create => FILE_OPEN_IF,
                    DirectoryOpen::CreateNew => FILE_CREATE,
                    DirectoryOpen::ExistingRead
                    | DirectoryOpen::ExistingReadWrite
                    | DirectoryOpen::ExistingPathIdentity => 1, // FILE_OPEN
                },
                FILE_SYNCHRONOUS_IO_NONALERT
                    | FILE_OPEN_REPARSE_POINT
                    | match mode {
                        DirectoryOpen::ExistingPathIdentity => 0,
                        DirectoryOpen::Create
                        | DirectoryOpen::CreateNew
                        | DirectoryOpen::ExistingRead
                        | DirectoryOpen::ExistingReadWrite => FILE_DIRECTORY_FILE,
                    },
                ptr::null(),
                /*ea_length*/ 0,
            )
        };
        if status < 0 {
            if status == STATUS_REPARSE_POINT_ENCOUNTERED {
                return Err(unsafe_state(
                    "private state ancestry contains a reparse point",
                ));
            }
            let error = unsafe { RtlNtStatusToDosError(status) };
            return Err(io::Error::from_raw_os_error(error as i32));
        }
        if handle == 0 || handle == INVALID_HANDLE_VALUE {
            return Err(io::Error::other(
                "NtCreateFile returned an invalid directory handle",
            ));
        }
        // NtCreateFile completed synchronously; transfer its non-inheritable
        // handle exactly once. The descriptor and UTF-16 storage outlive the call.
        Ok(unsafe { File::from_raw_handle(handle as *mut c_void) })
    })
}

#[cfg(test)]
#[path = "private_state_windows_directory_tests.rs"]
mod tests;
