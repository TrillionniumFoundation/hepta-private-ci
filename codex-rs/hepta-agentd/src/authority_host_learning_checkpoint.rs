//! Dedicated learning transport on the original Root service and live writer.
//! This does not alter the five-lane public handoff or register a new Root owner.

use super::*;
use crate::LearningIterationCheckpointOwnerV1;
use std::time::Instant;

impl HostAuthorityService {
    /// Serve a launcher-transferred dedicated learning stream. The owner must
    /// already have been opened from its original registered protected CAS.
    /// Caller data selects neither the owner nor the registered writer. The
    /// existing peer-pinned channel bounds frames and checks process lifetime
    /// after storage; an overdue/uncertain result is never acknowledged.
    pub fn serve_learning_checkpoint(
        &self,
        backend: &LearningIterationCheckpointOwnerV1,
        stream: UnixStream,
        policy: HostAuthorityPeerPolicy,
        owner_pidfd: OwnedFd,
    ) -> Result<(), HostIssuerTransportError> {
        self.serve_learning_checkpoint_with_end(
            backend,
            stream,
            policy,
            owner_pidfd,
            /*original_end*/ None,
        )
    }

    pub(crate) fn serve_learning_checkpoint_until(
        &self,
        backend: &LearningIterationCheckpointOwnerV1,
        stream: UnixStream,
        policy: HostAuthorityPeerPolicy,
        owner_pidfd: OwnedFd,
        end: Instant,
    ) -> Result<(), HostIssuerTransportError> {
        self.serve_learning_checkpoint_with_end(backend, stream, policy, owner_pidfd, Some(end))
    }

    fn serve_learning_checkpoint_with_end(
        &self,
        backend: &LearningIterationCheckpointOwnerV1,
        stream: UnixStream,
        mut policy: HostAuthorityPeerPolicy,
        owner_pidfd: OwnedFd,
        original_end: Option<Instant>,
    ) -> Result<(), HostIssuerTransportError> {
        let writer: &RegisteredWriter = self
            .writer
            .as_ref()
            .ok_or(HostIssuerTransportError::Unavailable)?;
        if backend.registered_agent_id() != self.identity.agent_id.to_string() {
            return Err(HostIssuerTransportError::PeerDenied);
        }
        policy.request_bound = 16 * 1024;
        policy.response_bound = 16 * 1024;
        let mut channel = HostAuthorityPeerChannel::from_stream(stream, policy, owner_pidfd)?;
        if let Some(end) = original_end {
            channel.limit_original_end(end)?;
        }
        let mut next_request_id = 1;
        while channel.exchange(|bytes| {
            self.check_logind_lifetime().map_err(unavailable)?;
            let response = writer.exchange_learning_checkpoint(
                &self.issuer,
                &self.clock,
                backend,
                bytes,
                &mut next_request_id,
            )?;
            self.check_logind_lifetime().map_err(unavailable)?;
            Ok(response)
        })? {}
        Ok(())
    }
}
