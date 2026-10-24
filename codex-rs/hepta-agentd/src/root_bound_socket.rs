//! Root retains pathname custody; only the actual Agentd owner calls listen.

use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

use crate::AgentdError;

/// Create only a bound AF_UNIX/SOCK_STREAM descriptor under an existing Root
/// directory. This function never listens, replaces an existing node, changes
/// a directory or grants authority. Root owns later pathname cleanup. The
/// dedicated child receives this descriptor through its original launch.
pub fn bind_root_agentd_socket(path: &Path, uid: u32, gid: u32) -> Result<OwnedFd, AgentdError> {
    // SAFETY: getuid/geteuid only read the actual current credentials.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0
        || matches!(uid, 0 | u32::MAX) || matches!(gid, 0 | u32::MAX)
    { return Err(refused("binding requires actual Root and a dedicated non-Root owner")); }
    require_root_parent(path)?;
    match std::fs::symlink_metadata(path) {
        Err(error) if error.kind() == io::ErrorKind::NotFound => {}
        Err(error) => return Err(error.into()),
        Ok(_) => return Err(refused("Root socket rendezvous already exists")),
    }
    let bytes = path.as_os_str().as_bytes();
    // SAFETY: a zeroed sockaddr_un is valid before assigning its family/path.
    let mut address: libc::sockaddr_un = unsafe { std::mem::zeroed() };
    if bytes.is_empty() || bytes.len() >= address.sun_path.len() || bytes.contains(&0) {
        return Err(refused("Root socket pathname exceeds the Linux pathname bound"));
    }
    address.sun_family = libc::AF_UNIX as libc::sa_family_t;
    for (destination, source) in address.sun_path.iter_mut().zip(bytes) {
        *destination = *source as libc::c_char;
    }
    // SAFETY: socket takes scalar constants and returns one new owned fd.
    let raw = unsafe { libc::socket(libc::AF_UNIX, libc::SOCK_STREAM | libc::SOCK_CLOEXEC | libc::SOCK_NONBLOCK, 0) };
    if raw < 0 { return Err(io::Error::last_os_error().into()); }
    // SAFETY: this call takes ownership of exactly the new socket descriptor.
    let socket = unsafe { OwnedFd::from_raw_fd(raw) };
    let length = (std::mem::offset_of!(libc::sockaddr_un, sun_path) + bytes.len() + 1) as libc::socklen_t;
    // SAFETY: address contains a bounded, NUL-terminated pathname; socket is live.
    if unsafe { libc::bind(socket.as_raw_fd(), std::ptr::from_ref(&address).cast(), length) } != 0 {
        return Err(io::Error::last_os_error().into());
    }
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    let name = std::ffi::CString::new(bytes).map_err(|_| refused("invalid socket pathname"))?;
    // SAFETY: Root exclusively owns every parent directory, and bind created
    // this new node. chown changes only the socket node, never a run directory.
    if unsafe { libc::chown(name.as_ptr(), uid, gid) } != 0 {
        return Err(io::Error::last_os_error().into());
    }
    let node = std::fs::symlink_metadata(path)?;
    if (node.uid(), node.gid(), node.mode() & 0o7777) != (uid, gid, 0o600) {
        return Err(refused("Root socket node custody was not established"));
    }
    Ok(socket)
}

/// Validate and listen once as the actual final owner. A Root-listening fd is
/// rejected, because Linux captures SO_PEERCRED at listen time. No pathname
/// ownership or directory permissions are changed; there is no bind fallback.
pub fn listen_root_bound_socket(socket: OwnedFd, path: &Path) -> Result<OwnedFd, AgentdError> {
    let before = validate_root_bound_socket(&socket, path)?;
    // SAFETY: validation established one unconnected, bound Unix stream socket.
    if unsafe { libc::listen(socket.as_raw_fd(), 128) } != 0 {
        return Err(io::Error::last_os_error().into());
    }
    let after = std::fs::symlink_metadata(path)?;
    require_root_parent(path)?;
    if (before.dev(), before.ino(), before.uid(), before.gid(), before.mode())
        != (after.dev(), after.ino(), after.uid(), after.gid(), after.mode())
    { return Err(refused("Root rendezvous changed while the owner began listening")); }
    Ok(socket)
}

pub(crate) fn validate_root_bound_socket(socket: &OwnedFd, path: &Path) -> Result<std::fs::Metadata, AgentdError> {
    // SAFETY: these calls only read actual credentials.
    let (uid, gid) = unsafe { (libc::geteuid(), libc::getegid()) };
    if uid == 0 || gid == 0 { return Err(refused("listen must follow the original dedicated-owner drop")); }
    crate::authority_host_runtime::verify_process_credentials(std::process::id(), uid, gid)?;
    require_root_parent(path)?;
    for (option, expected) in [(libc::SO_DOMAIN, libc::AF_UNIX), (libc::SO_TYPE, libc::SOCK_STREAM), (libc::SO_ACCEPTCONN, 0)] {
        let mut value: libc::c_int = 0;
        let mut length = std::mem::size_of_val(&value) as libc::socklen_t;
        // SAFETY: the held fd and correctly sized output buffers remain live.
        if unsafe { libc::getsockopt(socket.as_raw_fd(), libc::SOL_SOCKET, option,
            std::ptr::from_mut(&mut value).cast(), &mut length) } != 0
        { return Err(io::Error::last_os_error().into()); }
        if length as usize != std::mem::size_of_val(&value) || value != expected {
            return Err(refused("expected one Root-bound, not-yet-listening Unix stream socket"));
        }
    }
    let creator = File::from(socket.try_clone()?).metadata()?;
    let descriptor = std::os::unix::net::UnixStream::from(socket.try_clone()?);
    if !creator.file_type().is_socket() || creator.uid() != 0
        || descriptor.local_addr()?.as_pathname() != Some(path)
    { return Err(refused("inherited descriptor was not created by Root at the exact rendezvous")); }
    match descriptor.peer_addr() {
        Err(error) if error.raw_os_error() == Some(libc::ENOTCONN) => {}
        _ => return Err(refused("Root-bound descriptor must not already have a peer")),
    }
    let node = std::fs::symlink_metadata(path)?;
    if !node.file_type().is_socket() || node.nlink() != 1 || node.uid() != uid
        || node.gid() != gid || node.mode() & 0o7777 != 0o600
        || path.canonicalize()? != path
    { return Err(refused("Root rendezvous must be the exact dedicated-owner private socket node")); }
    Ok(node)
}

fn require_root_parent(path: &Path) -> Result<(), AgentdError> {
    let parent = path.parent().ok_or_else(|| refused("missing Root socket parent"))?;
    if !path.is_absolute() || parent.canonicalize()? != parent || path.file_name().is_none() {
        return Err(refused("socket requires an absolute canonical Root parent"));
    }
    for ancestor in parent.ancestors() {
        let metadata = std::fs::symlink_metadata(ancestor)?;
        if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
            return Err(refused("socket ancestors must retain exclusive Root pathname custody"));
        }
    }
    Ok(())
}

fn refused(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("original Root-bound socket: {message}"))
}

#[cfg(test)]
#[path = "root_bound_socket_tests.rs"]
mod tests;
