//! Trusted one-shot Session descriptor receipt; it does not activate authority.
use std::io;
use std::mem;
use std::os::fd::AsRawFd;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use crate::desktop_channel::AgentdDesktopEffectChannel;
use crate::desktop_channel::AgentdDesktopObservationChannel;
use crate::desktop_channel::PrivateStream;
use crate::desktop_channel::remaining;
use codex_hepta_memory::DesktopBootstrapAck;
use codex_hepta_memory::DesktopBootstrapOffer;
use codex_hepta_memory::DesktopBootstrapStatus;
use codex_hepta_memory::ProductionDesktopTarget;

/// Receives exactly [effect, observation] from the trusted inherited datagram.
/// ACK means descriptor composition only. The returned target still requires
/// explicit original recovered-writer / FinalUse / issuer registration before
/// dispatch. No public request, environment or arbitrary endpoint activates it.
pub fn receive_desktop_session(
    bootstrap: UnixDatagram,
) -> io::Result<(ProductionDesktopTarget, DesktopBootstrapOffer)> {
    receive_desktop_session_with_channel(bootstrap, |effect| Arc::new(effect))
}

pub(crate) fn receive_desktop_session_with_channel(
    bootstrap: UnixDatagram,
    effect_factory: impl FnOnce(
        AgentdDesktopEffectChannel,
    ) -> Arc<dyn codex_hepta_memory::DesktopPrivateChannel>,
) -> io::Result<(ProductionDesktopTarget, DesktopBootstrapOffer)> {
    if !bootstrap.local_addr()?.is_unnamed() || !bootstrap.peer_addr()?.is_unnamed() {
        return Err(io::ErrorKind::PermissionDenied.into());
    }
    let deadline = Instant::now() + Duration::from_secs(2);
    bootstrap.set_read_timeout(Some(remaining(deadline)?))?;
    let mut bytes = [0u8; 1025];
    let mut control = [0usize; 32];
    let mut vector = libc::iovec {
        iov_base: bytes.as_mut_ptr().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: the initialized bounded buffers live through the synchronous recvmsg.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    // The fixed buffer fits both glibc size_t and musl socklen_t.
    message.msg_controllen = mem::size_of_val(&control) as _;
    // SAFETY: only live initialized buffers are passed; CLOEXEC adoption is atomic.
    let got = unsafe { libc::recvmsg(bootstrap.as_raw_fd(), &mut message, libc::MSG_CMSG_CLOEXEC) };
    if got < 0 {
        return Err(io::Error::last_os_error());
    }
    let (mut fds, valid) = crate::notes_bootstrap::received_descriptors(&message);
    if !valid
        || fds.len() != 2
        || got == 0
        || got as usize > 1024
        || message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) != 0
    {
        return Err(io::ErrorKind::InvalidData.into());
    }
    let offer =
        DesktopBootstrapOffer::parse_exact(&bytes[..got as usize]).map_err(io::Error::other)?;
    let observation = fds.pop().ok_or(io::ErrorKind::InvalidData)?;
    let effect = fds.pop().ok_or(io::ErrorKind::InvalidData)?;
    for fd in [&effect, &observation] {
        crate::notes_bootstrap::require_socket(fd.as_raw_fd(), libc::SOCK_STREAM)?;
    }
    let target = ProductionDesktopTarget::new(
        offer.target.clone(),
        effect_factory(AgentdDesktopEffectChannel(PrivateStream::new(
            UnixStream::from(effect),
        )?)),
        Arc::new(AgentdDesktopObservationChannel(PrivateStream::new(
            UnixStream::from(observation),
        )?)),
    )
    .map_err(io::Error::other)?;
    let ack = serde_json::to_vec(&DesktopBootstrapAck {
        schema_version: 1,
        profile: offer.profile.clone(),
        target: offer.target.clone(),
        status: DesktopBootstrapStatus::Attached,
    })
    .map_err(io::Error::other)?;
    bootstrap.set_write_timeout(Some(remaining(deadline)?))?;
    if bootstrap.send(&ack)? != ack.len() {
        return Err(io::ErrorKind::WriteZero.into());
    }
    remaining(deadline)?;
    Ok((target, offer))
}
