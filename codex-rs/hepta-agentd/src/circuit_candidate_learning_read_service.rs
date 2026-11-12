//! Actual same-owner reads. Journal/Source locks are dropped before encoding
//! or writing any wire response; this service performs no claim or execution.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;
use tokio::sync::Semaphore;

use super::super::Publication;
use super::Error;
use super::OriginalCircuitCandidateLearningReadContextV1 as Context;
use super::OriginalCircuitCandidateLearningReadbackV1 as Readback;
use super::now;
use super::require_timing;
use super::wire;
use crate::AgentdIdentity;
use crate::AgentdRootAuthorityPeer;
use crate::CircuitTaskSourceReadbackV1;
use crate::PublishedCircuitCellOwnerV1;
use crate::circuit_feature_task_digest_v1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

#[path = "circuit_candidate_learning_completion_readiness_service.rs"]
mod readiness;

pub struct OriginalCircuitCandidateLearningReadOwnerV1<C: AnchorWitnessStore, S: AnchorWitnessStore> {
    cell: PublishedCircuitCellOwnerV1<C>,
    source: CircuitTaskSourceReadbackV1<S>,
    identity: AgentdIdentity,
    context: Context,
    binding: Digest32,
    connections: Semaphore,
}

impl<C: AnchorWitnessStore, S: AnchorWitnessStore> OriginalCircuitCandidateLearningReadOwnerV1<C, S> {
    pub fn from_original_owners(
        cell: PublishedCircuitCellOwnerV1<C>,
        source: CircuitTaskSourceReadbackV1<S>,
        identity: AgentdIdentity,
        context: Context,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        let binding = wire::context_binding(&context, started_at)?;
        let owner = Self {
            cell,
            source,
            identity,
            context,
            binding,
            connections: Semaphore::new(4),
        };
        owner.require_task_input_current()?;
        let coordinator = wire::decision(&owner.context)?;
        let cell: &PublishedCircuitCellOwnerV1<_> = &owner.cell;
        let observed = cell.read_learning_selection(&coordinator)?;
        owner.require_original_selection(&observed)?;
        owner.require_task_input_current()?;
        let fresh = now()?;
        if fresh < started_at || wire::context_binding(&owner.context, fresh)? != binding {
            return Err(Error::Binding("original published bootstrap clock"));
        }
        Ok(owner)
    }

    /// Read only this original mode/cut from a preconnected original consumer.
    /// A connection has no operation or role upgrade and no writer exposure.
    /// The original host must call this on its bounded blocking serving lane.
    pub fn serve_readback(
        &self,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        require_timing(timeout, lifetime)?;
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
        self.serve_channel(&mut channel)
    }

    /// Same prebound channel, used only by the original positive Version host
    /// after its actual C factory produced these original read-only owners.
    pub(crate) fn serve_original_candidate_channel(
        &self,
        channel: &mut HostAuthorityPeerChannel,
    ) -> Result<u64, Error> {
        if wire::mode(&self.context)? != wire::Mode::Selection {
            return Err(Error::Binding(
                "positive Version Selection-only read purpose",
            ));
        }
        self.serve_channel(channel)
    }

    /// Original positive Version host retains this same prebound NextUse peer.
    pub(crate) fn serve_original_next_use_channel(
        &self,
        channel: &mut HostAuthorityPeerChannel,
    ) -> Result<u64, Error> {
        if wire::mode(&self.context)? != wire::Mode::NextUse {
            return Err(Error::Binding("positive Version NextUse-only read purpose"));
        }
        self.serve_channel(channel)
    }

    pub(crate) fn serve_original_readiness_channel(
        &self,
        channel: &mut HostAuthorityPeerChannel,
    ) -> Result<u64, Error> {
        if wire::mode(&self.context)? != wire::Mode::NextUse {
            return Err(Error::Binding("positive Version NextUse-only readiness"));
        }
        self.serve_readiness_channel(channel)
    }

    pub(super) fn serve_channel(
        &self,
        channel: &mut HostAuthorityPeerChannel,
    ) -> Result<u64, Error> {
        for request_id in 1..=128 {
            let mut failure = None;
            let exchanged = channel.exchange(|bytes| {
                self.response(bytes, request_id).map_err(|error| {
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

    pub(super) fn response(&self, bytes: &[u8], request_id: u64) -> Result<Vec<u8>, Error> {
        let started_at = now()?;
        let request: wire::Request = serde_json::from_slice(bytes)?;
        request.require_context(&self.context, self.binding, request_id)?;
        if wire::context_binding(&self.context, started_at)? != self.binding {
            return Err(Error::Binding("same original published context"));
        }
        let read = self.read_original()?;
        let fresh = now()?;
        if fresh < started_at || wire::context_binding(&self.context, fresh)? != self.binding {
            return Err(Error::Binding("original read window after owner I/O"));
        }
        // read_original returned owned data; no Cell/Source mutex is held here.
        let read = wire::OriginalRead::from_original(read)?;
        let bytes = serde_json::to_vec(&wire::Response { request, read })?;
        if bytes.is_empty() || bytes.len() > 16_384 {
            return Err(Error::Binding("bounded original published response"));
        }
        Ok(bytes)
    }

    fn require_task_input_current(&self) -> Result<(), Error> {
        self.cell.task.require_current()?;
        let input = self.cell.task.source();
        let request = &self.context.prefix.request;
        if self.identity.agent_id.as_str() != request.agent_id.as_str()
            || input.scope.agent_id != request.agent_id
            || input.scope.cell_id != request.cell_id
            || input.scope.principal_digest.to_string() != request.principal_id.as_str()
            || input.scope.run_id == request.source_run_id
        {
            return Err(Error::Binding("original distinct published task input"));
        }
        let Publication::Update { previous, .. } = &self.cell.task.0.publication else {
            return Err(Error::Binding("original positive successor publication"));
        };
        if input.observation == previous.source.input().observation {
            return Err(Error::Binding("positive C requires a different actual input"));
        }
        let source: &CircuitTaskSourceReadbackV1<_> = &self.source;
        source.require_original_input(&self.identity, input)?;
        self.cell.task.require_current()?;
        Ok(())
    }

    fn require_original_selection(
        &self,
        observed: &codex_hepta_learning_artifacts::LearningIterationObservationV1,
    ) -> Result<(), Error> {
        self.context.scope().validate_observation(observed)?;
        let decision = wire::decision(&self.context)?;
        let candidate = decision.candidate()
            .ok_or(Error::Binding("original trained positive Candidate"))?
            .digest()
            .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
        if !matches!(observed,
            codex_hepta_learning_artifacts::LearningIterationObservationV1::Selection {
                candidate_bundle, selection_digest
            } if *candidate_bundle == candidate && !selection_digest.is_zero())
        {
            return Err(Error::Binding("actual original changed Model selection"));
        }
        if wire::mode(&self.context)? == wire::Mode::NextUse
            && self.context.prefix.receipts[5].observation != *observed
        {
            return Err(Error::Binding("original Selector receipt and publication"));
        }
        Ok(())
    }

    fn read_original(&self) -> Result<Readback, Error> {
        self.require_task_input_current()?;
        let coordinator = wire::decision(&self.context)?;
        let cell: &PublishedCircuitCellOwnerV1<_> = &self.cell;
        let selection = cell.read_learning_selection(&coordinator)?;
        self.require_original_selection(&selection)?;
        let Publication::Update { original, .. } = &self.cell.task.0.publication else {
            return Err(Error::Binding("original successor publication"));
        };
        let publication = original.publication_digest()?;
        let source_input =
            circuit_feature_task_digest_v1(self.cell.task.definition(), self.cell.task.source())?;
        let (observation, source_publication) = match wire::mode(&self.context)? {
            wire::Mode::Selection => (selection.clone(), None),
            wire::Mode::NextUse => {
                let before = self
                    .source
                    .read_run_publication(&self.identity, &self.cell.task.source().scope.run_id)?;
                let prefix =
                    LearningIterationCoordinatorV1::from_snapshot(self.context.prefix.clone())?;
                let observed =
                    cell.read_learning_next_use(&prefix, &self.source, &self.identity)?;
                if self
                    .source
                    .read_run_publication(&self.identity, &self.cell.task.source().scope.run_id)?
                    != before
                {
                    return Err(Error::Binding("original C source changed during read"));
                }
                (observed, Some(before.publication_digest()))
            }
        };
        self.require_task_input_current()?;
        if cell.read_learning_selection(&coordinator)? != selection {
            return Err(Error::Binding("original selection changed during read"));
        }
        self.require_task_input_current()?;
        Ok(Readback {
            observation,
            publication,
            source_input,
            source_publication,
        })
    }
}
