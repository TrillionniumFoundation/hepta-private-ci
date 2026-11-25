//! Retain the root installer's existing deployment lock across native startup.
use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::MetadataExt;
use std::path::Path;

pub(super) struct NativeDeploymentLock {
    _file: File,
}

/// Call only in the post-fork UI child. Keep descriptors usable by exec's
/// /proc/self/fd program path and error pipe, but close every inherited alias
/// when exec succeeds. A lock-only CLOEXEC flag would leave dup aliases usable.
pub(super) fn protect_child_descriptors() -> io::Result<()> {
    // SAFETY: close_range with CLOEXEC changes descriptor flags, takes no
    // pointers and is async-signal-safe. It does not close the exec program fd.
    if unsafe {
        libc::syscall(
            libc::SYS_close_range,
            3u32,
            u32::MAX,
            libc::CLOSE_RANGE_CLOEXEC,
        )
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

/// Managed Desktop releases must use the installer lock for that exact prefix,
/// including callers which use the backwards-compatible generic Root entry.
pub(super) fn verify_program_lock(
    program: &Path,
    lock: Option<&NativeDeploymentLock>,
) -> io::Result<()> {
    let Some(bin) = program.parent() else {
        return Ok(());
    };
    let Some(release) = bin.parent() else {
        return Ok(());
    };
    let Some(releases) = release.parent() else {
        return Ok(());
    };
    let Some(prefix) = releases.parent() else {
        return Ok(());
    };
    let id = release
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("");
    if program.file_name().is_none_or(|name| name != "trill-shell")
        || bin.file_name().is_none_or(|name| name != "bin")
        || releases.file_name().is_none_or(|name| name != "releases")
        || id.len() != 25
        || !id.as_bytes().iter().enumerate().all(|(i, byte)| {
            if i == 12 {
                *byte == b'-'
            } else {
                byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase()
            }
        })
    {
        return Ok(());
    }
    let lock = lock.ok_or_else(|| {
        io::Error::other("managed Desktop release requires its original deployment lock")
    })?;
    let expected = std::fs::symlink_metadata(prefix.join(".native-deployment.lock"))?;
    let actual = lock._file.metadata()?;
    if !expected.is_file()
        || expected.uid() != 0
        || expected.nlink() != 1
        || expected.mode() & 0o7777 != 0o600
        || (expected.dev(), expected.ino()) != (actual.dev(), actual.ino())
    {
        return Err(io::Error::other(
            "native deployment lock does not belong to this installed release",
        ));
    }
    Ok(())
}

impl NativeDeploymentLock {
    pub(super) fn from_inherited(descriptor: OwnedFd) -> io::Result<Self> {
        let file = File::from(descriptor);
        let metadata = file.metadata()?;
        if !metadata.is_file()
            || metadata.uid() != 0
            || metadata.nlink() != 1
            || metadata.mode() & 0o7777 != 0o600
        {
            return Err(io::Error::other(
                "deployment lock must be one linked root-owned mode0600 regular file",
            ));
        }
        let fd = file.as_raw_fd();
        // SAFETY: these calls only operate on our live, owned descriptor.
        let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
        if flags < 0 || flags & libc::O_ACCMODE != libc::O_RDWR {
            return Err(io::Error::other(
                "deployment lock requires a read/write descriptor",
            ));
        }
        // flock is tied to this open file description. The installer already
        // holds it; another independently opened lock must never be displaced.
        // SAFETY: fd is live and flock takes no pointers.
        if unsafe { libc::flock(fd, libc::LOCK_EX | libc::LOCK_NB) } != 0 {
            return Err(io::Error::last_os_error());
        }
        // Root keeps the lock for its entire serving lifetime. Its UI child
        // must not inherit a writable root descriptor or the ability to unlock.
        // SAFETY: fcntl changes only this owned descriptor's inheritance flag.
        if unsafe { libc::fcntl(fd, libc::F_SETFD, libc::FD_CLOEXEC) } != 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(Self { _file: file })
    }
}

#[cfg(test)]
#[path = "authority_host_native_deployment_tests.rs"]
mod tests;
