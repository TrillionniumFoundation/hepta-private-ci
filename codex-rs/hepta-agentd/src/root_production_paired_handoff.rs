//! Separate Root purpose for a fixed paired-training plan. The five-lane V1
//! packet remains unchanged and cannot consume this handoff.

use super::*;

const PAIRED_TRAINING_FRAME: &[u8] = b"HEPTA_ROOT_PAIRED_TRAINING_INPUTS_V1";

/// Owned provenance from one original Root-created anonymous pair. There is
/// no public descriptor constructor, deserializer or replacement-PID lookup.
pub struct RootPairedTrainingHandoffV1 {
    pub(crate) bootstrap: File,
    pub(crate) root_pidfd: OwnedFd,
    pub(crate) root_pid: u32,
}

/// Transfer only an already sealed paired training descriptor and the same Root's
/// retained pidfd. The receiver independently checks its complete scope
/// against the original five-lane handoff before connecting to the service.
pub fn send_root_paired_training_handoff(
    socket: UnixDatagram,
    bootstrap: &File,
    root_pidfd: &OwnedFd,
    timeout: Duration,
) -> Result<(), AgentdError> {
    // SAFETY: both calls only read the current process's kernel credentials.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
        return Err(refused(
            "paired training handoff sender requires actual Root",
        ));
    }
    let peer = root_pair(&socket, timeout)?;
    if peer.pid as u32 != std::process::id() {
        return Err(refused(
            "paired training pair must belong to this same Root",
        ));
    }
    validate_bootstrap(bootstrap)?;
    require_root_pin(root_pidfd, std::process::id())?;
    send_packet(
        &socket,
        PAIRED_TRAINING_FRAME,
        &[bootstrap.as_raw_fd(), root_pidfd.as_raw_fd()],
        timeout,
    )
}

/// Receive one exact paired training-purpose packet. All received rights are owned
/// immediately and close on any framing, custody or lifetime refusal.
pub fn receive_root_paired_training_handoff(
    socket: UnixDatagram,
    timeout: Duration,
) -> Result<RootPairedTrainingHandoffV1, AgentdError> {
    let peer = root_pair(&socket, timeout)?;
    let (bootstrap, root_pidfd) = receive_paired_training_packet(&socket, timeout)?;
    validate_bootstrap(&bootstrap)?;
    require_root_pin(&root_pidfd, peer.pid as u32)?;
    Ok(RootPairedTrainingHandoffV1 {
        bootstrap,
        root_pidfd,
        root_pid: peer.pid as u32,
    })
}

fn receive_paired_training_packet(
    socket: &UnixDatagram,
    timeout: Duration,
) -> Result<(File, OwnedFd), AgentdError> {
    socket.set_nonblocking(false)?;
    socket.set_read_timeout(Some(timeout))?;
    let mut bytes = [0_u8; PAIRED_TRAINING_FRAME.len() + 1];
    let mut control = [0_usize; 32];
    let mut vector = libc::iovec {
        iov_base: bytes.as_mut_ptr().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: initialized below with aligned, bounded buffers retained here.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    // SAFETY: recvmsg writes only the live bounded buffers above and marks
    // every received descriptor CLOEXEC atomically.
    let length = unsafe { libc::recvmsg(socket.as_raw_fd(), &mut message, libc::MSG_CMSG_CLOEXEC) };
    if length < 0 {
        return Err(io::Error::last_os_error().into());
    }
    // SAFETY: the original ancillary parser receives the completed message
    // while its aligned control buffer remains live in this scope.
    let (mut descriptors, valid) =
        unsafe { crate::notes_bootstrap::received_descriptors(&message) };
    if !valid
        || message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) != 0
        || descriptors.len() != 2
        || length as usize != PAIRED_TRAINING_FRAME.len()
        || &bytes[..PAIRED_TRAINING_FRAME.len()] != PAIRED_TRAINING_FRAME
    {
        return Err(refused(
            "exact paired training marker and two ordered rights required",
        ));
    }
    let root = descriptors
        .pop()
        .ok_or_else(|| refused("paired training Root pidfd missing"))?;
    let bootstrap = descriptors
        .pop()
        .ok_or_else(|| refused("paired training descriptor missing"))?;
    Ok((File::from(bootstrap), root))
}

#[cfg(test)]
#[path = "root_production_paired_handoff_tests.rs"]
mod tests;
