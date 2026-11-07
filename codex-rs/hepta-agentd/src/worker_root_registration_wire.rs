//! One bounded ACK/confirmation on the same inherited Root datagram pair.
//! Kernel credentials bind the ACK to the actual registered child, not a PID
//! claimed in payload bytes or the pair's creation-time SO_PEERCRED snapshot.

use super::WorkerProcessIdentityV1;
use super::refused;
use codex_hepta_contracts::Sha256Digest;
use std::io;
use std::mem;
use std::os::fd::AsRawFd;
use std::os::unix::net::UnixDatagram;
use std::time::Duration;
use std::time::Instant;

#[derive(Clone, Copy)]
pub(crate) enum Phase {
    Acknowledged,
    Confirmed,
}

fn frame(phase: Phase, digest: &Sha256Digest) -> Vec<u8> {
    let tag: &[u8] = match phase {
        Phase::Acknowledged => b"HEPTA_WORKER_ACK_V1\0",
        Phase::Confirmed => b"HEPTA_WORKER_CONFIRM_V1\0",
    };
    let mut bytes = tag.to_vec();
    bytes.extend_from_slice(digest.as_str().as_bytes());
    bytes
}

pub(crate) fn deadline(timeout: Duration) -> io::Result<Instant> {
    if timeout.is_zero() || timeout > Duration::from_secs(30) {
        return Err(refused("bounded Worker registration timeout required"));
    }
    Instant::now()
        .checked_add(timeout)
        .ok_or_else(|| refused("Worker registration deadline overflow"))
}

pub(crate) fn remaining(end: Instant) -> io::Result<Duration> {
    end.checked_duration_since(Instant::now())
        .filter(|value| !value.is_zero())
        .ok_or_else(|| io::Error::new(io::ErrorKind::TimedOut, "Worker registration deadline"))
}

pub(crate) fn enable_credentials(socket: &UnixDatagram) -> io::Result<()> {
    let enabled: libc::c_int = 1;
    // SAFETY: setsockopt borrows one correctly sized initialized integer.
    if unsafe {
        libc::setsockopt(
            socket.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PASSCRED,
            (&enabled as *const libc::c_int).cast(),
            mem::size_of_val(&enabled) as libc::socklen_t,
        )
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

pub(crate) fn send(
    socket: &UnixDatagram,
    phase: Phase,
    digest: &Sha256Digest,
    end: Instant,
) -> io::Result<()> {
    let bytes = frame(phase, digest);
    socket.set_write_timeout(Some(remaining(end)?))?;
    if socket.send(&bytes)? != bytes.len() {
        return Err(refused("partial Worker registration confirmation"));
    }
    remaining(end)?;
    Ok(())
}

pub(crate) fn receive(
    socket: &UnixDatagram,
    phase: Phase,
    digest: &Sha256Digest,
    expected_sender: &WorkerProcessIdentityV1,
    end: Instant,
) -> io::Result<()> {
    let expected = frame(phase, digest);
    let mut bytes = [0_u8; 128];
    let mut control = [0_usize; 32];
    let mut vector = libc::iovec {
        iov_base: bytes.as_mut_ptr().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: recvmsg below borrows only these live, bounded, aligned buffers.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    socket.set_read_timeout(Some(remaining(end)?))?;
    // SAFETY: every receive buffer is initialized and retained through parsing.
    let length = unsafe { libc::recvmsg(socket.as_raw_fd(), &mut message, libc::MSG_CMSG_CLOEXEC) };
    if length < 0 {
        return Err(io::Error::last_os_error());
    }
    // Adopt even unexpected rights exactly once so rejection cannot leak FDs.
    // The shared parser marks SCM_CREDENTIALS as invalid for its own two-FD
    // protocol; this separate protocol validates credentials below instead.
    let (unexpected_rights, _) = unsafe { crate::notes_bootstrap::received_descriptors(&message) };
    if message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) != 0
        || !unexpected_rights.is_empty()
        || length as usize != expected.len()
        || bytes[..expected.len()] != expected
    {
        return Err(refused("exact Worker confirmation without rights required"));
    }
    let mut credentials = None;
    // SAFETY: the completed recvmsg supplied the retained aligned control chain.
    let mut header = unsafe { libc::CMSG_FIRSTHDR(&message) };
    while !header.is_null() {
        // SAFETY: every header and payload is checked before its fields are read.
        let value = unsafe { &*header };
        let minimum = unsafe { libc::CMSG_LEN(0) } as usize;
        let offset = (header as usize).checked_sub(message.msg_control as usize);
        if value.cmsg_len < minimum
            || offset
                .and_then(|offset| offset.checked_add(value.cmsg_len))
                .is_none_or(|limit| limit > message.msg_controllen)
            || value.cmsg_level != libc::SOL_SOCKET
            || value.cmsg_type != libc::SCM_CREDENTIALS
            || value.cmsg_len - minimum != mem::size_of::<libc::ucred>()
            || credentials.is_some()
        {
            return Err(refused("one exact kernel sender credential required"));
        }
        // SAFETY: the complete ucred lies inside the checked ancillary payload.
        credentials = Some(unsafe {
            libc::CMSG_DATA(header)
                .cast::<libc::ucred>()
                .read_unaligned()
        });
        // SAFETY: same live bounded chain as above; no descriptor is adopted twice.
        header = unsafe { libc::CMSG_NXTHDR(&message, header) };
    }
    let actual = credentials.ok_or_else(|| refused("kernel sender credentials absent"))?;
    if actual.pid <= 0
        || actual.pid as u32 != expected_sender.pid
        || actual.uid != expected_sender.uid
        || actual.gid != expected_sender.gid
    {
        return Err(refused("confirmation came from a different actual process"));
    }
    remaining(end)?;
    Ok(())
}

#[cfg(test)]
#[path = "worker_root_registration_wire_tests.rs"]
mod tests;
