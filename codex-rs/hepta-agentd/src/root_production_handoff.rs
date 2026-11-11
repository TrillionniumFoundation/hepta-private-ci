//! One original Root-to-child descriptor handoff after actual PID registration.
//! The anonymous pair is created by trusted Root before child launch. Runtime
//! capture happens only after the child exists and drops to its dedicated UID.

use std::fs::File;
use std::io;
use std::io::Read;
use std::mem;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::fd::RawFd;
use std::os::unix::net::UnixDatagram;
use std::path::Path;
use std::time::Duration;

use crate::AgentdError;
use crate::HOST_AUTHORITY_BOOTSTRAP_BOUND;

const FRAME: &[u8] = b"HEPTA_ROOT_PRODUCTION_INPUTS_V1";

#[path = "root_production_writer_handoff.rs"]
mod writer;
pub use writer::RootProductionWriterDescriptor;
pub use writer::receive_root_production_writer_handoff;
pub use writer::send_root_production_writer_handoff;

/// Consume exactly one inherited unnamed pair. The retained creator must be
/// actual UID0, and the second transferred descriptor must pin that same Root.
/// All received rights close on malformed/truncated frames. This function does
/// not parse ordinary JSON or initialize any original authority object.
pub fn receive_root_production_handoff(
    socket: UnixDatagram,
    timeout: Duration,
) -> Result<(File, OwnedFd), AgentdError> {
    let peer = root_pair(&socket, timeout)?;
    let (bootstrap, root) = receive_packet(&socket, timeout)?;
    validate_bootstrap(&bootstrap)?;
    require_root_pin(&root, peer.pid as u32)?;
    Ok((bootstrap, root))
}

/// Send the fully captured original sealed descriptor and the launcher's own
/// previously retained pidfd. Sending consumes the private handoff socket, so
/// there is no resend path or second bootstrap message through this API.
pub fn send_root_production_handoff(
    socket: UnixDatagram,
    bootstrap: &File,
    root_pidfd: &OwnedFd,
    timeout: Duration,
) -> Result<(), AgentdError> {
    // SAFETY: geteuid reads this process's actual kernel credential.
    if unsafe { libc::geteuid() } != 0 {
        return Err(refused("sender requires actual Root"));
    }
    let peer = root_pair(&socket, timeout)?;
    if peer.pid as u32 != std::process::id() {
        return Err(refused(
            "handoff pair must have been created by this same retained Root",
        ));
    }
    validate_bootstrap(bootstrap)?;
    require_root_pin(root_pidfd, std::process::id())?;
    send_packet(
        &socket,
        FRAME,
        &[bootstrap.as_raw_fd(), root_pidfd.as_raw_fd()],
        timeout,
    )
}

fn validate_bootstrap(file: &File) -> Result<(), AgentdError> {
    let size = file.metadata()?.len();
    if size == 0 || size > HOST_AUTHORITY_BOOTSTRAP_BOUND as u64 {
        return Err(refused("original sealed bootstrap bound differs"));
    }
    crate::authority_host_bootstrap_seal::validate_sealed(file, size)?;
    Ok(())
}

pub(crate) fn root_pair(
    socket: &UnixDatagram,
    timeout: Duration,
) -> Result<libc::ucred, AgentdError> {
    if timeout.is_zero() || timeout > Duration::from_secs(30) {
        return Err(refused("bounded original handoff timeout required"));
    }
    crate::notes_bootstrap::require_socket(socket.as_raw_fd(), libc::SOCK_DGRAM)?;
    if !socket.local_addr()?.is_unnamed() || !socket.peer_addr()?.is_unnamed() {
        return Err(refused("inherited unnamed Root datagram pair required"));
    }
    let mut peer = libc::ucred {
        pid: 0,
        uid: u32::MAX,
        gid: u32::MAX,
    };
    let mut size = mem::size_of_val(&peer) as libc::socklen_t;
    // SAFETY: getsockopt writes one correctly sized initialized ucred and its
    // length. The socket remains exclusively owned by the current handoff.
    if unsafe {
        libc::getsockopt(
            socket.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            (&mut peer as *mut libc::ucred).cast(),
            &mut size,
        )
    } != 0
    {
        return Err(io::Error::last_os_error().into());
    }
    if size as usize != mem::size_of::<libc::ucred>() || peer.uid != 0 || peer.pid <= 0 {
        return Err(refused(
            "private handoff creator is not an actual Root process",
        ));
    }
    Ok(peer)
}

fn require_root_pin(root: &OwnedFd, pid: u32) -> Result<(), AgentdError> {
    let number = root.as_raw_fd();
    if std::fs::read_link(format!("/proc/self/fd/{number}"))? != Path::new("anon_inode:[pidfd]") {
        return Err(refused("original Root pidfd required"));
    }
    let mut info = String::new();
    File::open(format!("/proc/self/fdinfo/{number}"))?
        .take(4097)
        .read_to_string(&mut info)?;
    if info.len() > 4096
        || info
            .lines()
            .find_map(|line| line.strip_prefix("Pid:")?.trim().parse::<u32>().ok())
            != Some(pid)
    {
        return Err(refused(
            "descriptor does not pin the inherited pair's Root creator",
        ));
    }
    crate::root_observation_stream::check_lifetime(root)
        .map_err(|error| AgentdError::Protocol(format!("original Root handoff lifetime: {error}")))
}

fn receive_packet(
    socket: &UnixDatagram,
    timeout: Duration,
) -> Result<(File, OwnedFd), AgentdError> {
    socket.set_nonblocking(false)?;
    socket.set_read_timeout(Some(timeout))?;
    let mut bytes = [0_u8; FRAME.len() + 1];
    let mut control = [0_usize; 32];
    let mut vector = libc::iovec {
        iov_base: bytes.as_mut_ptr().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: the message points only to the bounded live buffers below.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    // SAFETY: recvmsg writes only initialized bounded buffers and atomically
    // gives received rights CLOEXEC; no buffer address escapes this call.
    let length = unsafe { libc::recvmsg(socket.as_raw_fd(), &mut message, libc::MSG_CMSG_CLOEXEC) };
    if length < 0 {
        return Err(io::Error::last_os_error().into());
    }
    // SAFETY: this is the same original ancillary parser as the Session Notes
    // handoff, with the completed recvmsg's aligned buffer still alive here.
    let (mut descriptors, valid) =
        unsafe { crate::notes_bootstrap::received_descriptors(&message) };
    if !valid
        || message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) != 0
        || descriptors.len() != 2
        || length as usize != FRAME.len()
        || &bytes[..FRAME.len()] != FRAME
    {
        return Err(refused(
            "exact original handoff marker and two ordered rights required",
        ));
    }
    let root = descriptors
        .pop()
        .ok_or_else(|| refused("Root pidfd missing"))?;
    let bootstrap = descriptors
        .pop()
        .ok_or_else(|| refused("sealed bootstrap missing"))?;
    Ok((File::from(bootstrap), root))
}

fn send_packet(
    socket: &UnixDatagram,
    bytes: &[u8],
    descriptors: &[RawFd],
    timeout: Duration,
) -> Result<(), AgentdError> {
    if descriptors.is_empty() || descriptors.len() > 8 {
        return Err(refused("handoff descriptor bound exceeded"));
    }
    socket.set_nonblocking(false)?;
    socket.set_write_timeout(Some(timeout))?;
    let length = mem::size_of_val(descriptors);
    let mut control = [0_usize; 32];
    // SAFETY: CMSG_SPACE performs scalar size/alignment arithmetic.
    let space = unsafe { libc::CMSG_SPACE(length as u32) } as usize;
    if space > mem::size_of_val(&control) {
        return Err(refused("handoff descriptor bound exceeded"));
    }
    let mut vector = libc::iovec {
        iov_base: bytes.as_ptr().cast_mut().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: the zeroed message is filled with live bounded buffers below.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = space;
    // SAFETY: the header and complete borrowed descriptor array fit within the
    // aligned retained control buffer. sendmsg borrows, never owns these FDs.
    unsafe {
        let header = libc::CMSG_FIRSTHDR(&message);
        (*header).cmsg_level = libc::SOL_SOCKET;
        (*header).cmsg_type = libc::SCM_RIGHTS;
        (*header).cmsg_len = libc::CMSG_LEN(length as u32) as usize;
        std::ptr::copy_nonoverlapping(
            descriptors.as_ptr(),
            libc::CMSG_DATA(header).cast(),
            descriptors.len(),
        );
    }
    // SAFETY: all pointers describe the exact live borrowed buffers above.
    let count = unsafe { libc::sendmsg(socket.as_raw_fd(), &message, libc::MSG_NOSIGNAL) };
    if count < 0 {
        return Err(io::Error::last_os_error().into());
    }
    if count as usize != bytes.len() {
        return Err(refused("partial original Root handoff send"));
    }
    Ok(())
}

fn refused(message: &str) -> AgentdError {
    AgentdError::Protocol(format!("original Root production handoff: {message}"))
}

#[cfg(test)]
#[path = "root_production_handoff_tests.rs"]
mod tests;
