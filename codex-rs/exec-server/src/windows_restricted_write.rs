use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Write;
use std::mem::MaybeUninit;
use std::mem::size_of;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::PathBuf;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_STANDARD_INFO;
use windows_sys::Win32::Storage::FileSystem::FileStandardInfo;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandleEx;
use windows_sys::Win32::Storage::FileSystem::SECURITY_IDENTIFICATION;

fn require_single_link(file: &File) -> io::Result<()> {
    let mut info = MaybeUninit::<FILE_STANDARD_INFO>::uninit();
    // SAFETY: `file` retains the handle and `info` has the exact queried layout and size.
    let result = unsafe {
        GetFileInformationByHandleEx(
            file.as_raw_handle() as HANDLE,
            FileStandardInfo,
            info.as_mut_ptr().cast(),
            size_of::<FILE_STANDARD_INFO>() as u32,
        )
    };
    if result == 0 {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            format!(
                "restricted filesystem write could not verify link count: {}",
                io::Error::last_os_error()
            ),
        ));
    }
    // SAFETY: the successful query initialized the complete FILE_STANDARD_INFO.
    let info = unsafe { info.assume_init() };
    if info.NumberOfLinks != 1 {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "restricted filesystem write requires a file with exactly one hard link",
        ));
    }
    Ok(())
}

pub(crate) async fn write_file(
    path: PathBuf,
    contents: Vec<u8>,
    follow_symlinks: bool,
) -> io::Result<()> {
    tokio::task::spawn_blocking(move || {
        let mut file = if follow_symlinks {
            let file = OpenOptions::new()
                .write(true)
                .create(true)
                .truncate(false)
                .access_mode(FILE_GENERIC_WRITE | FILE_READ_ATTRIBUTES)
                .security_qos_flags(SECURITY_IDENTIFICATION)
                .open(&path)?;
            if !crate::regular_file::is_disk_file(&file) || !file.metadata()?.is_file() {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    format!("path `{}` is not a file", path.display()),
                ));
            }
            file
        } else {
            crate::no_follow::open_file_for_write(&path)?
        };
        // This rejects aliases present at the query. The retained handle binds the
        // check and write to one file; it does not prevent concurrent alias creation.
        require_single_link(&file)?;
        file.set_len(0)?;
        file.write_all(&contents)
    })
    .await
    .map_err(|error| io::Error::other(format!("filesystem task failed: {error}")))?
}

#[cfg(test)]
#[path = "windows_restricted_write_tests.rs"]
mod tests;
