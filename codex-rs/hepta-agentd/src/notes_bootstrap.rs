//! One-shot, inherited Session-to-owner Notes descriptor handoff on Linux.
//!
//! The private datagram channel is created by trusted parent bootstrap. It is
//! not a listener, authority issuer, or an ordinary Agentd control request.

use std::io;
use std::mem;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::fd::RawFd;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_memory::NotesPrivateChannel;
use codex_hepta_memory::NotesTargetIdentity;
use codex_hepta_memory::ProductionNotesTarget;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdFinalUseGrantProvider;
use crate::AgentdNotesChannel;
use crate::AgentdProductionOperationRuntimeConfig;
use crate::AgentdProductionWriterHost;

const MAX_BOOTSTRAP_BYTES: usize = 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct NotesOffer {
    schema_version: u16,
    action: OfferAction,
    target: NotesTargetIdentity,
    destination_id: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum OfferAction {
    OfferNotesTarget,
}

#[derive(Serialize)]
struct Registration<'a> {
    schema_version: u16,
    action: &'static str,
    target: &'a NotesTargetIdentity,
    destination_id: &'a str,
    status: RegistrationStatus,
}

#[derive(Serialize)]
#[serde(rename_all = "snake_case")]
enum RegistrationStatus {
    Attached,
    Rejected,
}

enum Attachment {
    Primary(Arc<dyn AgentdFinalUseGrantProvider>),
    Additional,
}

impl AgentdProductionWriterHost {
    /// Accept exactly one initial Notes application from the explicitly
    /// inherited Session channel. The returned identity is the destination to
    /// bind in the original operation intent. An `attached` ACK confirms only
    /// recovered-owner target composition, never a grant, effect or receipt.
    /// No runtime target can be replaced through this one-shot channel.
    pub async fn attach_notes_from_session(
        self,
        bootstrap: UnixDatagram,
        final_use: FinalUseAuthority,
        grants: Arc<dyn AgentdFinalUseGrantProvider>,
    ) -> Result<(Self, NotesTargetIdentity), AgentdError> {
        self.attach_session_notes(bootstrap, final_use, Attachment::Primary(grants))
            .await
    }

    /// Add Notes to an already-composed host and preserve its existing grant
    /// provider. An absent primary provider is an error before handoff entry.
    pub async fn attach_additional_notes_from_session(
        self,
        bootstrap: UnixDatagram,
        final_use: FinalUseAuthority,
    ) -> Result<(Self, NotesTargetIdentity), AgentdError> {
        if !self.has_target() {
            return Err(AgentdError::Invalid(
                "Notes bootstrap requires the original grant provider".to_string(),
            ));
        }
        self.attach_session_notes(bootstrap, final_use, Attachment::Additional)
            .await
    }

    async fn attach_session_notes(
        self,
        bootstrap: UnixDatagram,
        final_use: FinalUseAuthority,
        attachment: Attachment,
    ) -> Result<(Self, NotesTargetIdentity), AgentdError> {
        let deadline = Instant::now() + Duration::from_secs(2);
        let (offer, endpoint, recovery) = receive_session(&bootstrap, deadline)?;
        let identity = offer.target.clone();
        let attached = tokio::time::timeout(remaining(deadline)?, async {
            match attachment {
                Attachment::Primary(grants) => {
                    self.attach_notes_recoverable_target(
                        identity.clone(),
                        endpoint,
                        recovery,
                        final_use,
                        grants,
                    )
                    .await
                }
                Attachment::Additional => {
                    self.attach_additional_notes_recoverable_target(
                        identity.clone(),
                        endpoint,
                        recovery,
                        final_use,
                    )
                    .await
                }
            }
        })
        .await;
        let host = match attached {
            Ok(Ok(host)) => host,
            Ok(Err(error)) => {
                let _ = acknowledge(&bootstrap, &offer, RegistrationStatus::Rejected, deadline);
                return Err(error);
            }
            Err(_) => {
                return Err(
                    io::Error::new(io::ErrorKind::TimedOut, "Notes bootstrap deadline").into(),
                );
            }
        };
        acknowledge(&bootstrap, &offer, RegistrationStatus::Attached, deadline)?;
        // Dropping bootstrap closes the sole handoff channel. A second offer
        // has no receive path and cannot replace this fixed target.
        Ok((host, identity))
    }
}

impl AgentdProductionOperationRuntimeConfig {
    /// Accept an initial Notes endpoint into the existing immutable runtime
    /// configuration. The primary target, provider and recovered writer must
    /// already be supplied. ACK means verified explicit composition; runtime
    /// startup repeats the original owner check before installing dispatch.
    pub async fn with_notes_from_session(
        self,
        config: &AgentdConfig,
        recovered_host: &AgentdProductionWriterHost,
        bootstrap: UnixDatagram,
        final_use: FinalUseAuthority,
    ) -> Result<(Self, NotesTargetIdentity), AgentdError> {
        self.with_notes_from_session_channel(
            config,
            recovered_host,
            bootstrap,
            final_use,
            |effect, recovery| {
                let channel = AgentdNotesChannel::from_private_channels(effect, recovery)?;
                Ok(Arc::new(channel) as Arc<dyn NotesPrivateChannel>)
            },
        )
        .await
    }

    /// Test-only fault injection wraps the actual inherited transport after
    /// the same recovered-owner validation. It cannot create an issuer,
    /// replace the writer, or skip the production bootstrap checks.
    #[cfg(test)]
    pub(crate) async fn with_notes_from_session_test_channel<F>(
        self,
        config: &AgentdConfig,
        recovered_host: &AgentdProductionWriterHost,
        bootstrap: UnixDatagram,
        final_use: FinalUseAuthority,
        channel_factory: F,
    ) -> Result<(Self, NotesTargetIdentity), AgentdError>
    where
        F: FnOnce(UnixStream, UnixDatagram) -> Result<Arc<dyn NotesPrivateChannel>, AgentdError>,
    {
        self.with_notes_from_session_channel(
            config,
            recovered_host,
            bootstrap,
            final_use,
            channel_factory,
        )
        .await
    }

    async fn with_notes_from_session_channel<F>(
        self,
        config: &AgentdConfig,
        recovered_host: &AgentdProductionWriterHost,
        bootstrap: UnixDatagram,
        final_use: FinalUseAuthority,
        channel_factory: F,
    ) -> Result<(Self, NotesTargetIdentity), AgentdError>
    where
        F: FnOnce(UnixStream, UnixDatagram) -> Result<Arc<dyn NotesPrivateChannel>, AgentdError>,
    {
        let deadline = Instant::now() + Duration::from_secs(2);
        self.validate_for(config)?;
        if recovered_host.destination_count() != 0 {
            return Err(AgentdError::Invalid("runtime Notes bootstrap requires the unregistered recovered writer; direct hosts use the additional-target API".to_string()));
        }
        tokio::time::timeout(
            remaining(deadline)?,
            self.validate_recovered_host(recovered_host),
        )
        .await
        .map_err(|_| {
            io::Error::new(io::ErrorKind::TimedOut, "Notes owner validation deadline")
        })??;
        let (offer, endpoint, recovery) = receive_session(&bootstrap, deadline)?;
        let identity = offer.target.clone();
        let target =
            ProductionNotesTarget::new(identity.clone(), channel_factory(endpoint, recovery)?)
                .map_err(AgentdError::Invalid)?;
        let configured = match self.with_additional_target(final_use, Arc::new(target)) {
            Ok(configured) => configured,
            Err(error) => {
                let _ = acknowledge(&bootstrap, &offer, RegistrationStatus::Rejected, deadline);
                return Err(error);
            }
        };
        acknowledge(&bootstrap, &offer, RegistrationStatus::Attached, deadline)?;
        Ok((configured, identity))
    }
}

fn receive_session(
    bootstrap: &UnixDatagram,
    deadline: Instant,
) -> Result<(NotesOffer, UnixStream, UnixDatagram), AgentdError> {
    require_socket(bootstrap.as_raw_fd(), libc::SOCK_DGRAM)?;
    if !bootstrap.local_addr()?.is_unnamed() || !bootstrap.peer_addr()?.is_unnamed() {
        return Err(AgentdError::Invalid(
            "Notes bootstrap requires an inherited unnamed datagram pair".to_string(),
        ));
    }
    bootstrap.set_nonblocking(false)?;
    receive_offer(bootstrap, deadline)
}

fn receive_offer(
    bootstrap: &UnixDatagram,
    deadline: Instant,
) -> Result<(NotesOffer, UnixStream, UnixDatagram), AgentdError> {
    bootstrap.set_read_timeout(Some(remaining(deadline)?))?;
    let mut bytes = [0_u8; MAX_BOOTSTRAP_BYTES + 1];
    // Word alignment permits cmsghdr access. Extra capacity lets us own and
    // close unwanted descriptors before rejecting malformed ancillary data.
    let mut control = [0_usize; 32];
    let mut vector = libc::iovec {
        iov_base: bytes.as_mut_ptr().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: the zeroed msghdr has no optional address and receives only the
    // bounded live buffers assigned below. recvmsg retains none of them.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    // SAFETY: descriptor is live, and message points only to initialized,
    // writable bounded buffers. CLOEXEC is atomic for received descriptors.
    let length =
        unsafe { libc::recvmsg(bootstrap.as_raw_fd(), &mut message, libc::MSG_CMSG_CLOEXEC) };
    if length < 0 {
        return Err(io::Error::last_os_error().into());
    }
    let (mut descriptors, ancillary_valid) = received_descriptors(&message);
    if message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) != 0
        || !ancillary_valid
        || descriptors.len() != 2
        || length == 0
        || length as usize > MAX_BOOTSTRAP_BYTES
    {
        return Err(AgentdError::Protocol(
            "invalid Notes bootstrap frame or descriptor count".to_string(),
        ));
    }
    let offer: NotesOffer = serde_json::from_slice(&bytes[..length as usize])
        .map_err(|_| AgentdError::Protocol("invalid Notes bootstrap schema".to_string()))?;
    offer.target.validate().map_err(AgentdError::Invalid)?;
    if offer.schema_version != 2
        || !matches!(offer.action, OfferAction::OfferNotesTarget)
        || offer.target.task_id != 1
        || offer.destination_id != offer.target.destination_id()
    {
        return Err(AgentdError::Protocol(
            "Notes bootstrap differs from its initial application identity".to_string(),
        ));
    }
    let recovery = descriptors
        .pop()
        .ok_or_else(|| AgentdError::Protocol("Notes recovery endpoint is absent".to_string()))?;
    require_socket(recovery.as_raw_fd(), libc::SOCK_DGRAM)?;
    let recovery = UnixDatagram::from(recovery);
    if !recovery.local_addr()?.is_unnamed() || !recovery.peer_addr()?.is_unnamed() {
        return Err(AgentdError::Protocol(
            "Notes recovery must be an inherited unnamed datagram".to_string(),
        ));
    }
    let descriptor = descriptors
        .pop()
        .ok_or_else(|| AgentdError::Protocol("Notes endpoint is absent".to_string()))?;
    require_socket(descriptor.as_raw_fd(), libc::SOCK_STREAM)?;
    let endpoint = UnixStream::from(descriptor);
    if !endpoint.local_addr()?.is_unnamed() || !endpoint.peer_addr()?.is_unnamed() {
        return Err(AgentdError::Protocol(
            "Notes endpoint must be an inherited unnamed stream".to_string(),
        ));
    }
    Ok((offer, endpoint, recovery))
}

fn received_descriptors(message: &libc::msghdr) -> (Vec<OwnedFd>, bool) {
    let mut descriptors = Vec::new();
    let mut valid = true;
    // SAFETY: recvmsg initialized a kernel-bounded ancillary chain in the
    // aligned buffer retained by the caller throughout this traversal.
    let mut header = unsafe { libc::CMSG_FIRSTHDR(message) };
    while !header.is_null() {
        // SAFETY: CMSG iteration provides an in-bounds header, and CMSG_LEN(0)
        // gives its minimum length before payload arithmetic.
        let value = unsafe { &*header };
        let minimum = unsafe { libc::CMSG_LEN(0) } as usize;
        let offset = (header as usize).checked_sub(message.msg_control as usize);
        if value.cmsg_len < minimum
            || offset
                .and_then(|offset| offset.checked_add(value.cmsg_len))
                .is_none_or(|end| end > message.msg_controllen)
        {
            valid = false;
            break;
        }
        let count_bytes = value.cmsg_len - minimum;
        if value.cmsg_level == libc::SOL_SOCKET && value.cmsg_type == libc::SCM_RIGHTS {
            valid &= count_bytes.is_multiple_of(mem::size_of::<RawFd>());
            for index in 0..count_bytes / mem::size_of::<RawFd>() {
                // SAFETY: each complete descriptor lies within the ancillary
                // payload. Kernel-transferred descriptors have unique owned
                // numbers; adopting them immediately closes all on rejection.
                let descriptor = unsafe {
                    libc::CMSG_DATA(header)
                        .cast::<RawFd>()
                        .add(index)
                        .read_unaligned()
                };
                if descriptor < 0 {
                    valid = false;
                } else {
                    descriptors.push(unsafe { OwnedFd::from_raw_fd(descriptor) });
                }
            }
        } else {
            valid = false;
        }
        // SAFETY: same retained, bounded ancillary chain as above.
        header = unsafe { libc::CMSG_NXTHDR(message, header) };
    }
    (descriptors, valid)
}

fn require_socket(descriptor: RawFd, kind: libc::c_int) -> io::Result<()> {
    for (option, expected) in [(libc::SO_DOMAIN, libc::AF_UNIX), (libc::SO_TYPE, kind)] {
        let mut actual: libc::c_int = 0;
        let mut length = mem::size_of_val(&actual) as libc::socklen_t;
        // SAFETY: actual and its length are initialized writable values of the
        // exact size expected by these integer socket options.
        let result = unsafe {
            libc::getsockopt(
                descriptor,
                libc::SOL_SOCKET,
                option,
                (&mut actual as *mut libc::c_int).cast(),
                &mut length,
            )
        };
        if result != 0 {
            return Err(io::Error::last_os_error());
        }
        if length as usize != mem::size_of_val(&actual) || actual != expected {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "Notes descriptor socket type mismatch",
            ));
        }
    }
    Ok(())
}

fn acknowledge(
    bootstrap: &UnixDatagram,
    offer: &NotesOffer,
    status: RegistrationStatus,
    deadline: Instant,
) -> Result<(), AgentdError> {
    let response = serde_json::to_vec(&Registration {
        schema_version: 2,
        action: "notes_target_registration",
        target: &offer.target,
        destination_id: &offer.destination_id,
        status,
    })
    .map_err(|error| AgentdError::Protocol(error.to_string()))?;
    bootstrap.set_write_timeout(Some(remaining(deadline)?))?;
    if bootstrap.send(&response)? != response.len() {
        return Err(AgentdError::Protocol(
            "partial Notes bootstrap acknowledgement".to_string(),
        ));
    }
    Ok(())
}

fn remaining(deadline: Instant) -> io::Result<Duration> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|left| !left.is_zero())
        .ok_or_else(|| io::Error::new(io::ErrorKind::TimedOut, "Notes bootstrap deadline"))
}

#[cfg(test)]
#[path = "notes_bootstrap_tests.rs"]
mod tests;
