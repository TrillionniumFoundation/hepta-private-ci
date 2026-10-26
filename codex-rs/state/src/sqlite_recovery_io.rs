//! Platform-specific descriptor I/O. No source filename is reopened for bytes.

use super::SqliteRecoveryError;
use super::indeterminate;
use std::fs::File;
#[cfg(unix)]
use std::fs::OpenOptions;
#[cfg(unix)]
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
    #[cfg(windows)]
    {
        let parent = path.parent().ok_or(SqliteRecoveryError::Indeterminate)?;
        let name = path.file_name().ok_or(SqliteRecoveryError::Indeterminate)?;
        codex_utils_path::RetainedPrivateDirectory::open_existing(parent)
            .and_then(|directory| directory.write_new_child(name, bytes))
            .map(|_| ())
            .map_err(indeterminate)
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        let mut options = OpenOptions::new();
        options
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW);
        let mut file = options.open(path).map_err(indeterminate)?;
        file.write_all(bytes).map_err(indeterminate)?;
        file.sync_all().map_err(indeterminate)
    }
}

pub(super) fn sync_directory(path: &Path) -> Result<(), SqliteRecoveryError> {
    #[cfg(windows)]
    {
        codex_utils_path::RetainedPrivateDirectory::open_existing(path)
            .and_then(|directory| directory.sync_verified())
            .map_err(indeterminate)
    }
    #[cfg(unix)]
    {
        let directory = File::open(path).map_err(indeterminate)?;
        directory.sync_all().map_err(indeterminate)
    }
}
