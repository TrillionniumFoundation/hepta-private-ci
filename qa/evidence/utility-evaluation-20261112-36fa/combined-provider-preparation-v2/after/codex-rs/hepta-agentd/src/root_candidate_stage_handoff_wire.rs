//! Fixed twenty role rights and one original Root pidfd. Old handoff limits
//! and both existing two-right purposes are deliberately unchanged.

use std::mem;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::fd::RawFd;
use std::os::unix::net::UnixDatagram;
use std::time::Duration;
use crate::AgentdError;
use super::refused;

const RIGHTS: usize = 21;
const BOUND: usize = 16_384;

pub(super) fn send(socket: &UnixDatagram, bytes: &[u8], rights: &[RawFd], timeout: Duration) -> Result<(), AgentdError> {
    if rights.len() != RIGHTS || bytes.is_empty() || bytes.len() > BOUND {
        return Err(refused("exact bounded candidate packet required"));
    }
    socket.set_nonblocking(false)?;
    socket.set_write_timeout(Some(timeout))?;
    let mut control = [0_usize; 32];
    let mut vector = libc::iovec { iov_base: bytes.as_ptr().cast_mut().cast(), iov_len: bytes.len() };
    // SAFETY: the message is initialized below with retained aligned buffers.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    let length = mem::size_of_val(rights);
    // SAFETY: scalar alignment calculation for a fixed bounded FD array.
    message.msg_controllen = unsafe { libc::CMSG_SPACE(length as u32) } as usize;
    if message.msg_controllen > mem::size_of_val(&control) {
        return Err(refused("candidate ancillary bound exceeded"));
    }
    // SAFETY: the complete header and FD array fit in the live aligned buffer.
    unsafe {
        let header = libc::CMSG_FIRSTHDR(&message);
        (*header).cmsg_level = libc::SOL_SOCKET;
        (*header).cmsg_type = libc::SCM_RIGHTS;
        (*header).cmsg_len = libc::CMSG_LEN(length as u32) as usize;
        std::ptr::copy_nonoverlapping(rights.as_ptr(), libc::CMSG_DATA(header).cast(), rights.len());
    }
    // SAFETY: sendmsg only borrows these exact retained buffers and FD array.
    let count = unsafe { libc::sendmsg(socket.as_raw_fd(), &message, libc::MSG_NOSIGNAL) };
    if count < 0 { return Err(std::io::Error::last_os_error().into()); }
    if count as usize != bytes.len() { return Err(refused("partial candidate handoff")); }
    Ok(())
}

pub(super) fn receive(socket: &UnixDatagram, timeout: Duration) -> Result<(Vec<u8>, Vec<OwnedFd>), AgentdError> {
    socket.set_nonblocking(false)?;
    socket.set_read_timeout(Some(timeout))?;
    let mut bytes = vec![0_u8; BOUND + 1];
    let mut control = [0_usize; 32];
    let mut vector = libc::iovec { iov_base: bytes.as_mut_ptr().cast(), iov_len: bytes.len() };
    // SAFETY: initialized below with bounded live data and aligned ancillary buffers.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    // SAFETY: recvmsg is bounded and atomically gives every received FD CLOEXEC.
    let length = unsafe { libc::recvmsg(socket.as_raw_fd(), &mut message, libc::MSG_CMSG_CLOEXEC) };
    if length < 0 { return Err(std::io::Error::last_os_error().into()); }
    // SAFETY: original ancillary parser; completed recvmsg buffers remain live.
    let (rights, valid) = unsafe { crate::notes_bootstrap::received_descriptors(&message) };
    if !valid || message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) != 0
        || rights.len() != RIGHTS || length == 0 || length as usize > BOUND
    {
        return Err(refused("exact twenty role rights and original Root pin required"));
    }
    let mut sockets = std::collections::BTreeSet::new();
    for stream in rights.iter().skip(1).step_by(2) {
        crate::notes_bootstrap::require_socket(stream.as_raw_fd(), libc::SOCK_STREAM)?;
        if !sockets.insert(socket_identity(stream.as_raw_fd())?) {
            return Err(refused("role stream aliases another purpose"));
        }
    }
    bytes.truncate(length as usize);
    Ok((bytes, rights))
}

pub(super) fn socket_identity(fd: RawFd) -> Result<(libc::dev_t, libc::ino_t), AgentdError> {
    // SAFETY: fstat writes one correctly sized initialized stat for a borrowed FD.
    let mut stat: libc::stat = unsafe { mem::zeroed() };
    if unsafe { libc::fstat(fd, &mut stat) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok((stat.st_dev, stat.st_ino))
}

pub(super) fn monotonic_ns() -> Result<u64, AgentdError> {
    let mut clock = libc::timespec { tv_sec: 0, tv_nsec: 0 };
    // SAFETY: clock_gettime writes exactly this initialized timespec.
    if unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut clock) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    u64::try_from(clock.tv_sec).ok().and_then(|s| s.checked_mul(1_000_000_000))
        .and_then(|s| u64::try_from(clock.tv_nsec).ok().and_then(|ns| s.checked_add(ns)))
        .ok_or_else(|| refused("original monotonic clock unavailable"))
}
