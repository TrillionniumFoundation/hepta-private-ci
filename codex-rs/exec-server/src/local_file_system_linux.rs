use std::io;
use std::os::fd::RawFd;
use std::path::Path;

use codex_utils_absolute_path::AbsolutePathBuf;
use rustix::fs::CWD;
use rustix::fs::Mode;
use rustix::fs::OFlags;
use rustix::fs::ResolveFlags;
use rustix::fs::openat2;

use super::authorized_read_error;
use super::redact_file_access_error;
use super::unique_std_file_identity;

/// Reopen the resolved path without following any symlink or magic link.
///
/// The descriptor, rather than another pathname lookup, supplies the regular
/// file and single-link checks. The caller also compares its identity with the
/// original handle and authorizes its kernel-reported path before reading it.
pub(super) fn secure_open_unique_without_symlinks(path: &Path) -> io::Result<std::fs::File> {
    let descriptor = openat2(
        CWD,
        path,
        OFlags::RDONLY | OFlags::CLOEXEC | OFlags::NONBLOCK | OFlags::NOCTTY,
        Mode::empty(),
        ResolveFlags::NO_SYMLINKS | ResolveFlags::NO_MAGICLINKS,
    )?;
    let file = std::fs::File::from(descriptor);
    unique_std_file_identity(&file)?;
    Ok(file)
}

/// Resolve a live descriptor through procfs; unavailable procfs fails closed.
pub(super) fn stable_file_path_from_raw_fd(fd: RawFd) -> io::Result<AbsolutePathBuf> {
    let path =
        std::fs::read_link(format!("/proc/self/fd/{fd}")).map_err(redact_file_access_error)?;
    AbsolutePathBuf::from_absolute_path(path)
        .map_err(|_| authorized_read_error(io::ErrorKind::PermissionDenied))
}
