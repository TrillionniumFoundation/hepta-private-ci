//! Filesystem publication mechanism, without private-owner qualification.

use std::ffi::c_void;
use std::fs::File;
use std::io;
use std::mem::offset_of;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use std::ptr;

// FILE_RENAME_INFO begins with a four-byte BOOLEAN/DWORD union. Initializing
// this storage to integer one sets ReplaceIfExists and leaves padding zero.
#[repr(C)]
struct RenameInfo {
    replace_if_exists: u32,
    root_directory: *mut c_void,
    file_name_length: u32,
    file_name: [u16; 1],
}

#[link(name = "kernel32")]
unsafe extern "system" {
    fn SetFileInformationByHandle(
        file: *mut c_void,
        information_class: i32,
        information: *const c_void,
        buffer_size: u32,
    ) -> i32;
}

/// Sync and replace a relative leaf using the exact held staging file.
///
/// This is a file mechanism, not a private-directory constructor. Callers must
/// already hold their independently admitted directory and stage capabilities.
/// The stage needs DELETE access; no path reopen or delete-sharing fallback is
/// attempted. A successful return still requires the caller's real directory
/// sync and its existing indeterminate-commit handling. It does not establish
/// namespace provenance, access isolation or power-loss qualification.
pub fn replace_synced_state_stage(directory: &File, stage: &File, leaf: &str) -> io::Result<()> {
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
    // the synchronous Win32 call; no kernel IO_STATUS_BLOCK escapes the stack.
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
    // FileRenameInfo = 3. A relative FileName resolves against RootDirectory,
    // while the source is this exact original staging handle, never its name.
    // https://learn.microsoft.com/windows/win32/api/winbase/ns-winbase-file_rename_info
    // SAFETY: all initialized input storage and handles remain live through
    // SetFileInformationByHandle, which returns its completed BOOL result.
    if unsafe { SetFileInformationByHandle(stage.as_raw_handle(), 3, header.cast(), bytes as u32) }
        == 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}
