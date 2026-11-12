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
use super::super::current_read::OriginalPublishedReadCurrent;
use super::super::current_read::OriginalPublishedReadPurpose;
use super::Error;
use super::OriginalCircuitLearningReadContextV1 as Context;
use super::OriginalCircuitLearningReadbackV1 as Readback;
use super::now;
use super::profile::ReadProfile;
use super::require_timing;
use super::wire;
use crate::AgentdIdentity;
use crate::AgentdRootAuthorityPeer;
use crate::CircuitTaskSourceReadbackV1;
use crate::PublishedCircuitCellOwnerV1;
use crate::circuit_feature_task_digest_v1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

#[path = "circuit_evaluated_completion_readiness_service.rs"]
mod evaluated_readiness;
#[path = "circuit_learning_completion_readiness_service.rs"]
mod readiness;

pub struct OriginalCircuitLearningReadOwnerV1<C: AnchorWitnessStore, S: AnchorWitnessStore> {
    cell: PublishedCircuitCellOwnerV1<C>,
    source: CircuitTaskSourceReadbackV1<S>,
    identity: AgentdIdentity,
    context: ReadProfile,
    binding: Digest32,
    connections: Semaphore,
}

impl<C: AnchorWitnessStore, S: AnchorWitnessStore> OriginalCircuitLearningReadOwnerV1<C, S> {
    pub fn from_original_owners(
        cell: PublishedCircuitCellOwnerV1<C>,
        source: CircuitTaskSourceReadbackV1<S>,
        identity: AgentdIdentity,
        context: Context,
    ) -> Result<Self, Error> {
        Self::from_original_profile(
            cell,
            source,
            identity,
            ReadProfile::TrainingNoUpdate(context),
        )
    }

    pub(super) fn from_original_profile(
        cell: PublishedCircuitCellOwnerV1<C>,
        source: CircuitTaskSourceReadbackV1<S>,
        identity: AgentdIdentity,
        context: ReadProfile,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        let binding = context.binding(started_at)?;
        let owner = Self {
            cell,
            source,
            identity,
            context,
            binding,
            connections: Semaphore::new(4),
        };
        owner.require_task_input_current()?;
        let coordinator = owner.context.decision()?;
        let cell: &PublishedCircuitCellOwnerV1<_> = &owner.cell;
        let observed = cell.read_learning_selection(&coordinator)?;
        owner.require_original_selection(&observed)?;
        owner.require_task_input_current()?;
        let fresh = now()?;
        if fresh < started_at || owner.context.binding(fresh)? != binding {
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

    /// Same prebound channel, used only by the original retained Version host
    /// after its actual C factory produced these original read-only owners.
    pub(crate) fn serve_original_retained_channel(
        &self,
        channel: &mut HostAuthorityPeerChannel,
    ) -> Result<u64, Error> {
        if wire::mode(self.context.legacy()?)? != wire::Mode::Selection {
            return Err(Error::Binding(
                "retained Version Selection-only read purpose",
            ));
        }
        self.serve_channel(channel)
    }

    /// Same original channel, with an explicitly evaluated four-cut purpose.
    /// It does not admit five-cut completion or the legacy three-cut profile.
    pub(crate) fn serve_original_evaluated_retained_channel(
        &self,
        channel: &mut HostAuthorityPeerChannel,
    ) -> Result<u64, Error> {
        let ReadProfile::Evaluated(context) = &self.context else {
            return Err(Error::Binding(
                "evaluated Version Selection-only read profile",
            ));
        };
        if context.mode() != wire::Mode::Selection {
            return Err(Error::Binding(
                "evaluated Version Selection-only read purpose",
            ));
        }
        self.serve_channel(channel)
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
        self.context
            .require_request(&request, self.binding, request_id)?;
        if self.context.binding(started_at)? != self.binding {
            return Err(Error::Binding("same original published context"));
        }
        let read = self.read_original()?;
        let fresh = now()?;
        if fresh < started_at || self.context.binding(fresh)? != self.binding {
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
        let mut current = OriginalPublishedReadCurrent::individual(&self.cell);
        self.require_task_input_current_with_current(&mut current)
    }

    fn require_task_input_current_with_current(
        &self,
        current: &mut OriginalPublishedReadCurrent<'_, C>,
    ) -> Result<(), Error> {
        OriginalPublishedReadCurrent::require(current, &self.cell)?;
        let input = self.cell.task.source();
        let request = &self.context.prefix().request;
        if self.identity.agent_id.as_str() != request.agent_id.as_str()
            || input.scope.agent_id != request.agent_id
            || input.scope.cell_id != request.cell_id
            || input.scope.principal_digest.to_string() != request.principal_id.as_str()
            || input.scope.run_id == request.source_run_id
        {
            return Err(Error::Binding("original distinct published task input"));
        }
        let source: &CircuitTaskSourceReadbackV1<_> = &self.source;
        source.require_original_input(&self.identity, input)?;
        OriginalPublishedReadCurrent::require(current, &self.cell)?;
        Ok(())
    }

    fn require_original_selection(
        &self,
        observed: &codex_hepta_learning_artifacts::LearningIterationObservationV1,
    ) -> Result<(), Error> {
        self.context.scope().validate_observation(observed)?;
        if self.context.mode()? == wire::Mode::NextUse && self.context.selection()? != observed {
            return Err(Error::Binding("original Selector receipt and publication"));
        }
        Ok(())
    }

    fn read_original(&self) -> Result<Readback, Error> {
        let mut current = OriginalPublishedReadCurrent::for_original_read(&self.cell);
        self.require_task_input_current_with_current(&mut current)?;
        let coordinator = self.context.decision()?;
        let cell: &PublishedCircuitCellOwnerV1<_> = &self.cell;
        let selection = cell.read_learning_selection_with_current(&coordinator, &mut current)?;
        self.require_original_selection(&selection)?;
        let Publication::Update { original, .. } = &self.cell.task.0.publication else {
            return Err(Error::Binding("original successor publication"));
        };
        let publication = original.publication_digest()?;
        let source_input =
            circuit_feature_task_digest_v1(self.cell.task.definition(), self.cell.task.source())?;
        let mode = self.context.mode()?;
        OriginalPublishedReadCurrent::select_purpose(
            &mut current,
            match mode {
                wire::Mode::Selection => OriginalPublishedReadPurpose::Selection,
                wire::Mode::NextUse => OriginalPublishedReadPurpose::NextUse,
            },
        )?;
        let (observation, source_publication) = match mode {
            wire::Mode::Selection => (selection.clone(), None),
            wire::Mode::NextUse => {
                let before = self
                    .source
                    .read_run_publication(&self.identity, &self.cell.task.source().scope.run_id)?;
                let prefix =
                    LearningIterationCoordinatorV1::from_snapshot(self.context.prefix().clone())?;
                let observed = cell.read_learning_next_use_with_current(
                    &prefix,
                    &self.source,
                    &self.identity,
                    &mut current,
                )?;
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
        self.require_task_input_current_with_current(&mut current)?;
        if cell.read_learning_selection_with_current(&coordinator, &mut current)? != selection {
            return Err(Error::Binding("original selection changed during read"));
        }
        self.require_task_input_current_with_current(&mut current)?;
        OriginalPublishedReadCurrent::finish(current)?;
        Ok(Readback {
            observation,
            publication,
            source_input,
            source_publication,
        })
    }
}
