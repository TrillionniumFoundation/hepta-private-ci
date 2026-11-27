//! Compare Windows filesystem identities through borrowed file handles.

use std::fs::File;
use std::io;
use std::os::windows::io::AsRawHandle;

use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Storage::FileSystem::FILE_ID_128;
use windows_sys::Win32::Storage::FileSystem::FILE_ID_INFO;
use windows_sys::Win32::Storage::FileSystem::FileIdInfo;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandleEx;

/// Compare the volume and full 128-bit file identifier of two open handles.
///
/// Both identity queries must succeed. Unsupported identity queries return an
/// error; there is no size or shortened-identifier fallback.
/// Callers retain both handles. This compares their objects at observation time,
/// and does not authenticate a pathname, its permissions, or future path lookups.
pub fn same_file_handles(left: &File, right: &File) -> io::Result<bool> {
    Ok(file_identity(left)? == file_identity(right)?)
}

fn file_identity(file: &File) -> io::Result<(u64, [u8; 16])> {
    let mut information = FILE_ID_INFO {
        VolumeSerialNumber: 0,
        FileId: FILE_ID_128 {
            Identifier: [0; 16],
        },
    };
    // SAFETY: File retains a valid borrowed handle for this call. The writable,
    // initialized buffer has the FILE_ID_INFO layout and its exact byte length.
    let succeeded = unsafe {
        GetFileInformationByHandleEx(
            file.as_raw_handle() as HANDLE,
            FileIdInfo,
            std::ptr::from_mut(&mut information).cast(),
            std::mem::size_of::<FILE_ID_INFO>() as u32,
        )
    };
    if succeeded == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok((
        information.VolumeSerialNumber,
        information.FileId.Identifier,
    ))
}

#[cfg(test)]
#[path = "file_identity_windows_tests.rs"]
mod tests;
