//! An independent fixed purpose on an original Root-created anonymous pair.

use super::*;

const HISTORICAL_FRAME: &[u8] = b"HEPTA_ROOT_HISTORICAL_TASK_READ_V1";

pub struct RootHistoricalTaskReadHandoffV1 {
    pub(crate) bootstrap: File,
    pub(crate) root_pidfd: OwnedFd,
    pub(crate) root_pid: u32,
}

/// Transfer the sealed complete-task route and the same original Root pidfd.
pub fn send_root_historical_task_read_handoff(
    socket: UnixDatagram,
    offer: crate::RootHistoricalTaskReadOfferV1,
    root_pidfd: &OwnedFd,
    timeout: Duration,
) -> Result<(), AgentdError> {
    // SAFETY: these calls only observe the current process's kernel credentials.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
        return Err(refused("historical handoff requires actual Root"));
    }
    let peer = root_pair(&socket, timeout)?;
    if peer.pid as u32 != std::process::id() {
        return Err(refused("historical pair belongs to another original Root"));
    }
    validate_bootstrap(&offer.bootstrap)?;
    require_root_pin(root_pidfd, std::process::id())?;
    send_packet(
        &socket,
        HISTORICAL_FRAME,
        &[offer.bootstrap.as_raw_fd(), root_pidfd.as_raw_fd()],
        timeout,
    )
}

/// Consume one exact-purpose packet; every received right closes on refusal.
pub fn receive_root_historical_task_read_handoff(
    socket: UnixDatagram,
    timeout: Duration,
) -> Result<RootHistoricalTaskReadHandoffV1, AgentdError> {
    let peer = root_pair(&socket, timeout)?;
    socket.set_nonblocking(false)?;
    socket.set_read_timeout(Some(timeout))?;
    let mut bytes = [0_u8; HISTORICAL_FRAME.len() + 1];
    let mut control = [0_usize; 32];
    let mut vector = libc::iovec {
        iov_base: bytes.as_mut_ptr().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: initialized below with bounded aligned buffers retained here.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    // SAFETY: the live receive buffers are bounded; all received FDs are CLOEXEC.
    let size = unsafe { libc::recvmsg(socket.as_raw_fd(), &mut message, libc::MSG_CMSG_CLOEXEC) };
    if size < 0 {
        return Err(io::Error::last_os_error().into());
    }
    // SAFETY: the original ancillary parser immediately owns every descriptor.
    let (mut descriptors, valid) =
        unsafe { crate::notes_bootstrap::received_descriptors(&message) };
    if !valid
        || message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) != 0
        || descriptors.len() != 2
        || size as usize != HISTORICAL_FRAME.len()
        || &bytes[..HISTORICAL_FRAME.len()] != HISTORICAL_FRAME
    {
        return Err(refused(
            "exact historical purpose and two original rights required",
        ));
    }
    let root_pidfd = descriptors
        .pop()
        .ok_or_else(|| refused("historical Root pin missing"))?;
    let bootstrap = File::from(
        descriptors
            .pop()
            .ok_or_else(|| refused("historical route missing"))?,
    );
    validate_bootstrap(&bootstrap)?;
    require_root_pin(&root_pidfd, peer.pid as u32)?;
    Ok(RootHistoricalTaskReadHandoffV1 {
        bootstrap,
        root_pidfd,
        root_pid: peer.pid as u32,
    })
}
