//! Purpose-limited server framing shared by the protected authority lanes.

use super::HostIssuerPeer;
use super::HostIssuerTransportError;
use super::channel::OwnerChannel;
use super::io_error;
use std::net::Shutdown;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::time::Duration;

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

/// Server-side channel only. Construction checks the existing SO_PEERCRED and
/// pre-held pidfd. No discovery, authorization policy or issuer is created.
pub struct HostAuthorityPeerChannel {
    stream: Option<UnixStream>,
    policy: HostAuthorityPeerPolicy,
    owner: OwnerChannel,
}

impl HostAuthorityPeerChannel {
    /// Sample the already pinned process lifetime without reading a frame.
    /// This creates no permission and never exposes or replaces its pidfd.
    pub fn check_peer_lifetime(&self) -> Result<(), HostIssuerTransportError> {
        self.owner.check(self.owner.end())
    }

    pub fn from_stream(
        stream: UnixStream,
        policy: HostAuthorityPeerPolicy,
        owner_pidfd: OwnedFd,
    ) -> Result<Self, HostIssuerTransportError> {
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
            stream: Some(stream),
            policy,
            owner,
        })
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
        handle: impl FnOnce(&[u8]) -> Result<Vec<u8>, HostIssuerTransportError>,
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
        let length = u32::from_be_bytes(length) as usize;
        if length == 0 || length > self.policy.request_bound {
            return Err(HostIssuerTransportError::InvalidRequest);
        }
        let mut bytes = vec![0; length];
        self.owner.read_until(stream, &mut bytes, deadline)?;
        self.owner.check(deadline)?;
        let response = handle(&bytes)?;
        self.owner.check(deadline)?;
        if response.is_empty() || response.len() > self.policy.response_bound {
            return Err(HostIssuerTransportError::Unavailable);
        }
        self.owner
            .write_until(stream, &(response.len() as u32).to_be_bytes(), deadline)?;
        self.owner.write_until(stream, &response, deadline)?;
        self.owner.check(deadline)?;
        Ok(true)
    }
}

#[cfg(test)]
#[path = "authority_host_peer_tests.rs"]
mod tests;
