//! Acquire the private directory without a separate path check or creation.

use std::ffi::c_void;
use std::fs::File;
use std::io;
use std::mem::size_of;
use std::os::windows::io::FromRawHandle;
use std::path::Path;
use std::ptr;

use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::NTSTATUS;
use windows_sys::Win32::Foundation::RtlNtStatusToDosError;
use windows_sys::Win32::Foundation::UNICODE_STRING;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_NORMAL;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK_0;
use windows_sys::Win32::System::Kernel::OBJ_CASE_INSENSITIVE;
use windows_sys::Win32::System::Kernel::OBJ_DONT_REPARSE;

use super::unsafe_state;
use super::wide_path;
use super::with_private_security;

const FILE_OPEN_IF: u32 = 3;
const FILE_DIRECTORY_FILE: u32 = 1;
const FILE_SYNCHRONOUS_IO_NONALERT: u32 = 0x20;
const FILE_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
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

pub(super) fn open(root: &Path) -> io::Result<File> {
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
            security_descriptor: security.lpSecurityDescriptor,
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
                FILE_GENERIC_READ | FILE_GENERIC_WRITE,
                &attributes,
                &mut io_status,
                ptr::null(),
                FILE_ATTRIBUTE_NORMAL,
                // Retain the original no-delete-sharing pin until File drops.
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                FILE_OPEN_IF,
                FILE_DIRECTORY_FILE | FILE_SYNCHRONOUS_IO_NONALERT | FILE_OPEN_REPARSE_POINT,
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

// Recovery must not create a missing parent or repair its permissions. These
// opens share the same native no-reparse boundary as the ordinary owner above.
pub(super) fn open_existing_directory(root: &Path, write: bool) -> io::Result<File> {
    let mut name = wide_path(root)?;
    name[1] = u16::from(b'?');
    for unit in &mut name {
        if *unit == u16::from(b'/') {
            *unit = u16::from(b'\\');
        }
    }
    recovery_open(
        /*parent*/ 0, &mut name, /*is_directory*/ true, /*create*/ false, write,
    )
}

pub(super) fn open_recovery_child(
    parent: &File,
    name: &std::ffi::OsStr,
    create: bool,
) -> io::Result<File> {
    use std::os::windows::ffi::OsStrExt;
    use std::os::windows::io::AsRawHandle;
    use std::path::Component;

    let mut components = Path::new(name).components();
    if !matches!(components.next(), Some(Component::Normal(_))) || components.next().is_some() {
        return Err(unsafe_state("recovery child must be one normal component"));
    }
    let mut name: Vec<u16> = name.encode_wide().collect();
    if name.iter().any(|unit| matches!(*unit, 0 | 47 | 58 | 92)) {
        return Err(unsafe_state(
            "recovery child contains a separator or stream name",
        ));
    }
    name.push(0);
    recovery_open(
        parent.as_raw_handle() as HANDLE,
        &mut name,
        /*is_directory*/ false,
        create,
        create,
    )
}

fn recovery_open(
    parent: HANDLE,
    name: &mut [u16],
    is_directory: bool,
    create: bool,
    write: bool,
) -> io::Result<File> {
    use windows_sys::Win32::Storage::FileSystem::DELETE;

    const FILE_OPEN: u32 = 1;
    const FILE_CREATE: u32 = 2;
    const FILE_NON_DIRECTORY_FILE: u32 = 0x40;
    let maximum_length = u16::try_from(std::mem::size_of_val(name))
        .map_err(|_| unsafe_state("recovery name is too long"))?;
    let object_name = UNICODE_STRING {
        Length: maximum_length - size_of::<u16>() as u16,
        MaximumLength: maximum_length,
        Buffer: name.as_mut_ptr(),
    };
    let open = |security_descriptor: *const c_void| {
        let attributes = ObjectAttributes {
            length: size_of::<ObjectAttributes>() as u32,
            root_directory: parent,
            object_name: &object_name,
            attributes: OBJ_CASE_INSENSITIVE as u32 | OBJ_DONT_REPARSE as u32,
            security_descriptor,
            security_quality_of_service: ptr::null(),
        };
        let mut io_status = IO_STATUS_BLOCK {
            Anonymous: IO_STATUS_BLOCK_0 { Status: 0 },
            Information: 0,
        };
        let mut handle = 0;
        let access = FILE_GENERIC_READ
            | if write { FILE_GENERIC_WRITE } else { 0 }
            | if create { DELETE } else { 0 };
        let share = FILE_SHARE_READ | if is_directory { FILE_SHARE_WRITE } else { 0 };
        // Source files deny both write and delete sharing for the guard's full
        // lifetime. Child names resolve relative to the retained directory,
        // never by rebuilding and reopening a source pathname.
        let status = unsafe {
            NtCreateFile(
                &mut handle,
                access,
                &attributes,
                &mut io_status,
                ptr::null(),
                FILE_ATTRIBUTE_NORMAL,
                share,
                if create { FILE_CREATE } else { FILE_OPEN },
                FILE_SYNCHRONOUS_IO_NONALERT
                    | FILE_OPEN_REPARSE_POINT
                    | if is_directory {
                        FILE_DIRECTORY_FILE
                    } else {
                        FILE_NON_DIRECTORY_FILE
                    },
                ptr::null(),
                /*ea_length*/ 0,
            )
        };
        if status < 0 {
            if status == STATUS_REPARSE_POINT_ENCOUNTERED {
                return Err(unsafe_state("recovery name contains a reparse point"));
            }
            return Err(io::Error::from_raw_os_error(
                unsafe { RtlNtStatusToDosError(status) } as i32,
            ));
        }
        if handle == 0 || handle == INVALID_HANDLE_VALUE {
            return Err(io::Error::other("recovery open returned an invalid handle"));
        }
        // The native synchronous call returned a new non-inheritable handle.
        Ok(unsafe { File::from_raw_handle(handle as *mut c_void) })
    };
    if create {
        with_private_security(|security| open(security.lpSecurityDescriptor))
    } else {
        open(ptr::null())
    }
}
