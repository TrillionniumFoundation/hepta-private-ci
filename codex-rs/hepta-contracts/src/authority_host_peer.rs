//! Purpose-limited server framing shared by the protected authority lanes.

// HEPTA_PHASE_BEGIN
#[cfg(hepta_ci_phase_diagnostic)]
use crate::phase_diagnostic as phase;
// HEPTA_PHASE_END

// HEPTA_PHASE_BEGIN
#[cfg(hepta_ci_phase_diagnostic)]
use crate::phase_observe;
// HEPTA_PHASE_END

// HEPTA_PHASE_BEGIN
#[cfg(not(hepta_ci_phase_diagnostic))]
macro_rules! phase_observe {
    ($kind:ident, $phase:literal, $value:expr) => {
        $value
    };
    (future_at, $context:expr, $phase:literal, $value:expr) => {
        $value
    };
}
// HEPTA_PHASE_END

use super::HostIssuerPeer;
use super::HostIssuerTransportError;
use super::channel::OwnerChannel;
use super::io_error;
use std::net::Shutdown;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::time::Duration;
use std::time::Instant;

#[path = "authority_host_descriptor.rs"]
mod descriptor;

/// Limits and exact owner identity installed by the trusted root launcher.
/// A peer request cannot change these limits, extend its lifetime or reconnect.
#[derive(Clone, Copy, Debug)]
pub struct HostAuthorityPeerPolicy {
    pub peer: HostIssuerPeer,
    pub timeout: Duration,
    pub lifetime: Duration,
    pub request_bound: usize,
    pub response_bound: usize,
}

/// One peer-pinned framed channel. Construction checks the existing SO_PEERCRED
/// and pre-held pidfd. No discovery, authorization policy or issuer is created.
pub struct HostAuthorityPeerChannel {
    // HEPTA_PHASE_BEGIN
    #[cfg(hepta_ci_phase_diagnostic)]
    phase_endpoint: phase::Endpoint,
    // HEPTA_PHASE_END
    stream: Option<UnixStream>,
    policy: HostAuthorityPeerPolicy,
    owner: OwnerChannel,
}

impl HostAuthorityPeerChannel {
    // HEPTA_PHASE_BEGIN
    #[cfg(hepta_ci_phase_diagnostic)]
    pub fn phase_request_context(&self, request_id: u64) -> phase::Context {
        self.phase_endpoint.request(request_id, /*sender*/ true)
    }
    // HEPTA_PHASE_END

    /// Sample the already pinned process lifetime without reading a frame.
    /// This creates no permission and never exposes or replaces its pidfd.
    pub fn check_peer_lifetime(&self) -> Result<(), HostIssuerTransportError> {
        self.owner.check(self.owner.end())
    }

    /// Shorten this already pinned channel to the original enclosing deadline.
    /// A later deadline cannot extend it. Expiry or loss of the pinned owner
    /// closes the original stream permanently, before any further frame I/O.
    pub fn limit_original_end(&mut self, end: Instant) -> Result<(), HostIssuerTransportError> {
        if self.stream.is_none() {
            return Err(HostIssuerTransportError::Closed);
        }
        let result = OwnerChannel::limit_original_end(&mut self.owner, end);
        if result.is_err()
            && let Some(stream) = self.stream.take()
        {
            let _ = stream.shutdown(Shutdown::Both);
        }
        result
    }

    pub fn from_stream(
        stream: UnixStream,
        policy: HostAuthorityPeerPolicy,
        owner_pidfd: OwnedFd,
    ) -> Result<Self, HostIssuerTransportError> {
        // HEPTA_PHASE_BEGIN
        #[cfg(hepta_ci_phase_diagnostic)]
        let phase_endpoint = phase::take_endpoint(&stream);
        // HEPTA_PHASE_END

        if policy.peer.pid == 0
            || policy.peer.pid > i32::MAX as u32
            || policy.timeout.is_zero()
            || policy.timeout > Duration::from_secs(30)
            || !(1..=65_536).contains(&policy.request_bound)
            || !(1..=65_536).contains(&policy.response_bound)
        {
            return Err(HostIssuerTransportError::InvalidConfiguration);
        }
        let peer = rustix::net::sockopt::socket_peercred(&stream).map_err(io_error)?;
        if peer.uid.as_raw() != policy.peer.uid
            || peer.pid.as_raw_nonzero().get() as u32 != policy.peer.pid
        {
            return Err(HostIssuerTransportError::PeerDenied);
        }
        let owner = OwnerChannel::new(owner_pidfd, policy.peer.pid, policy.lifetime)?;
        stream.set_nonblocking(true).map_err(io_error)?;
        Ok(Self {
            // HEPTA_PHASE_BEGIN
            #[cfg(hepta_ci_phase_diagnostic)]
            phase_endpoint,
            // HEPTA_PHASE_END
            stream: Some(stream),
            policy,
            owner,
        })
    }

    /// Send one complete bounded request to the same pinned peer and receive
    /// one complete response. The whole exchange shares one deadline. A lost
    /// response or any other uncertainty closes the channel permanently; this
    /// method never reconnects or retries a possibly delivered request.
    pub fn request(&mut self, request: &[u8]) -> Result<Vec<u8>, HostIssuerTransportError> {
        // HEPTA_PHASE_BEGIN
        #[cfg(hepta_ci_phase_diagnostic)]
        let _phase_context =
            phase::enter(self.phase_endpoint.request_bytes(request, /*sender*/ true));
        // HEPTA_PHASE_END

        // HEPTA_PHASE_BEGIN
        #[cfg(hepta_ci_phase_diagnostic)]
        let _phase_request = phase::scope("peer.request");
        // HEPTA_PHASE_END

        let mut stream = self.stream.take().ok_or(HostIssuerTransportError::Closed)?;
        let result = (|| {
            if request.is_empty() || request.len() > self.policy.request_bound {
                return Err(HostIssuerTransportError::InvalidRequest);
            }
            let deadline = self.owner.deadline(self.policy.timeout);
            // HEPTA_PHASE_BEGIN
            #[cfg(hepta_ci_phase_diagnostic)]
            {
                phase::deadline("peer.client_deadline", deadline);
            }
            // HEPTA_PHASE_END

            phase_observe!(sync, "peer.check", self.owner.check(deadline))?;
            phase_observe!(
                sync,
                "peer.write_prefix",
                self.owner.write_until(
                    &mut stream,
                    &(request.len() as u32).to_be_bytes(),
                    deadline
                )
            )?;
            phase_observe!(
                sync,
                "peer.write_body",
                self.owner.write_until(&mut stream, request, deadline)
            )?;
            let mut length = [0; 4];
            phase_observe!(
                sync,
                "peer.read_prefix",
                self.owner.read_until(&mut stream, &mut length, deadline)
            )?;
            let length = u32::from_be_bytes(length) as usize;
            if length == 0 || length > self.policy.response_bound {
                return Err(HostIssuerTransportError::Unavailable);
            }
            let mut response = vec![0; length];
            phase_observe!(
                sync,
                "peer.read_body",
                self.owner.read_until(&mut stream, &mut response, deadline)
            )?;
            phase_observe!(sync, "peer.check", self.owner.check(deadline))?;
            Ok(response)
        })();
        match result {
            Ok(response) => {
                self.stream = Some(stream);
                Ok(response)
            }
            Err(error) => {
                let _ = stream.shutdown(Shutdown::Both);
                Err(error)
            }
        }
    }

    /// Serve one frame. The handler must return a complete bounded response.
    /// No response prefix is sent before encoding and capacity checks finish.
    /// Storage in the handler is not forcibly cancelled; deadline/owner checks
    /// after it prevent an overdue result from being returned as success.
    /// Any uncertainty permanently closes this stream, including handler errors.
    pub fn exchange(
        &mut self,
        handle: impl FnOnce(&[u8]) -> Result<Vec<u8>, HostIssuerTransportError>,
    ) -> Result<bool, HostIssuerTransportError> {
        self.exchange_with_original_deadline(|bytes, _deadline| handle(bytes))
    }

    /// Expose this frame's already established deadline to a durable handler.
    /// It is the same deadline used for the request, response and final peer
    /// check. The handler cannot renew it or replace the original pinned owner.
    pub fn exchange_with_original_deadline(
        &mut self,
        handle: impl FnOnce(&[u8], Instant) -> Result<Vec<u8>, HostIssuerTransportError>,
    ) -> Result<bool, HostIssuerTransportError> {
        let mut stream = self.stream.take().ok_or(HostIssuerTransportError::Closed)?;
        let result = self.exchange_inner(&mut stream, handle);
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

    fn exchange_inner(
        &self,
        stream: &mut UnixStream,
        handle: impl FnOnce(&[u8], Instant) -> Result<Vec<u8>, HostIssuerTransportError>,
    ) -> Result<bool, HostIssuerTransportError> {
        let mut length = [0; 4];
        if self
            .owner
            .read(stream, &mut length[..1], self.owner.end())?
            == 0
        {
            return Ok(false);
        }
        let deadline = self.owner.deadline(self.policy.timeout);
        self.owner.read_until(stream, &mut length[1..], deadline)?;
        // HEPTA_PHASE_BEGIN
        #[cfg(hepta_ci_phase_diagnostic)]
        let mut phase_receive = phase::timer_at(self.phase_endpoint.waiting(), "peer.receive_body");
        // HEPTA_PHASE_END

        let length = u32::from_be_bytes(length) as usize;
        if length == 0 || length > self.policy.request_bound {
            return Err(HostIssuerTransportError::InvalidRequest);
        }
        let mut bytes = vec![0; length];
        self.owner.read_until(stream, &mut bytes, deadline)?;
        // HEPTA_PHASE_BEGIN
        #[cfg(hepta_ci_phase_diagnostic)]
        let _phase_context =
            phase::enter(self.phase_endpoint.request_bytes(&bytes, /*sender*/ false));
        // HEPTA_PHASE_END

        // HEPTA_PHASE_BEGIN
        #[cfg(hepta_ci_phase_diagnostic)]
        {
            phase_receive.correlate(phase::capture());
            phase_receive.finish();
            phase::deadline("peer.server_deadline", deadline);
        }
        // HEPTA_PHASE_END

        phase_observe!(sync, "peer.check", self.owner.check(deadline))?;
        let response = phase_observe!(sync, "peer.handler", handle(&bytes, deadline))?;
        phase_observe!(sync, "peer.check", self.owner.check(deadline))?;
        if response.is_empty() || response.len() > self.policy.response_bound {
            return Err(HostIssuerTransportError::Unavailable);
        }
        phase_observe!(
            sync,
            "peer.server_write_prefix",
            self.owner
                .write_until(stream, &(response.len() as u32).to_be_bytes(), deadline)
        )?;
        phase_observe!(
            sync,
            "peer.server_write_body",
            self.owner.write_until(stream, &response, deadline)
        )?;
        phase_observe!(sync, "peer.check", self.owner.check(deadline))?;
        Ok(true)
    }
}

#[cfg(test)]
#[path = "authority_host_peer_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "authority_host_peer_deadline_tests.rs"]
mod deadline_tests;
