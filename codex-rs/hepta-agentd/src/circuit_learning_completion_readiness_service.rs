//! The original Published owner serves only completion readiness here.
//! Missing/Pending source data is unresolved, not proof that C never executed.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;

use super::super::readiness;
use super::Error;
use super::OriginalCircuitLearningReadOwnerV1;
use super::Readback;
use super::now;
use super::require_timing;
use super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::CircuitTaskErrorV1;
use crate::CircuitTaskSourceReadbackV1;
use crate::PublishedCircuitCellOwnerV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

impl<C: AnchorWitnessStore, S: AnchorWitnessStore> OriginalCircuitLearningReadOwnerV1<C, S> {
    /// A distinct read-only purpose. The original task host must already hold
    /// the actual published C, its original Source and the full original S cut.
    /// No request creates, executes, reconciles or signs ordinary work.
    pub fn serve_completion_readiness(
        &self,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        require_timing(timeout, lifetime)?;
        if wire::mode(&self.context)? != wire::Mode::NextUse {
            return Err(Error::Binding("only original C completion readiness"));
        }
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
        self.serve_readiness_channel(&mut channel)
    }

    pub(in super::super) fn serve_readiness_channel(
        &self,
        channel: &mut HostAuthorityPeerChannel,
    ) -> Result<u64, Error> {
        for request_id in 1..=128 {
            let mut failure = None;
            let exchanged = channel.exchange(|bytes| {
                self.readiness_response(bytes, request_id).map_err(|error| {
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

    pub(in super::super) fn readiness_response(
        &self,
        bytes: &[u8],
        request_id: u64,
    ) -> Result<Vec<u8>, Error> {
        let started_at = now()?;
        let request: readiness::Request = serde_json::from_slice(bytes)?;
        request.require_context(&self.context, self.binding, request_id)?;
        if wire::context_binding(&self.context, started_at)? != self.binding {
            return Err(Error::Binding("same original readiness context"));
        }
        let current = self.read_original_readiness()?;
        let fresh = now()?;
        if fresh < started_at || wire::context_binding(&self.context, fresh)? != self.binding {
            return Err(Error::Binding("readiness window after original owner I/O"));
        }
        let result = match current {
            None => readiness::Readiness::NotReady,
            Some(read) => readiness::Readiness::Ready {
                read: wire::OriginalRead::from_original(read)?,
            },
        };
        let bytes = serde_json::to_vec(&readiness::Response { request, result })?;
        if bytes.is_empty() || bytes.len() > 16_384 {
            return Err(Error::Binding("bounded original readiness response"));
        }
        Ok(bytes)
    }

    fn read_original_readiness(&self) -> Result<Option<Readback>, Error> {
        self.require_task_input_current()?;
        let coordinator = wire::decision(&self.context)?;
        let cell: &PublishedCircuitCellOwnerV1<_> = &self.cell;
        let selection = cell.read_learning_selection(&coordinator)?;
        self.require_original_selection(&selection)?;
        let publication = CircuitTaskSourceReadbackV1::read_run_publication(
            &self.source,
            &self.identity,
            &self.cell.task.source().scope.run_id,
        );
        let current = match publication {
            Err(CircuitTaskErrorV1::ReconciliationRequired) => {
                // Only original Missing/Pending maps here. This says nothing
                // about whether an external effect already happened.
                PublishedCircuitCellOwnerV1::snapshot(&self.cell, &self.cell.task.source().scope)
                    .map_err(|_| Error::Binding("original C private state unavailable"))?;
                None
            }
            Err(error) => return Err(Error::Source(error)),
            Ok(before) => {
                let current = self.read_original()?;
                if current.source_publication != Some(before.publication_digest()) {
                    return Err(Error::Binding("C publication changed across readiness"));
                }
                Some(current)
            }
        };
        self.require_task_input_current()?;
        if cell.read_learning_selection(&coordinator)? != selection {
            return Err(Error::Binding(
                "original Selection changed during readiness",
            ));
        }
        self.require_task_input_current()?;
        Ok(current)
    }
}
