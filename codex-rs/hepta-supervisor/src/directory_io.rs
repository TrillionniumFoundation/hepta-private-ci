//! Directory synchronization rejects a substituted special file before open can
//! wait on it. Host filesystem progress and ancestor integrity remain separate.

use std::io;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;

pub(crate) fn sync_directory(path: &Path) -> io::Result<()> {
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC)
        .open(path)?;
    if !file.metadata()?.is_dir() {
        return Err(io::Error::new(
            io::ErrorKind::NotADirectory,
            "opened sync target must be a directory",
        ));
    }
    file.sync_all()
}

#[cfg(test)]
#[path = "directory_io_tests.rs"]
mod tests;
