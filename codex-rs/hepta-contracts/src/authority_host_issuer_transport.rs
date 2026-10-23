//! Private, peer-pinned server for the original Agentd final-use wire format.

use crate::FinalUseBinding;
use crate::FinalUseRevocations;
use crate::HostFinalUseIssuer;
use crate::HostIssuerError;
use crate::SignedFinalUseGrant;
use crate::authority_lease::AuthorityLeaseError;
use crate::authority_lease::AuthorityLeaseVerifier;
use serde::Deserialize;
use serde::Serialize;
use std::io;
use std::io::Read;
use std::io::Write;
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

const OPERATION: &str = "runtime.agentd.production_operation";
const MAX_REQUEST: usize = 16 * 1024;
const MAX_RESPONSE: usize = 64 * 1024;
const MAX_TIMEOUT: Duration = Duration::from_secs(30);

/// Identity supplied by the root launcher, verified against SO_PEERCRED.
/// Request fields never select the authorized process or lease.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HostIssuerPeer {
    pub uid: u32,
    pub pid: u32,
}

pub struct HostIssuerSessionPolicy {
    pub peer: HostIssuerPeer,
    pub lease_id: String,
    pub lease_revision: u64,
    /// Existing original FinalUse head for wire compatibility. The original
    /// Agentd provider treats this field as untrusted and does not apply it.
    pub revocations: FinalUseRevocations,
    pub timeout: Duration,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HostIssuerTransportError {
    InvalidConfiguration,
    PeerDenied,
    Closed,
    InvalidRequest,
    DeadlineElapsed,
    Unavailable,
}

impl std::fmt::Display for HostIssuerTransportError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for HostIssuerTransportError {}

/// One inherited/privately connected capability channel, one exchange at a
/// time. The root launcher pins the actual process and selects an existing
/// original lease. The server does no discovery/reconnect or lease creation.
/// An uncertain exchange closes the channel; a complete policy denial does
/// not. The launcher must prevent unauthorized descriptor inheritance/transfer.
pub struct HostIssuerSession {
    stream: Option<UnixStream>,
    policy: HostIssuerSessionPolicy,
    issuer: Arc<HostFinalUseIssuer>,
    leases: AuthorityLeaseVerifier,
}

impl HostIssuerSession {
    pub fn from_stream(
        stream: UnixStream,
        policy: HostIssuerSessionPolicy,
        issuer: Arc<HostFinalUseIssuer>,
        leases: AuthorityLeaseVerifier,
    ) -> Result<Self, HostIssuerTransportError> {
        if policy.peer.pid == 0
            || policy.peer.pid > i32::MAX as u32
            || policy.lease_id.is_empty()
            || policy.lease_id.len() > 128
            || policy.lease_revision == 0
            || policy.timeout.is_zero()
            || policy.timeout > MAX_TIMEOUT
        {
            return Err(HostIssuerTransportError::InvalidConfiguration);
        }
        if policy.revocations.authority_epoch != issuer.trust_key().not_before_authority_epoch
            || policy.revocations.revision == 0
            || serde_json::to_vec(&policy.revocations)
                .map_err(|_| HostIssuerTransportError::InvalidConfiguration)?
                .len()
                > MAX_RESPONSE / 2
        {
            return Err(HostIssuerTransportError::InvalidConfiguration);
        }
        let peer = rustix::net::sockopt::socket_peercred(&stream).map_err(io_error)?;
        if peer.uid.as_raw() != policy.peer.uid
            || peer.pid.as_raw_nonzero().get() as u32 != policy.peer.pid
        {
            return Err(HostIssuerTransportError::PeerDenied);
        }
        stream.set_nonblocking(false).map_err(io_error)?;
        Ok(Self {
            stream: Some(stream),
            policy,
            issuer,
            leases,
        })
    }

    /// Handle one bounded original request. `false` is clean EOF before a new
    /// frame. No partial response or unsigned substitute grant is successful.
    pub fn serve_next(&mut self) -> Result<bool, HostIssuerTransportError> {
        let mut stream = self.stream.take().ok_or(HostIssuerTransportError::Closed)?;
        let deadline = Instant::now() + self.policy.timeout;
        let result = self.exchange(&mut stream, deadline);
        match result {
            Ok(true) => {
                self.stream = Some(stream);
                Ok(true)
            }
            Ok(false) => Ok(false),
            Err(error) => {
                let _ = stream.shutdown(Shutdown::Both);
                Err(error)
            }
        }
    }

    fn exchange(
        &self,
        stream: &mut UnixStream,
        deadline: Instant,
    ) -> Result<bool, HostIssuerTransportError> {
        let mut length = [0; 4];
        loop {
            stream
                .set_read_timeout(Some(remaining(deadline)?))
                .map_err(io_error)?;
            match stream.read(&mut length[..1]) {
                Ok(0) => return Ok(false),
                Ok(_) => break,
                Err(error) if error.kind() == io::ErrorKind::Interrupted => {
                    remaining(deadline)?;
                }
                Err(error) => return Err(io_error(error)),
            }
        }
        read_until(stream, &mut length[1..], deadline)?;
        let length = u32::from_be_bytes(length) as usize;
        if length == 0 || length > MAX_REQUEST {
            return Err(HostIssuerTransportError::InvalidRequest);
        }
        let mut bytes = vec![0; length];
        read_until(stream, &mut bytes, deadline)?;
        let request: Request =
            serde_json::from_slice(&bytes).map_err(|_| HostIssuerTransportError::InvalidRequest)?;
        if request.schema_version != 1 || request.operation != OPERATION {
            return Err(HostIssuerTransportError::InvalidRequest);
        }
        remaining(deadline)?;
        let grant = match self.issuer.issue(
            &self.leases,
            &self.policy.lease_id,
            self.policy.lease_revision,
            &request.binding,
        ) {
            Ok(grant) => Some(grant),
            Err(HostIssuerError::Lease(
                AuthorityLeaseError::LeaseNotFound
                | AuthorityLeaseError::Revoked
                | AuthorityLeaseError::BindingMismatch
                | AuthorityLeaseError::RevisionMismatch
                | AuthorityLeaseError::EpochMismatch
                | AuthorityLeaseError::NotYetValid
                | AuthorityLeaseError::Expired,
            )) => None,
            Err(_) => return Err(HostIssuerTransportError::Unavailable),
        };
        remaining(deadline)?;
        let denied = grant.is_none();
        let bytes = serde_json::to_vec(&Response {
            schema_version: 1,
            revocations: &self.policy.revocations,
            grant,
            denial_reason: denied.then_some("authorization_denied"),
        })
        .map_err(|_| HostIssuerTransportError::Unavailable)?;
        if bytes.is_empty() || bytes.len() > MAX_RESPONSE {
            return Err(HostIssuerTransportError::Unavailable);
        }
        write_until(stream, &(bytes.len() as u32).to_be_bytes(), deadline)?;
        write_until(stream, &bytes, deadline)?;
        remaining(deadline)?;
        Ok(true)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema_version: u32,
    operation: String,
    binding: FinalUseBinding,
}

#[derive(Serialize)]
struct Response<'a> {
    schema_version: u32,
    revocations: &'a FinalUseRevocations,
    grant: Option<SignedFinalUseGrant>,
    denial_reason: Option<&'static str>,
}

fn remaining(deadline: Instant) -> Result<Duration, HostIssuerTransportError> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|value| !value.is_zero())
        .ok_or(HostIssuerTransportError::DeadlineElapsed)
}

fn read_until(
    stream: &mut UnixStream,
    mut bytes: &mut [u8],
    deadline: Instant,
) -> Result<(), HostIssuerTransportError> {
    while !bytes.is_empty() {
        stream
            .set_read_timeout(Some(remaining(deadline)?))
            .map_err(io_error)?;
        match stream.read(bytes) {
            Ok(0) => return Err(HostIssuerTransportError::Closed),
            Ok(count) => bytes = &mut bytes[count..],
            Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
            Err(error) => return Err(io_error(error)),
        }
    }
    Ok(())
}

fn write_until(
    stream: &mut UnixStream,
    mut bytes: &[u8],
    deadline: Instant,
) -> Result<(), HostIssuerTransportError> {
    while !bytes.is_empty() {
        stream
            .set_write_timeout(Some(remaining(deadline)?))
            .map_err(io_error)?;
        match stream.write(bytes) {
            Ok(0) => return Err(HostIssuerTransportError::Closed),
            Ok(count) => bytes = &bytes[count..],
            Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
            Err(error) => return Err(io_error(error)),
        }
    }
    Ok(())
}

fn io_error(error: impl Into<io::Error>) -> HostIssuerTransportError {
    match error.into().kind() {
        io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock => {
            HostIssuerTransportError::DeadlineElapsed
        }
        _ => HostIssuerTransportError::Unavailable,
    }
}
