//! Explicit native purpose for the same original Root bootstrap and writer FD.
//! The existing two-FD handoff retains its exact marker/count and rejects this.

use super::*;

const WRITER_FRAME: &[u8] = b"HEPTA_ROOT_PRODUCTION_WRITER_INPUTS_V1";

/// One purpose-checked Root descriptor. No public File/raw-FD constructor,
/// Clone, descriptor accessor or deserializer permits another startup from a
/// copied DTO or an aliased file description.
pub struct RootProductionWriterDescriptor(File);

impl RootProductionWriterDescriptor {
    pub(crate) fn into_file(self) -> File {
        self.0
    }
}

/// Send the original sealed bootstrap, same Root pidfd and actual Root0600
/// registered writer FD on this same Root-created private pair. Consuming the
/// sender's file prevents Root from accidentally retaining the same locked
/// open-file description after the child exits. The receiver's
/// original config constructor still checks exact layout/inode/live authority.
pub fn send_root_production_writer_handoff(
    socket: UnixDatagram,
    bootstrap: &File,
    root_pidfd: &OwnedFd,
    writer: File,
    timeout: Duration,
) -> Result<(), AgentdError> {
    // SAFETY: these functions read actual credentials only.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
        return Err(refused("writer descriptor sender requires actual Root"));
    }
    let peer = root_pair(&socket, timeout)?;
    if peer.pid as u32 != std::process::id() {
        return Err(refused("writer pair creator must be this same Root"));
    }
    validate_bootstrap(bootstrap)?;
    require_root_pin(root_pidfd, std::process::id())?;
    validate_writer(&writer)?;
    send_packet(
        &socket,
        WRITER_FRAME,
        &[
            bootstrap.as_raw_fd(),
            root_pidfd.as_raw_fd(),
            writer.as_raw_fd(),
        ],
        timeout,
    )
}

/// Consume only the native three-FD purpose. Nothing can silently fall back to
/// the descriptor-free/original two-FD path after a lost or malformed handoff.
pub fn receive_root_production_writer_handoff(
    socket: UnixDatagram,
    timeout: Duration,
) -> Result<(File, OwnedFd, RootProductionWriterDescriptor), AgentdError> {
    let peer = root_pair(&socket, timeout)?;
    socket.set_nonblocking(false)?;
    socket.set_read_timeout(Some(timeout))?;
    let mut bytes = [0_u8; WRITER_FRAME.len() + 1];
    let mut control = [0_usize; 32];
    let mut vector = libc::iovec {
        iov_base: bytes.as_mut_ptr().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: initialized below with bounded, live, correctly aligned buffers.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    // SAFETY: recvmsg writes only these bounded live buffers and gives received
    // rights CLOEXEC atomically. The shared original parser owns every right.
    let length = unsafe { libc::recvmsg(socket.as_raw_fd(), &mut message, libc::MSG_CMSG_CLOEXEC) };
    if length < 0 {
        return Err(io::Error::last_os_error().into());
    }
    // SAFETY: this is the original ancillary parser over the completed recvmsg.
    let (mut descriptors, valid) =
        unsafe { crate::notes_bootstrap::received_descriptors(&message) };
    if !valid
        || message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) != 0
        || descriptors.len() != 3
        || length as usize != WRITER_FRAME.len()
        || &bytes[..WRITER_FRAME.len()] != WRITER_FRAME
    {
        return Err(refused(
            "exact native writer marker and three ordered rights required",
        ));
    }
    let writer = File::from(
        descriptors
            .pop()
            .ok_or_else(|| refused("original writer FD missing"))?,
    );
    let root = descriptors
        .pop()
        .ok_or_else(|| refused("same Root pidfd missing"))?;
    let bootstrap = File::from(
        descriptors
            .pop()
            .ok_or_else(|| refused("sealed bootstrap missing"))?,
    );
    validate_bootstrap(&bootstrap)?;
    require_root_pin(&root, peer.pid as u32)?;
    validate_writer(&writer)?;
    Ok((bootstrap, root, RootProductionWriterDescriptor(writer)))
}

fn validate_writer(file: &File) -> Result<(), AgentdError> {
    let metadata = file.metadata()?;
    // SAFETY: F_GETFL reads access flags of this retained live descriptor.
    let flags = unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GETFL) };
    if !metadata.is_file()
        || metadata.uid() != 0
        || metadata.nlink() != 1
        || metadata.mode() & 0o7777 != 0o600
        || flags < 0
        || flags & libc::O_ACCMODE != libc::O_RDWR
    {
        return Err(refused(
            "actual Root0600 read-write regular writer FD required",
        ));
    }
    Ok(())
}
