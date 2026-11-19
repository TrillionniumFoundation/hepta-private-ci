//! Held-directory traversal shared by owner-local files and research material checks.

use std::ffi::CString;
use std::fs::File;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::unix::ffi::OsStrExt;
use std::path::Component;
use std::path::Path;

use anyhow::ensure;

// Every component is opened relative to a held directory, with NOFOLLOW.
// There is no canonicalize-then-open race, and a FIFO cannot block a read.
pub(crate) fn open_at(dir: &File, name: &std::ffi::OsStr, flags: i32) -> std::io::Result<File> {
    let name = CString::new(name.as_bytes())?;
    // SAFETY: name is a live NUL-terminated string and dir owns its fd. A
    // successful openat returns a new descriptor uniquely owned by File.
    let fd = unsafe {
        libc::openat(
            dir.as_raw_fd(),
            name.as_ptr(),
            flags | libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK,
            0o600,
        )
    };
    if fd < 0 {
        return Err(std::io::Error::last_os_error());
    }
    // SAFETY: successful openat returned this uniquely owned descriptor.
    Ok(unsafe { File::from_raw_fd(fd) })
}

pub(crate) fn directory(path: &Path) -> anyhow::Result<File> {
    ensure!(path.is_absolute(), "absolute material path required");
    let mut fd = File::open("/")?;
    for component in path.components() {
        match component {
            Component::RootDir => {}
            Component::Normal(name) => fd = open_at(&fd, name, libc::O_RDONLY | libc::O_DIRECTORY)?,
            _ => anyhow::bail!("non-normal path component"),
        }
    }
    Ok(fd)
}
