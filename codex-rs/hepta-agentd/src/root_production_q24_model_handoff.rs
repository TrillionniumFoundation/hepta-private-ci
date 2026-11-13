//! Separate Model factory purpose with the actual reserved owner rights.

use super::*;
use crate::RootQ24ModelFactoryOfferV1;

const MODEL_FRAME: &[u8] = b"HEPTA_ROOT_Q24_MODEL_FACTORY_V1";

/// Actual Root-created pair provenance. There is no descriptor-only constructor
/// and no API that extracts the received writable owner files.
pub struct RootQ24ModelFactoryHandoffV1 {
    pub(crate) bootstrap: File,
    pub(crate) root_pidfd: OwnedFd,
    pub(crate) root_pid: u32,
    pub(crate) journal: File,
    pub(crate) witness: File,
}

/// Consume the original Root's one-shot reservation offer. No file is opened,
/// initialized or discovered from a pathname during this transfer.
pub fn send_root_q24_model_factory_handoff(
    socket: UnixDatagram,
    offer: RootQ24ModelFactoryOfferV1,
    root_pidfd: &OwnedFd,
    timeout: Duration,
) -> Result<(), AgentdError> {
    // SAFETY: credential queries only observe this process's kernel identity.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
        return Err(refused("Model factory handoff requires actual Root"));
    }
    if root_pair(&socket, timeout)?.pid as u32 != std::process::id() {
        return Err(refused("Model factory pair belongs to another Root"));
    }
    validate_bootstrap(&offer.bootstrap)?;
    require_root_pin(root_pidfd, std::process::id())?;
    send_packet(
        &socket,
        MODEL_FRAME,
        &[
            offer.bootstrap.as_raw_fd(),
            root_pidfd.as_raw_fd(),
            offer.journal.as_raw_fd(),
            offer.witness.as_raw_fd(),
        ],
        timeout,
    )
}

/// Receive exactly the factory descriptor, original Root pidfd, proposal file
/// and durable witness file. All rights close on framing or custody refusal.
pub fn receive_root_q24_model_factory_handoff(
    socket: UnixDatagram,
    timeout: Duration,
) -> Result<RootQ24ModelFactoryHandoffV1, AgentdError> {
    let peer = root_pair(&socket, timeout)?;
    socket.set_nonblocking(false)?;
    socket.set_read_timeout(Some(timeout))?;
    let mut bytes = [0_u8; MODEL_FRAME.len() + 1];
    let mut control = [0_usize; 32];
    let mut vector = libc::iovec {
        iov_base: bytes.as_mut_ptr().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: initialized with live aligned bounded buffers immediately below.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    // SAFETY: recvmsg writes only these retained buffers; every right is CLOEXEC.
    let length = unsafe { libc::recvmsg(socket.as_raw_fd(), &mut message, libc::MSG_CMSG_CLOEXEC) };
    if length < 0 {
        return Err(io::Error::last_os_error().into());
    }
    // SAFETY: the completed message and its aligned ancillary storage remain live.
    let (mut rights, valid) = unsafe { crate::notes_bootstrap::received_descriptors(&message) };
    if !valid
        || message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) != 0
        || rights.len() != 4
        || length as usize != MODEL_FRAME.len()
        || &bytes[..MODEL_FRAME.len()] != MODEL_FRAME
    {
        return Err(refused(
            "exact factory purpose and four ordered rights required",
        ));
    }
    let witness = File::from(
        rights
            .pop()
            .ok_or_else(|| refused("factory witness missing"))?,
    );
    let journal = File::from(
        rights
            .pop()
            .ok_or_else(|| refused("factory journal missing"))?,
    );
    let root_pidfd = rights
        .pop()
        .ok_or_else(|| refused("factory Root pidfd missing"))?;
    let bootstrap = File::from(
        rights
            .pop()
            .ok_or_else(|| refused("factory descriptor missing"))?,
    );
    validate_bootstrap(&bootstrap)?;
    require_root_pin(&root_pidfd, peer.pid as u32)?;
    Ok(RootQ24ModelFactoryHandoffV1 {
        bootstrap,
        root_pidfd,
        root_pid: peer.pid as u32,
        journal,
        witness,
    })
}

#[cfg(test)]
#[path = "root_production_q24_model_handoff_tests.rs"]
mod tests;
