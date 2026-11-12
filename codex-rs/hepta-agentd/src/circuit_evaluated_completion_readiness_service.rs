//! Explicit evaluated readiness over the same original Published/Source owner.
//! It cannot enter legacy TNU readiness or turn unresolved C into permission.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;

use super::super::evaluated_readiness;
use super::Error;
use super::OriginalCircuitLearningReadOwnerV1;
use super::now;
use super::require_timing;
use super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

impl<C: AnchorWitnessStore, S: AnchorWitnessStore> OriginalCircuitLearningReadOwnerV1<C, S> {
    pub fn serve_evaluated_completion_readiness(
        &self,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        require_timing(timeout, lifetime)?;
        evaluated_readiness::require_evaluated_next_use(&self.context)?;
        let _permit = self
            .connections
            .try_acquire()
            .map_err(|_| Error::Unavailable)?;
        let mut channel = original_owner_command_channel_v1(
            stream,
            consumer,
            consumer_uid,
            original_consumer_pidfd,
            timeout,
            lifetime,
        )?;
        self.serve_evaluated_readiness_channel(&mut channel)
    }

    pub(in super::super) fn serve_evaluated_readiness_channel(
        &self,
        channel: &mut HostAuthorityPeerChannel,
    ) -> Result<u64, Error> {
        evaluated_readiness::require_evaluated_next_use(&self.context)?;
        for request_id in 1..=128 {
            let mut failure = None;
            let exchanged = channel.exchange(|bytes| {
                self.evaluated_readiness_response(bytes, request_id)
                    .map_err(|error| {
                        failure = Some(error);
                        HostIssuerTransportError::InvalidRequest
                    })
            });
            match exchanged {
                Ok(true) => {}
                Ok(false) => return Ok(request_id - 1),
                Err(error) => return Err(failure.unwrap_or(Error::Transport(error))),
            }
        }
        Err(Error::Unavailable)
    }

    pub(crate) fn evaluated_readiness_response(
        &self,
        bytes: &[u8],
        request_id: u64,
    ) -> Result<Vec<u8>, Error> {
        let started = now()?;
        let request: evaluated_readiness::Request = serde_json::from_slice(bytes)?;
        request.require_context(&self.context, self.binding, request_id)?;
        if self.context.binding(started)? != self.binding {
            return Err(Error::Binding("same original evaluated readiness context"));
        }
        let current = self.read_original_readiness()?;
        let fresh = now()?;
        if fresh < started || self.context.binding(fresh)? != self.binding {
            return Err(Error::Binding(
                "evaluated readiness window after original owner I/O",
            ));
        }
        let result = match current {
            None => evaluated_readiness::Readiness::NotReady,
            Some(read) => evaluated_readiness::Readiness::Ready {
                read: wire::OriginalRead::from_original(read)?,
            },
        };
        let bytes = serde_json::to_vec(&evaluated_readiness::Response { request, result })?;
        if bytes.is_empty() || bytes.len() > 16_384 {
            return Err(Error::Binding(
                "bounded original evaluated readiness response",
            ));
        }
        Ok(bytes)
    }
}
