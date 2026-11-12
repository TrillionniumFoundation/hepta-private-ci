//! Existing Training purpose served by the one deferred original host.
//! Request context is checked before consuming custody. Once initialization can
//! begin, all connections share the same Starting/Ready/Fenced state forever.
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;

use super::super::wire;
use super::Error;
use super::Origin;
use super::OriginalCellQ24TrainingBootstrapOwnerV1;
use super::OriginalCellQ24TrainingCommandErrorV1;
use super::OriginalCellQ24TrainingCommandOwnerV1;
use super::State;
use super::now;
use crate::AgentdRootAuthorityPeer;
use crate::OriginalCellQ24DatasetCommandReadbackV1;
use crate::OriginalCellQ24MaterialCommandErrorV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

#[path = "cell_q24_training_bootstrap_candidate.rs"]
mod candidate;

impl<TW: AnchorWitnessStore + Send + 'static, RW: AnchorWitnessStore + Send + 'static>
    OriginalCellQ24TrainingBootstrapOwnerV1<TW, RW>
{
    pub async fn serve_commands(
        self: Arc<Self>,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        let permit = Arc::clone(&self.connections)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let mut channel = original_owner_command_channel_v1(
                stream,
                consumer,
                consumer_uid,
                original_consumer_pidfd,
                timeout,
                lifetime,
            )
            .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
            self.serve_command_channel(&mut channel)
        })
        .await
        .map_err(|_| Error::Uncertain)?
    }

    /// The existing evidence protocol stays read-only and bounded to 500 ms.
    /// It never bootstraps Missing owners; first use requires the command path.
    pub async fn serve_evidence_readback(
        self: Arc<Self>,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        let _permit = Arc::clone(&self.connections)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        let original = self
            .ready()?
            .ok_or(Error::Binding("original Trainer is not bootstrapped"))?;
        Ok(
            OriginalCellQ24TrainingCommandOwnerV1::serve_evidence_readback(
                original,
                stream,
                consumer,
                consumer_uid,
                original_consumer_pidfd,
                timeout,
                lifetime,
            )
            .await?,
        )
    }

    pub(super) fn ready(
        &self,
    ) -> Result<Option<Arc<OriginalCellQ24TrainingCommandOwnerV1<TW, RW>>>, Error> {
        let state = self.state.try_lock().map_err(|_| Error::Busy)?;
        match &*state {
            State::Awaiting(_) => Ok(None),
            State::Starting => Err(Error::Busy),
            State::Ready(original) => Ok(Some(Arc::clone(original))),
            State::Fenced => Err(Error::Uncertain),
        }
    }

    pub(super) fn serve_command_channel(
        &self,
        channel: &mut HostAuthorityPeerChannel,
    ) -> Result<u64, Error> {
        for request_id in 1..=128_u64 {
            let exchanged = channel
                .exchange(|bytes| {
                    self.command_response(bytes, request_id)
                        .map_err(|_| HostIssuerTransportError::InvalidRequest)
                })
                .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
            if !exchanged {
                return Ok(request_id - 1);
            }
        }
        Err(Error::Uncertain)
    }

    pub(super) fn command_response(&self, bytes: &[u8], request_id: u64) -> Result<Vec<u8>, Error> {
        let request: wire::Request =
            serde_json::from_slice(bytes).map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
        self.require_initial_request(&request, request_id)?;
        if let Some(original) = self.ready()? {
            return Ok(original.command_response(bytes, request_id)?);
        }
        let result = if matches!(self.origin, Origin::Recovered)
            && request.action == wire::Action::Execute
        {
            wire::CommandResult::ReadbackRequired
        } else if matches!(self.origin, Origin::Fresh) && request.action == wire::Action::Readback {
            wire::CommandResult::ReadbackRequired
        } else {
            let _permit = self.bootstrap_lane.try_acquire().map_err(|_| Error::Busy)?;
            if let Some(original) = self.ready()? {
                return Ok(original.command_response(bytes, request_id)?);
            }
            let started_at = now()?;
            let cut =
                match self
                    .runtime
                    .block_on(OriginalCellQ24DatasetCommandReadbackV1::readback(
                        &self.dataset,
                    )) {
                    Ok(cut) => cut,
                    Err(OriginalCellQ24MaterialCommandErrorV1::Missing) => {
                        return self.response(&request, wire::CommandResult::Unavailable);
                    }
                    Err(OriginalCellQ24MaterialCommandErrorV1::Pending) => {
                        return self.response(&request, wire::CommandResult::Unavailable);
                    }
                    Err(error) => return Err(error.into()),
                };
            let context = self.actual_context(&cut, &request, request_id, started_at)?;
            // No writer exists before the exact actual Dataset request passes.
            // This one transition is shared by every connection; no error can
            // put original files, key or streams back into Awaiting.
            let custody = {
                let mut state = self.state.try_lock().map_err(|_| Error::Busy)?;
                match std::mem::replace(&mut *state, State::Starting) {
                    State::Awaiting(custody) => custody,
                    other => {
                        *state = other;
                        return Err(Error::Uncertain);
                    }
                }
            };
            let built = self
                .runtime
                .block_on(self.build_original_owner(custody, context, cut, started_at));
            let original = match built {
                Ok(original) => {
                    *self.state.try_lock().map_err(|_| Error::Uncertain)? =
                        State::Ready(Arc::clone(&original));
                    original
                }
                Err(error) => {
                    *self.state.try_lock().map_err(|_| Error::Uncertain)? = State::Fenced;
                    return Err(error);
                }
            };
            // Retain Ready before any fit/claim or ACK, so later reads borrow
            // the same original lane even if this connection disappears.
            return Ok(original.command_response(bytes, request_id)?);
        };
        self.response(&request, result)
    }

    fn response(
        &self,
        request: &wire::Request,
        result: wire::CommandResult,
    ) -> Result<Vec<u8>, Error> {
        Ok(
            serde_json::to_vec(&wire::Response::from_request(request, result))
                .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?,
        )
    }

    fn require_initial_request(
        &self,
        request: &wire::Request,
        request_id: u64,
    ) -> Result<(), Error> {
        let initial = &self.config.material.initial;
        let digest = |text: &str| -> Result<Digest32, Error> {
            let digest: Digest32 = text
                .parse()
                .map_err(|_| Error::Binding("canonical Trainer binding"))?;
            if digest.is_zero() || digest.to_string() != text {
                return Err(Error::Binding("canonical Trainer binding"));
            }
            Ok(digest)
        };
        digest(&request.binding)?;
        digest(&request.dataset_head)?;
        if request.schema != 1
            || request.operation != wire::OPERATION
            || request.request_id != request_id
            || request.operation_id != initial.request.operation_id.as_str()
            || request.actor_id != initial.owners.trainer.as_str()
            || request.scope_binding != self.config.material.scope.binding().to_string()
            || request.action == wire::Action::Readback && request.cancelled
        {
            return Err(Error::Binding("same original Trainer bootstrap request"));
        }
        Ok(())
    }
}
