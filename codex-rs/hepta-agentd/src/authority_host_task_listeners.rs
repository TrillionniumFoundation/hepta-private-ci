//! Two purpose-fixed listeners in the original Root-controlled runtime parent.
//! Existing paths are never removed for bind. Cleanup removes only the sockets
//! whose exact device/inode this scope created, and accepts each peer once.

use std::fs;
use std::os::fd::OwnedFd;
use std::os::fd::RawFd;
use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::PathBuf;
use std::time::{Duration, Instant};

use crate::AgentdError;
use crate::root_original_task_descriptor::{protocol, require_before};

pub(super) struct TaskListeners {
    task: UnixListener,
    loan: UnixListener,
    guard: SocketGuard,
}

struct SocketGuard(Vec<(PathBuf, u64, u64)>);

impl Drop for SocketGuard {
    fn drop(&mut self) {
        for (path, device, inode) in &self.0 {
            if fs::symlink_metadata(path).is_ok_and(|entry| entry.dev() == *device && entry.ino() == *inode) {
                let _ = fs::remove_file(path);
            }
        }
    }
}

impl TaskListeners {
    pub(super) fn bind(task: &PathBuf, loan: &PathBuf, gid: u32) -> Result<Self, AgentdError> {
        crate::authority_host_runtime::validate_lane_paths(&[task, loan], gid)?;
        let mut guard = SocketGuard(Vec::new());
        let task = bind_one(task, gid, &mut guard)?;
        let loan = bind_one(loan, gid, &mut guard)?;
        Ok(Self { task, loan, guard })
    }

    pub(super) fn accept(&self, owner: &OwnedFd, end: Instant) -> Result<(UnixStream, UnixStream), AgentdError> {
        // The same fixed end covers both accepts; no per-lane startup renewal.
        let task = accept_one(&self.task, owner, end)?;
        let loan = accept_one(&self.loan, owner, end)?;
        for (path, device, inode) in &self.guard.0 {
            let entry = fs::symlink_metadata(path)?;
            if entry.dev() != *device || entry.ino() != *inode {
                return Err(AgentdError::Invalid("original task listener changed".into()));
            }
        }
        require_before(end)?;
        Ok((task, loan))
    }
}

fn bind_one(path: &PathBuf, gid: u32, guard: &mut SocketGuard) -> Result<UnixListener, AgentdError> {
    let listener = UnixListener::bind(path)?;
    let entry = fs::symlink_metadata(path)?;
    guard.0.push((path.clone(), entry.dev(), entry.ino()));
    fs::set_permissions(path, fs::Permissions::from_mode(0o660))?;
    let after = fs::symlink_metadata(path)?;
    if entry.dev() != after.dev() || entry.ino() != after.ino() || after.uid() != 0
        || after.gid() != gid || after.mode() & 0o7777 != 0o660
    { return Err(AgentdError::Invalid("original task socket ownership differs".into())); }
    listener.set_nonblocking(true)?;
    Ok(listener)
}

fn accept_one(listener: &UnixListener, owner: &OwnedFd, end: Instant) -> Result<UnixStream, AgentdError> {
    loop {
        require_before(end)?;
        crate::root_observation_stream::check_lifetime(owner).map_err(protocol)?;
        match listener.accept() {
            Ok((stream, _)) => {
                require_before(end)?;
                crate::root_observation_stream::check_lifetime(owner).map_err(protocol)?;
                return Ok(stream);
            }
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                std::thread::sleep(Duration::from_millis(5).min(end.saturating_duration_since(Instant::now())));
            }
            Err(error) => return Err(error.into()),
        }
    }
}

/// No bytes are decoded here. The caller retains an already peer-authenticated
/// original HAP channel owning this FD. The same startup end covers bind,
/// handoff, accepts and this first-frame barrier; each exchange still has its
/// original 500 ms timeout, 128 aggregate count and original operation end.
pub(super) fn wait_first_frame(fd: RawFd, owner: &OwnedFd, end: Instant) -> Result<(), AgentdError> {
    loop {
        require_before(end)?;
        crate::root_observation_stream::check_lifetime(owner).map_err(protocol)?;
        let left = end.saturating_duration_since(Instant::now());
        let millis = i32::try_from(left.as_millis().saturating_add(1))
            .map_err(|_| AgentdError::Invalid("original task startup bound differs".into()))?;
        let mut entry = libc::pollfd { fd, events: libc::POLLIN, revents: 0 };
        // SAFETY: poll borrows one live descriptor held by the original HAP
        // channel and writes only this initialized scalar pollfd.
        let result = unsafe { libc::poll(&mut entry, 1, millis) };
        if result < 0 {
            let error = std::io::Error::last_os_error();
            if error.kind() == std::io::ErrorKind::Interrupted { continue; }
            return Err(error.into());
        }
        require_before(end)?;
        crate::root_observation_stream::check_lifetime(owner).map_err(protocol)?;
        if result == 0 || entry.revents & (libc::POLLERR | libc::POLLHUP | libc::POLLNVAL) != 0 {
            return Err(AgentdError::Protocol("original task peer ended before its first request".into()));
        }
        if entry.revents & libc::POLLIN != 0 { return Ok(()); }
    }
}
