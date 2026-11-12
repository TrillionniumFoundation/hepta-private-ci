//! A separate Root purpose carrying the original sealed route, pidfd and the
//! registered candidate DATA input. No result, holdout or signature writer moves.
//! The actual current owner is obtained later from the live enrolled Root lane.

use super::*;

const INDEPENDENT_B_FRAME: &[u8] = b"HEPTA_ROOT_INDEPENDENT_B_EVALUATION_V2";

/// Owned original Root route. Public bytes, files or a replacement PID cannot
/// construct this value, and receiving it does not activate a B read client.
pub struct RootIndependentBEvaluationHandoffV1 {
    pub(crate) bootstrap: File,
    pub(crate) candidate_data: File,
    pub(crate) source_admitted: File,
    pub(crate) root_pidfd: OwnedFd,
    pub(crate) root_pid: u32,
}

/// Consume one original offer after the dedicated Root listener is ready.
pub fn send_root_independent_b_evaluation_handoff(
    socket: UnixDatagram,
    offer: crate::RootIndependentBEvaluationOfferV1,
    root_pidfd: &OwnedFd,
    timeout: Duration,
) -> Result<(), AgentdError> {
    // SAFETY: these calls only observe the process's actual kernel credentials.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
        return Err(refused("independent B sender requires actual Root"));
    }
    let peer = root_pair(&socket, timeout)?;
    if peer.pid as u32 != std::process::id() {
        return Err(refused(
            "independent B pair belongs to another original Root",
        ));
    }
    validate_bootstrap(&offer.bootstrap)?;
    require_root_pin(root_pidfd, std::process::id())?;
    crate::root_independent_b_notice::require_original_notice_reader(
        &offer.source_admitted,
        std::process::id(),
    )?;
    send_packet(
        &socket,
        INDEPENDENT_B_FRAME,
        &[
            offer.bootstrap.as_raw_fd(),
            root_pidfd.as_raw_fd(),
            offer.candidate_data.as_raw_fd(),
            offer.source_admitted.as_raw_fd(),
        ],
        timeout,
    )
}

/// Receive exactly one original purpose packet, closing every right on error.
pub fn receive_root_independent_b_evaluation_handoff(
    socket: UnixDatagram,
    timeout: Duration,
) -> Result<RootIndependentBEvaluationHandoffV1, AgentdError> {
    let peer = root_pair(&socket, timeout)?;
    socket.set_nonblocking(false)?;
    socket.set_read_timeout(Some(timeout))?;
    let mut bytes = [0_u8; INDEPENDENT_B_FRAME.len() + 1];
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
        || descriptors.len() != 4
        || size as usize != INDEPENDENT_B_FRAME.len()
        || &bytes[..INDEPENDENT_B_FRAME.len()] != INDEPENDENT_B_FRAME
    {
        return Err(refused(
            "exact independent B purpose and four original rights required",
        ));
    }
    let source_admitted = File::from(
        descriptors
            .pop()
            .ok_or_else(|| refused("original B source readiness missing"))?,
    );
    crate::root_independent_b_notice::require_original_notice_reader(
        &source_admitted,
        peer.pid as u32,
    )?;
    let candidate_data = File::from(
        descriptors
            .pop()
            .ok_or_else(|| refused("original B candidate data missing"))?,
    );
    let root_pidfd = descriptors
        .pop()
        .ok_or_else(|| refused("independent B Root pin missing"))?;
    let bootstrap = File::from(
        descriptors
            .pop()
            .ok_or_else(|| refused("independent B route missing"))?,
    );
    validate_bootstrap(&bootstrap)?;
    require_root_pin(&root_pidfd, peer.pid as u32)?;
    Ok(RootIndependentBEvaluationHandoffV1 {
        bootstrap,
        candidate_data,
        source_admitted,
        root_pidfd,
        root_pid: peer.pid as u32,
    })
}
