//! A separate Root purpose carrying only the original sealed route and pidfd.
//! The actual current owner is obtained later from the live enrolled Root lane.

use super::*;

const PUBLICATION_FRAME: &[u8] = b"HEPTA_ROOT_GENERATION_PUBLICATION_V1";

/// Owned original Root route. Public bytes, files or a replacement PID cannot
/// construct this value, and receiving it does not activate a CURRENT owner.
pub struct RootGenerationPublicationHandoffV1 {
    pub(crate) bootstrap: File,
    pub(crate) root_pidfd: OwnedFd,
    pub(crate) root_pid: u32,
}

impl RootGenerationPublicationHandoffV1 {
    pub(crate) fn require_original_root(&self) -> Result<(), AgentdError> {
        require_root_pin(&self.root_pidfd, self.root_pid)
    }
}

/// Consume one original offer after the dedicated Root listener is ready.
pub fn send_root_generation_publication_handoff(
    socket: UnixDatagram,
    offer: crate::RootGenerationPublicationOfferV1,
    root_pidfd: &OwnedFd,
    timeout: Duration,
) -> Result<(), AgentdError> {
    // SAFETY: these calls only observe the process's actual kernel credentials.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
        return Err(refused("publication sender requires actual Root"));
    }
    let peer = root_pair(&socket, timeout)?;
    if peer.pid as u32 != std::process::id() {
        return Err(refused("publication pair belongs to another original Root"));
    }
    validate_bootstrap(&offer.bootstrap)?;
    require_root_pin(root_pidfd, std::process::id())?;
    send_packet(
        &socket,
        PUBLICATION_FRAME,
        &[offer.bootstrap.as_raw_fd(), root_pidfd.as_raw_fd()],
        timeout,
    )
}

/// Receive exactly one original purpose packet, closing every right on error.
pub fn receive_root_generation_publication_handoff(
    socket: UnixDatagram,
    timeout: Duration,
) -> Result<RootGenerationPublicationHandoffV1, AgentdError> {
    let peer = root_pair(&socket, timeout)?;
    socket.set_nonblocking(false)?;
    socket.set_read_timeout(Some(timeout))?;
    let mut bytes = [0_u8; PUBLICATION_FRAME.len() + 1];
    let mut control = [0_usize; 32];
    let mut vector = libc::iovec {
        iov_base: bytes.as_mut_ptr().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: initialized below with aligned bounded buffers retained here.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    // SAFETY: every receive buffer is live and bounded. CLOEXEC is atomic.
    let size = unsafe { libc::recvmsg(socket.as_raw_fd(), &mut message, libc::MSG_CMSG_CLOEXEC) };
    if size < 0 {
        return Err(io::Error::last_os_error().into());
    }
    // SAFETY: the existing parser owns each returned descriptor immediately.
    let (mut descriptors, valid) =
        unsafe { crate::notes_bootstrap::received_descriptors(&message) };
    if !valid
        || message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) != 0
        || descriptors.len() != 2
        || size as usize != PUBLICATION_FRAME.len()
        || &bytes[..PUBLICATION_FRAME.len()] != PUBLICATION_FRAME
    {
        return Err(refused(
            "exact publication purpose and two original rights required",
        ));
    }
    let root_pidfd = descriptors
        .pop()
        .ok_or_else(|| refused("publication Root pin missing"))?;
    let bootstrap = File::from(
        descriptors
            .pop()
            .ok_or_else(|| refused("publication route missing"))?,
    );
    validate_bootstrap(&bootstrap)?;
    require_root_pin(&root_pidfd, peer.pid as u32)?;
    Ok(RootGenerationPublicationHandoffV1 {
        bootstrap,
        root_pidfd,
        root_pid: peer.pid as u32,
    })
}

#[cfg(test)]
#[path = "root_generation_publication_handoff_tests.rs"]
mod tests;
