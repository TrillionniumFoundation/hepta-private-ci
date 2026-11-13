//! One late V3 Root packet, separate from both original V1 handoffs.

use super::*;
use std::time::Instant;

const FRAME_V3: &[u8] = b"HEPTA_ROOT_RESIDENT_ENROLLMENT_V3";

pub(crate) fn send_original_resident_enrollment(
    socket: UnixDatagram,
    bootstrap: &File,
    root_pidfd: &OwnedFd,
    timeout: Duration,
) -> Result<(), AgentdError> {
    // SAFETY: both calls only inspect the current kernel credentials.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
        return Err(refused("resident enrollment requires original Root"));
    }
    let peer = root_pair(&socket, timeout)?;
    if peer.pid as u32 != std::process::id() {
        return Err(refused("resident enrollment pair belongs to another Root"));
    }
    validate_bootstrap(bootstrap)?;
    require_root_pin(root_pidfd, std::process::id())?;
    send_packet(&socket, FRAME_V3, &[bootstrap.as_raw_fd(), root_pidfd.as_raw_fd()], timeout)
}

pub(crate) async fn receive_original_resident_enrollment(
    socket: UnixDatagram,
    identity: &crate::AgentdIdentity,
    idle_end: Instant,
) -> Result<crate::AgentdRootResidentLearningClientV3, AgentdError> {
    // Idle waiting is bounded by the already running original Root session.
    // The packet carries its own shorter absolute 30-second handoff deadline.
    let peer = root_pair(&socket, Duration::from_secs(30))?;
    if Instant::now() >= idle_end { return Err(refused("resident enrollment expired")); }
    socket.set_nonblocking(true)?;
    let socket = tokio::net::UnixDatagram::from_std(socket)?;
    tokio::time::timeout_at(tokio::time::Instant::from_std(idle_end), socket.readable())
        .await.map_err(|_| refused("resident enrollment expired"))??;
    let (bootstrap, pidfd) = receive_once(socket.as_raw_fd())?;
    validate_bootstrap(&bootstrap)?;
    require_root_pin(&pidfd, peer.pid as u32)?;
    if Instant::now() >= idle_end { return Err(refused("resident enrollment expired")); }
    crate::authority_host_runtime::connect_original_resident_enrollment(
        bootstrap, pidfd, peer.pid as u32, identity, idle_end,
    ).await.map_err(|error| AgentdError::Protocol(error.to_string()))
}

fn receive_once(socket: std::os::fd::RawFd) -> Result<(File, OwnedFd), AgentdError> {
    let mut bytes = [0_u8; FRAME_V3.len() + 1];
    let mut control = [0_usize; 32];
    let mut vector = libc::iovec { iov_base: bytes.as_mut_ptr().cast(), iov_len: bytes.len() };
    // SAFETY: all pointer fields below name bounded buffers retained here.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector; message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast(); message.msg_controllen = mem::size_of_val(&control);
    // SAFETY: recvmsg writes only these live buffers and owns received rights
    // with CLOEXEC. A stale readiness indication fails, without another recv.
    let length = unsafe { libc::recvmsg(socket, &mut message, libc::MSG_CMSG_CLOEXEC | libc::MSG_DONTWAIT) };
    if length < 0 { return Err(io::Error::last_os_error().into()); }
    // SAFETY: the original parser consumes only this completed bounded buffer.
    let (mut rights, valid) = unsafe { crate::notes_bootstrap::received_descriptors(&message) };
    if !valid || message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) != 0
        || rights.len() != 2 || length as usize != FRAME_V3.len()
        || &bytes[..FRAME_V3.len()] != FRAME_V3
    { return Err(refused("resident enrollment requires exact purpose and two rights")); }
    let pidfd = rights.pop().ok_or_else(|| refused("resident Root pidfd absent"))?;
    let bootstrap = rights.pop().ok_or_else(|| refused("resident sealed input absent"))?;
    Ok((File::from(bootstrap), pidfd))
}

pub(crate) fn require_original_resident_process_pin(pidfd: &OwnedFd, pid: u32) -> Result<(), AgentdError> {
    require_root_pin(pidfd, pid)
}

#[cfg(test)]
#[path = "root_resident_enrollment_handoff_tests.rs"]
mod tests;
