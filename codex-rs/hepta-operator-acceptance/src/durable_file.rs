use std::fs::File;
#[cfg(not(windows))]
use std::fs::OpenOptions;
use std::path::Path;

#[cfg(windows)]
use super::windows;
use crate::AcceptanceError;

pub(super) fn same_file_snapshot(before: &std::fs::Metadata, after: &std::fs::Metadata) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        before.dev() == after.dev()
            && before.ino() == after.ino()
            && before.len() == after.len()
            && before.mtime() == after.mtime()
            && before.mtime_nsec() == after.mtime_nsec()
            && before.ctime() == after.ctime()
            && before.ctime_nsec() == after.ctime_nsec()
            && before.mode() == after.mode()
            && before.nlink() == after.nlink()
    }
    #[cfg(not(unix))]
    {
        before.len() == after.len() && before.modified().ok() == after.modified().ok()
    }
}

#[cfg(not(windows))]
pub(super) fn same_file_identity(before: &std::fs::Metadata, after: &std::fs::Metadata) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        before.dev() == after.dev() && before.ino() == after.ino()
    }
    #[cfg(not(unix))]
    {
        before.is_dir() == after.is_dir()
    }
}

#[cfg(windows)]
pub(super) fn open_reader(path: &Path) -> Result<(File, windows::ParentPin), AcceptanceError> {
    let parent = windows::ParentPin::for_file(path)?;
    let file = parent.read(path)?;
    Ok((file, parent))
}

#[cfg(not(windows))]
pub(super) fn open_reader(path: &Path) -> Result<(File, ()), AcceptanceError> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW);
    }
    Ok((options.open(path)?, ()))
}
