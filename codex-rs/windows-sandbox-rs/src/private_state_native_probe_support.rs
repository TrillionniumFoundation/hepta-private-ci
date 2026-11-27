//! Test-only Windows mechanism probes, not a private-state backend.
//! No owner ACL policy, immutable executable fallback, or durability receipt is
//! implemented here. The three authoritative stores remain unsupported.

use std::ffi::c_void;
use std::fs::File;
use std::io;
use std::mem::offset_of;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use std::ptr;

use codex_utils_windows_private_state::mechanism;
pub(super) use codex_utils_windows_private_state::mechanism::FILE_CREATE;
pub(super) use codex_utils_windows_private_state::mechanism::FILE_OPEN;
pub(super) use codex_utils_windows_private_state::mechanism::identity;
use serde_json::Value;
use serde_json::json;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::NTSTATUS;
use windows_sys::Win32::Foundation::RtlNtStatusToDosError;
use windows_sys::Win32::Storage::FileSystem::FILE_RENAME_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_RENAME_INFO_0;
use windows_sys::Win32::Storage::FileSystem::GetVolumeInformationByHandleW;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK_0;

// Native FILE_INFORMATION_CLASS, not Win32 FILE_INFO_BY_HANDLE_CLASS.
const FILE_RENAME_INFORMATION_CLASS: u32 = 10;

#[link(name = "ntdll")]
unsafe extern "system" {
    fn NtFlushBuffersFileEx(
        file_handle: HANDLE,
        flags: u32,
        parameters: *const c_void,
        parameters_size: u32,
        io_status_block: *mut IO_STATUS_BLOCK,
    ) -> NTSTATUS;
    fn NtSetInformationFile(
        file_handle: HANDLE,
        io_status_block: *mut IO_STATUS_BLOCK,
        file_information: *const c_void,
        length: u32,
        file_information_class: u32,
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

fn observe_open(observation: mechanism::OpenObservation) {
    emit(
        "NtCreateFile",
        json!({
            "relative_to_held_root": observation.relative_to_held_root, "access": observation.access,
            "sharing": observation.sharing, "disposition": observation.disposition, "options": observation.options,
            "ntstatus": format!("0x{:08x}", observation.ntstatus as u32), "information": observation.information
        }),
    );
}

pub(super) fn open_root(path: &Path) -> io::Result<File> {
    mechanism::open_root(path, observe_open)
}

pub(super) fn open_relative(
    root: &File,
    name: &str,
    access: u32,
    sharing: u32,
    disposition: u32,
) -> io::Result<File> {
    mechanism::open_relative(root, name, access, sharing, disposition, observe_open)
}

pub(super) fn open_relative_directory(root: &File, name: &str) -> io::Result<File> {
    mechanism::open_relative_directory(root, name, observe_open)
}

pub(super) fn rename_relative(root: &File, source: &File, name: &str) -> io::Result<()> {
    #[repr(C)]
    struct RenameBuffer {
        flags: FILE_RENAME_INFO_0,
        root: HANDLE,
        length: u32,
        name: [u16; 64],
    }
    let name = mechanism::leaf_name(name)?;
    if name.len() >= 64 {
        return Err(invalid("probe rename leaf is too long"));
    }
    // C layout and fixed backing storage avoid unaligned flexible-array writes.
    if offset_of!(RenameBuffer, root) != offset_of!(FILE_RENAME_INFO, RootDirectory)
        || offset_of!(RenameBuffer, length) != offset_of!(FILE_RENAME_INFO, FileNameLength)
        || offset_of!(RenameBuffer, name) != offset_of!(FILE_RENAME_INFO, FileName)
    {
        return Err(io::Error::other("FILE_RENAME_INFO layout mismatch"));
    }
    let mut information = RenameBuffer {
        flags: FILE_RENAME_INFO_0 { Flags: 1 },
        root: root.as_raw_handle() as HANDLE,
        length: (name.len() * size_of::<u16>()) as u32,
        name: [0; 64],
    };
    information.name[..name.len()].copy_from_slice(&name);
    let mut status_block = IO_STATUS_BLOCK {
        Anonymous: IO_STATUS_BLOCK_0 { Status: 0 },
        Information: 0,
    };
    // SAFETY: the live source/root handles and C-layout buffer cover every byte
    // specified. FileRenameInformation directly accepts a held RootDirectory
    // and counted relative leaf; no Win32 path conversion or CWD lookup occurs.
    // Flags=1 initializes the first BOOLEAN to ReplaceIfExists and clears the
    // remaining union bytes; no POSIX/readonly-ignore semantics are requested.
    // The source was opened synchronously by open_nt and remains live here.
    let status = unsafe {
        NtSetInformationFile(
            source.as_raw_handle() as HANDLE,
            &mut status_block,
            (&raw const information).cast(),
            size_of::<RenameBuffer>() as u32,
            FILE_RENAME_INFORMATION_CLASS,
        )
    };
    emit(
        "NtSetInformationFile",
        json!({
            "relative_to_held_root": true, "information_class": FILE_RENAME_INFORMATION_CLASS,
            "replace_if_exists": true, "name_bytes": information.length,
            "buffer_bytes": size_of::<RenameBuffer>(), "ntstatus": format!("0x{:08x}", status as u32)
        }),
    );
    let result = if status < 0 {
        // SAFETY: this pure conversion accepts the returned native status.
        let code = unsafe { RtlNtStatusToDosError(status) };
        Err(io::Error::from_raw_os_error(code as i32))
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
