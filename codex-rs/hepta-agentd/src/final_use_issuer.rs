//! Bounded transport to an independently operated final-use issuer.
//!
//! The trusted host supplies an already connected private descriptor and its
//! independently established peer identity. This adapter owns no signer,
//! clock, revocation authority, frontier, or durable operation state.

use std::fmt;
use std::io;
use std::io::Read;
use std::io::Write;
use std::net::Shutdown;
use std::os::fd::AsRawFd;
use std::os::unix::net::UnixStream;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Deserialize;
use serde::Serialize;

const SCHEMA_VERSION: u32 = 1;
const OPERATION: &str = "runtime.agentd.production_operation";
const MAX_REQUEST_BYTES: usize = 16 * 1024;
const MAX_RESPONSE_BYTES: usize = 64 * 1024;
const MAX_TIMEOUT: Duration = Duration::from_secs(30);

#[path = "root_issuer_client.rs"]
mod root_client;

struct ProtectedRootIssuer {
    channel: HostAuthorityPeerChannel,
    end: Instant,
}

/// Independently pinned identity of the connected issuer, not request data.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AgentdFinalUseIssuerPeer {
    pub uid: u32,
    pub pid: u32,
}

/// Transport diagnostics contain no request, signature, or issuer prose.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AgentdFinalUseIssuerError {
    InvalidConfiguration,
    PeerDenied,
    Busy,
    ChannelClosed,
    Unavailable,
    DeadlineElapsed,
    MalformedResponse,
    InvalidGrant,
    BindingMismatch,
    Denied,
}

impl fmt::Display for AgentdFinalUseIssuerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for AgentdFinalUseIssuerError {}

/// Original grants over the authority port's u32-BE length-framed JSON.
///
/// The embedding host must establish the connection with its own bounded
/// bootstrap and transfer exclusive descriptor ownership. This API never
/// discovers, connects, reconnects, or retries. One request may be in flight.
/// Any uncertain exchange permanently closes this channel; a complete denial
/// leaves it usable. Returned grants still require the original FinalUse
/// verifier and its independently configured trust inputs before any effect.
pub struct AgentdUnixFinalUseGrantProvider {
    stream: Mutex<Option<UnixStream>>,
    timeout: Duration,
    protected_root: Option<ProtectedRootIssuer>,
}

impl AgentdUnixFinalUseGrantProvider {
    pub fn from_stream(
        stream: UnixStream,
        peer: AgentdFinalUseIssuerPeer,
        timeout: Duration,
    ) -> Result<Self, AgentdFinalUseIssuerError> {
        if peer.pid == 0 || peer.pid > i32::MAX as u32 || timeout.is_zero() || timeout > MAX_TIMEOUT
        {
            return Err(AgentdFinalUseIssuerError::InvalidConfiguration);
        }
        validate_peer(&stream, peer)?;
        stream.set_nonblocking(false).map_err(io_error)?;
        Ok(Self {
            stream: Mutex::new(Some(stream)),
            timeout,
            protected_root: None,
        })
    }

    pub fn request_grant(
        &self,
        binding: &FinalUseBinding,
    ) -> Result<SignedFinalUseGrant, AgentdFinalUseIssuerError> {
        // Bound allocation before serialization even for a non-owner caller.
        if binding.subject_id.len() > 128 || binding.destination_id.len() > 128 {
            return Err(AgentdFinalUseIssuerError::InvalidGrant);
        }
        let request = serde_json::to_vec(&IssuerRequest {
            schema_version: SCHEMA_VERSION,
            operation: OPERATION,
            binding,
        })
        .map_err(|_| AgentdFinalUseIssuerError::InvalidGrant)?;
        if request.is_empty() || request.len() > MAX_REQUEST_BYTES {
            return Err(AgentdFinalUseIssuerError::InvalidGrant);
        }
        self.exchange_guarded(|stream, deadline| exchange(stream, &request, binding, deadline))?
            .ok_or(AgentdFinalUseIssuerError::Denied)
    }

    fn exchange_guarded<T>(
        &self,
        exchange: impl FnOnce(&mut UnixStream, Instant) -> Result<T, AgentdFinalUseIssuerError>,
    ) -> Result<T, AgentdFinalUseIssuerError> {
        let mut slot = self.stream.try_lock().map_err(|error| match error {
            std::sync::TryLockError::WouldBlock => AgentdFinalUseIssuerError::Busy,
            std::sync::TryLockError::Poisoned(_) => AgentdFinalUseIssuerError::ChannelClosed,
        })?;
        let mut stream = slot
            .take()
            .ok_or(AgentdFinalUseIssuerError::ChannelClosed)?;
        let deadline = (Instant::now() + self.timeout).min(
            self.protected_root
                .as_ref()
                .map_or_else(|| Instant::now() + self.timeout, |root| root.end),
        );
        let result = (|| {
            self.check_root()?;
            remaining(deadline)?;
            let response = exchange(&mut stream, deadline)?;
            self.check_root()?;
            remaining(deadline)?;
            Ok(response)
        })();
        match result {
            Ok(response) => {
                *slot = Some(stream);
                Ok(response)
            }
            Err(error) => {
                let _ = stream.shutdown(Shutdown::Both);
                Err(error)
            }
        }
    }

    fn check_root(&self) -> Result<(), AgentdFinalUseIssuerError> {
        if let Some(root) = &self.protected_root {
            root.channel
                .check_peer_lifetime()
                .map_err(|_| AgentdFinalUseIssuerError::PeerDenied)?;
        }
        Ok(())
    }
}

#[derive(Serialize)]
struct IssuerRequest<'a> {
    schema_version: u32,
    operation: &'static str,
    binding: &'a FinalUseBinding,
}

/// Preserve the existing authority-port response shape. The issuer's unsigned
/// head is only parsed; it never updates the original FinalUse authority.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct IssuerResponse {
    schema_version: u32,
    #[serde(rename = "revocations")]
    _untrusted_revocations: FinalUseRevocations,
    grant: Option<SignedFinalUseGrant>,
    denial_reason: Option<String>,
}

fn exchange(
    stream: &mut UnixStream,
    request: &[u8],
    binding: &FinalUseBinding,
    deadline: Instant,
) -> Result<Option<SignedFinalUseGrant>, AgentdFinalUseIssuerError> {
    let bytes = exchange_frame(stream, request, deadline)?;
    let response: IssuerResponse =
        serde_json::from_slice(&bytes).map_err(|_| AgentdFinalUseIssuerError::MalformedResponse)?;
    remaining(deadline)?;
    if response.schema_version != SCHEMA_VERSION {
        return Err(AgentdFinalUseIssuerError::MalformedResponse);
    }
    match (response.grant, response.denial_reason) {
        (Some(grant), None) => {
            if grant.grant.binding != *binding {
                return Err(AgentdFinalUseIssuerError::BindingMismatch);
            }
            if grant.signature.len() != 64 || grant.grant.signing_bytes().is_err() {
                return Err(AgentdFinalUseIssuerError::InvalidGrant);
            }
            Ok(Some(grant))
        }
        (None, Some(reason)) if !reason.is_empty() && reason.len() <= 1024 => Ok(None),
        _ => Err(AgentdFinalUseIssuerError::MalformedResponse),
    }
}

fn exchange_frame(
    stream: &mut UnixStream,
    request: &[u8],
    deadline: Instant,
) -> Result<Vec<u8>, AgentdFinalUseIssuerError> {
    write_until(stream, &(request.len() as u32).to_be_bytes(), deadline)?;
    write_until(stream, request, deadline)?;
    let mut length = [0; 4];
    read_until(stream, &mut length, deadline)?;
    let length = u32::from_be_bytes(length) as usize;
    if length == 0 || length > MAX_RESPONSE_BYTES {
        return Err(AgentdFinalUseIssuerError::MalformedResponse);
    }
    let mut bytes = vec![0; length];
    read_until(stream, &mut bytes, deadline)?;
    remaining(deadline)?;
    Ok(bytes)
}

fn remaining(deadline: Instant) -> Result<Duration, AgentdFinalUseIssuerError> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|duration| !duration.is_zero())
        .ok_or(AgentdFinalUseIssuerError::DeadlineElapsed)
}

fn write_until(
    stream: &mut UnixStream,
    mut bytes: &[u8],
    deadline: Instant,
) -> Result<(), AgentdFinalUseIssuerError> {
    while !bytes.is_empty() {
        stream
            .set_write_timeout(Some(remaining(deadline)?))
            .map_err(io_error)?;
        match stream.write(bytes) {
            Ok(0) => return Err(AgentdFinalUseIssuerError::Unavailable),
            Ok(count) => bytes = &bytes[count..],
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(io_error(error)),
        }
    }
    Ok(())
}

fn read_until(
    stream: &mut UnixStream,
    mut bytes: &mut [u8],
    deadline: Instant,
) -> Result<(), AgentdFinalUseIssuerError> {
    while !bytes.is_empty() {
        stream
            .set_read_timeout(Some(remaining(deadline)?))
            .map_err(io_error)?;
        match stream.read(bytes) {
            Ok(0) => return Err(AgentdFinalUseIssuerError::Unavailable),
            Ok(count) => bytes = &mut bytes[count..],
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(io_error(error)),
        }
    }
    Ok(())
}

fn io_error(error: io::Error) -> AgentdFinalUseIssuerError {
    match error.kind() {
        io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock => {
            AgentdFinalUseIssuerError::DeadlineElapsed
        }
        _ => AgentdFinalUseIssuerError::Unavailable,
    }
}

fn validate_peer(
    stream: &UnixStream,
    expected: AgentdFinalUseIssuerPeer,
) -> Result<(), AgentdFinalUseIssuerError> {
    let mut actual = libc::ucred {
        pid: 0,
        uid: 0,
        gid: 0,
    };
    let mut length = size_of::<libc::ucred>() as libc::socklen_t;
    // SAFETY: the live socket, initialized output object, and exact buffer size
    // remain valid for this non-retaining getsockopt call.
    let result = unsafe {
        libc::getsockopt(
            stream.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            (&mut actual as *mut libc::ucred).cast(),
            &mut length,
        )
    };
    if result != 0
        || length as usize != size_of::<libc::ucred>()
        || actual.uid != expected.uid
        || actual.pid != expected.pid as i32
    {
        return Err(AgentdFinalUseIssuerError::PeerDenied);
    }
    Ok(())
}

#[cfg(test)]
#[path = "final_use_issuer_tests.rs"]
mod tests;
