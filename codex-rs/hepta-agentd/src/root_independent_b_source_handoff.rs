//! Independent source custody never shares the learner's B datagram. Closed
//! routes carry two rights and cannot recreate an original source writer.

use super::*;

const FRAME: &[u8] = b"HEPTA_ROOT_INDEPENDENT_B_SOURCE_V1";

pub struct RootIndependentBSourceHandoffV1 {
    pub(crate) bootstrap: File,
    pub(crate) source: Option<File>,
    pub(crate) root_pidfd: OwnedFd,
    pub(crate) root_pid: u32,
}

pub fn send_root_independent_b_source_handoff(
    socket: UnixDatagram,
    offer: crate::RootIndependentBSourceOfferV1,
    root_pidfd: &OwnedFd,
    timeout: Duration,
) -> Result<(), AgentdError> {
    // SAFETY: these calls only observe the actual kernel credentials.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
        return Err(refused("B source sender requires actual Root"));
    }
    let peer = root_pair(&socket, timeout)?;
    if peer.pid as u32 != std::process::id() {
        return Err(refused("B source pair belongs to another Root"));
    }
    validate_bootstrap(&offer.bootstrap)?;
    require_root_pin(root_pidfd, std::process::id())?;
    let mut rights = vec![offer.bootstrap.as_raw_fd(), root_pidfd.as_raw_fd()];
    if let Some(source) = &offer.source {
        rights.push(source.as_raw_fd());
    }
    send_packet(&socket, FRAME, &rights, timeout)
}

pub fn receive_root_independent_b_source_handoff(
    socket: UnixDatagram,
    timeout: Duration,
) -> Result<RootIndependentBSourceHandoffV1, AgentdError> {
    let peer = root_pair(&socket, timeout)?;
    socket.set_nonblocking(false)?;
    socket.set_read_timeout(Some(timeout))?;
    let mut bytes = [0_u8; FRAME.len() + 1];
    let mut control = [0_usize; 32];
    let mut vector = libc::iovec {
        iov_base: bytes.as_mut_ptr().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: all buffers are aligned, initialized and retained through recvmsg.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    // SAFETY: bounded live buffers; received descriptors gain CLOEXEC atomically.
    let size = unsafe { libc::recvmsg(socket.as_raw_fd(), &mut message, libc::MSG_CMSG_CLOEXEC) };
    if size < 0 {
        return Err(io::Error::last_os_error().into());
    }
    // SAFETY: the parser takes ownership of every actual received right.
    let (mut rights, valid) = unsafe { crate::notes_bootstrap::received_descriptors(&message) };
    if !valid
        || message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) != 0
        || !matches!(rights.len(), 2 | 3)
        || size as usize != FRAME.len()
        || &bytes[..FRAME.len()] != FRAME
    {
        return Err(refused("exact original B source purpose rights required"));
    }
    let source = if rights.len() == 3 {
        Some(File::from(
            rights
                .pop()
                .ok_or_else(|| refused("B source right absent"))?,
        ))
    } else {
        None
    };
    let root_pidfd = rights
        .pop()
        .ok_or_else(|| refused("B source Root pin absent"))?;
    let bootstrap = File::from(
        rights
            .pop()
            .ok_or_else(|| refused("B source route absent"))?,
    );
    validate_bootstrap(&bootstrap)?;
    require_root_pin(&root_pidfd, peer.pid as u32)?;
    Ok(RootIndependentBSourceHandoffV1 {
        bootstrap,
        source,
        root_pidfd,
        root_pid: peer.pid as u32,
    })
}
