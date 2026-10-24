//! Filesystem publication mechanism, without private-owner qualification.

use std::ffi::c_void;
use std::fs::File;
use std::io;
use std::io::Write;
use std::mem::offset_of;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use std::ptr;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::NTSTATUS;
use windows_sys::Win32::Foundation::RtlNtStatusToDosError;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK_0;

// FILE_RENAME_INFORMATION begins with a BOOLEAN/ULONG union. Initializing
// this storage to integer one sets ReplaceIfExists and leaves padding zero.
#[repr(C)]
struct RenameInfo {
    replace_if_exists: u32,
    root_directory: *mut c_void,
    file_name_length: u32,
    file_name: [u16; 1],
}

#[link(name = "ntdll")]
unsafe extern "system" {
    fn NtSetInformationFile(
        file: HANDLE,
        completion: *mut IO_STATUS_BLOCK,
        information: *const c_void,
        buffer_size: u32,
        information_class: i32,
    ) -> NTSTATUS;
}

/// An actual non-overlapped stage, without private-owner qualification.
///
/// Only the real relative native create can construct this object. It exposes
/// neither an arbitrary-File adapter, cloned/raw handle nor caller-set mode.
/// Its access and inherited descriptor remain ordinary filesystem mechanisms.
pub struct SynchronousStageFile {
    file: File,
}

impl SynchronousStageFile {
    /// CREATE_NEW under the held root, retaining the original read/write sharing.
    /// The native producer adds SYNCHRONIZE and FILE_SYNCHRONOUS_IO_NONALERT.
    pub fn create_relative(directory: &File, leaf: &str, access: u32) -> io::Result<Self> {
        if leaf.len() > 128 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "staging leaf is too long",
            ));
        }
        let file = crate::mechanism::open_relative(
            directory,
            leaf,
            access,
            /*sharing*/ 3,
            crate::mechanism::FILE_CREATE,
            |_| {},
        )?;
        Ok(Self { file })
    }
}

impl Write for SynchronousStageFile {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.file.write(bytes)
    }

    fn flush(&mut self) -> io::Result<()> {
        self.file.flush()
    }
}

/// Sync and replace a relative leaf using the exact held staging file.
///
/// This is a file mechanism, not a private-directory constructor. Callers must
/// already hold their independently admitted directory and stage capabilities.
/// The stage needs DELETE access; no path reopen or delete-sharing fallback is
/// attempted. A successful return still requires the caller's real directory
/// sync and its existing indeterminate-commit handling. It does not establish
/// namespace provenance, access isolation or power-loss qualification.
pub fn replace_synced_state_stage(
    directory: &File,
    stage: &SynchronousStageFile,
    leaf: &str,
) -> io::Result<()> {
    // SAFETY: the private file can only originate from the synchronous relative
    // producer above; safe callers cannot replace its mode or create an alias.
    unsafe { replace_synced_synchronous_stage(directory, &stage.file, leaf) }
}

/// Same mechanism for the internal owner file's already-proven native producer.
///
/// # Safety
/// The exact stage file object must originate from mechanism::open_nt with
/// FILE_SYNCHRONOUS_IO_NONALERT | SYNCHRONIZE, without an escaped raw/cloned
/// handle or any way to change that mode. No arbitrary File may enter here.
pub(crate) unsafe fn replace_synced_synchronous_stage(
    directory: &File,
    stage: &File,
    leaf: &str,
) -> io::Result<()> {
    if leaf.is_empty()
        || leaf.len() > 128
        || matches!(leaf, "." | "..")
        || leaf.ends_with('.')
        || !leaf
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-' | b'_'))
        || !directory.metadata()?.is_dir()
        || !stage.metadata()?.is_file()
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "state replacement requires held directory/file and a bounded leaf",
        ));
    }
    let name: Vec<u16> = leaf.encode_utf16().collect();
    let name_bytes = name.len() * size_of::<u16>();
    let bytes = size_of::<RenameInfo>() + name_bytes;
    // usize storage supplies native pointer alignment; the bounded trailing
    // name and terminating zero fit beyond the fixed C header on x86/ARM64/x64.
    let mut storage = vec![0_usize; bytes.div_ceil(size_of::<usize>())];
    let header = storage.as_mut_ptr().cast::<RenameInfo>();
    // SAFETY: storage is aligned and large enough for the complete fixed
    // header and UTF-16 name. Both borrowed File handles stay live throughout
    // the synchronous native call below.
    unsafe {
        ptr::write(
            header,
            RenameInfo {
                replace_if_exists: 1,
                root_directory: directory.as_raw_handle(),
                file_name_length: name_bytes as u32,
                file_name: [0],
            },
        );
        ptr::copy_nonoverlapping(
            name.as_ptr(),
            storage
                .as_mut_ptr()
                .cast::<u8>()
                .add(offset_of!(RenameInfo, file_name))
                .cast::<u16>(),
            name.len(),
        );
    }
    stage.sync_all()?;
    let mut completion = IO_STATUS_BLOCK {
        Anonymous: IO_STATUS_BLOCK_0 { Status: -1 },
        Information: 0,
    };
    // FileRenameInformation = 10: the native layer consumes the literal leaf
    // relative to this non-null held root without a Win32 path conversion.
    // https://learn.microsoft.com/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_rename_information
    // SAFETY: the checked producer used FILE_SYNCHRONOUS_IO_NONALERT and
    // SYNCHRONIZE. The I/O manager waits for all I/O on this file object before
    // returning, including internally pending work; it cannot outlive either
    // initialized buffer. No caller-owned asynchronous File is admitted.
    let status = unsafe {
        NtSetInformationFile(
            stage.as_raw_handle() as HANDLE,
            &mut completion,
            header.cast(),
            bytes as u32,
            /*information_class*/ 10,
        )
    };
    if status != 0 {
        // SAFETY: the returned completed NTSTATUS is a valid conversion input.
        return Err(io::Error::from_raw_os_error(
            unsafe { RtlNtStatusToDosError(status) } as i32,
        ));
    }
    // SAFETY: synchronous completion initialized this native status union.
    let completed = unsafe { completion.Anonymous.Status };
    if completed != 0 {
        // SAFETY: this conversion accepts the actual completed NTSTATUS.
        return Err(io::Error::from_raw_os_error(
            unsafe { RtlNtStatusToDosError(completed) } as i32,
        ));
    }
    Ok(())
}
