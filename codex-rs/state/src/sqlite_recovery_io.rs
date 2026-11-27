//! Platform-specific descriptor I/O. No source filename is reopened for bytes.

use super::SqliteRecoveryError;
use super::indeterminate;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;

pub(super) fn read_exact_at(file: &File, bytes: &mut [u8]) -> std::io::Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::FileExt;
        file.read_exact_at(bytes, 0)
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::FileExt;
        let mut filled = 0;
        while filled < bytes.len() {
            match file.seek_read(&mut bytes[filled..], filled as u64) {
                Ok(0) => return Err(std::io::ErrorKind::UnexpectedEof.into()),
                Ok(count) => filled += count,
                Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(error) => return Err(error),
            }
        }
        Ok(())
    }
}

pub(super) fn write_private_new(path: &Path, bytes: &[u8]) -> Result<(), SqliteRecoveryError> {
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options
            .mode(0o600)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW);
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
        options
            .read(true)
            .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT);
    }
    let mut file = options.open(path).map_err(indeterminate)?;
    #[cfg(windows)]
    super::windows::require_private_created_file(&file)?;
    file.write_all(bytes).map_err(indeterminate)?;
    file.sync_all().map_err(indeterminate)
}

pub(super) fn sync_directory(path: &Path) -> Result<(), SqliteRecoveryError> {
    #[cfg(unix)]
    let directory = File::open(path).map_err(indeterminate)?;
    #[cfg(windows)]
    let directory = {
        use std::os::windows::fs::OpenOptionsExt;
        use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
        use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
        let directory = OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
            .open(path)
            .map_err(indeterminate)?;
        super::windows::require_private_directory(&directory)?;
        directory
    };
    directory.sync_all().map_err(indeterminate)
}
