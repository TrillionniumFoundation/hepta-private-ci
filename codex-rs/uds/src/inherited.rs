//! Adoption never changes a socket path or its parent's permissions.

use std::io;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::fs::MetadataExt;
use std::path::Path;

use crate::UnixListener;

impl UnixListener {
    /// Adopt one already-listening Linux Unix socket at the exact private
    /// rendezvous supplied by its owner. The caller retains pathname cleanup
    /// ownership; this listener only owns the descriptor. In particular this
    /// operation does not bind, listen, chmod, probe or unlink any path.
    pub fn from_inherited(fd: OwnedFd, expected_path: &Path) -> io::Result<Self> {
        for (option, expected) in [
            (libc::SO_DOMAIN, libc::AF_UNIX),
            (libc::SO_TYPE, libc::SOCK_STREAM),
            (libc::SO_ACCEPTCONN, 1),
        ] {
            let mut value: libc::c_int = 0;
            let mut length = std::mem::size_of_val(&value) as libc::socklen_t;
            // SAFETY: fd and both output buffers remain live for getsockopt.
            let result = unsafe {
                libc::getsockopt(fd.as_raw_fd(), libc::SOL_SOCKET, option,
                    std::ptr::from_mut(&mut value).cast(), &mut length)
            };
            if result != 0 { return Err(io::Error::last_os_error()); }
            if length as usize != std::mem::size_of_val(&value) || value != expected {
                return Err(io::Error::new(io::ErrorKind::InvalidInput,
                    "inherited listener must be a listening Unix stream socket"));
            }
        }
        let listener = std::os::unix::net::UnixListener::from(fd);
        let node = std::fs::symlink_metadata(expected_path)?;
        // SAFETY: geteuid reads the current process identity.
        if !expected_path.is_absolute() || expected_path.canonicalize()? != expected_path
            || listener.local_addr()?.as_pathname() != Some(expected_path)
            || !node.file_type().is_socket() || node.nlink() != 1
            || node.uid() != unsafe { libc::geteuid() } || node.mode() & 0o7777 != 0o600
        {
            return Err(io::Error::new(io::ErrorKind::PermissionDenied,
                "inherited listener must name its exact current-owner private socket"));
        }
        listener.set_nonblocking(true)?;
        super::platform::from_std(listener).map(|inner| Self { inner })
    }
}

#[cfg(test)]
#[path = "inherited_tests.rs"]
mod tests;
