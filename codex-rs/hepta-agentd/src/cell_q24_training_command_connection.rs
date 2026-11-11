//! Original Agentd-to-Trainer connection, bound before Dataset exists.
//! The original descriptor and deadline are consumed once. Only the actual
//! authenticated Material cut can complete the fixed Training context.
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Mutex;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_types::Digest32;

use super::Channel;
use super::LearningIterationEvidencePeerV1;
use super::OriginalCellQ24TrainingCommandClientV1;
use super::OriginalCellQ24TrainingCommandContextV1;
use super::OriginalCellQ24TrainingCommandErrorV1;
use super::OriginalCellQ24TrainingCommandReceiptV1;
use super::now;
use super::wire;
use crate::AgentdRootAuthorityPeer;
use crate::OriginalCellQ24MaterialCommandErrorV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24TrainingCommandConnectionErrorV1 {
    #[error("original Trainer initial connection binding: {0}")]
    Binding(&'static str),
    #[error("original Trainer connection: {0}")]
    Command(#[from] OriginalCellQ24TrainingCommandErrorV1),
    #[error("original Material cut: {0}")]
    Material(#[from] OriginalCellQ24MaterialCommandErrorV1),
}

type Error = OriginalCellQ24TrainingCommandConnectionErrorV1;

enum Origin {
    Fresh,
    Recovered(Option<OriginalCellQ24TrainingCommandReceiptV1>),
}

pub struct OriginalCellQ24TrainingCommandConnectionV1 {
    peer: HostAuthorityPeerChannel,
    material: OriginalCellQ24MaterialReceiptConfigV1,
    initial_binding: Digest32,
    origin: Origin,
}

impl OriginalCellQ24TrainingCommandConnectionV1 {
    /// Called at original Root descriptor handoff, before Dataset exists.
    /// Synchronous bounded peer checks belong on the host's blocking lane.
    pub fn from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        material: OriginalCellQ24MaterialReceiptConfigV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::bind_original_stream(
            stream,
            peer,
            original_owner_pidfd,
            material,
            timeout,
            lifetime,
            Origin::Fresh,
        )
    }

    /// Recovery cannot restore execution. A retained original Training result,
    /// when available, is authenticated against actual D before any readback.
    pub fn recover_from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        material: OriginalCellQ24MaterialReceiptConfigV1,
        expected: Option<OriginalCellQ24TrainingCommandReceiptV1>,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::bind_original_stream(
            stream,
            peer,
            original_owner_pidfd,
            material,
            timeout,
            lifetime,
            Origin::Recovered(expected),
        )
    }

    fn bind_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        material: OriginalCellQ24MaterialReceiptConfigV1,
        timeout: Duration,
        lifetime: Duration,
        origin: Origin,
    ) -> Result<Self, Error> {
        let (initial_binding, started_at) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)?;
        if peer.actor_id != material.initial.owners.trainer {
            return Err(Error::Binding("same original Trainer actor"));
        }
        let peer = original_owner_command_channel_v1(
            stream,
            AgentdRootAuthorityPeer {
                pid: peer.pid,
                boot_id: peer.boot_id,
                process_start_ticks: peer.process_start_ticks,
            },
            peer.uid,
            original_owner_pidfd,
            timeout,
            lifetime,
        )
        .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
        peer.check_peer_lifetime()
            .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
        let (current_binding, fresh_now) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)?;
        if current_binding != initial_binding || fresh_now < started_at {
            return Err(Error::Binding("original Trainer initial context and clock"));
        }
        Ok(Self {
            peer,
            material,
            initial_binding,
            origin,
        })
    }

    /// Consume the original connection after actual Material completion.
    /// No snapshot DTO, future head, batch, label or signing payload is accepted.
    pub fn bind_original_dataset(
        self,
        completed: OriginalCellQ24MaterialCommandReceiptV1,
    ) -> Result<OriginalCellQ24TrainingCommandClientV1, Error> {
        let started_at = now()?;
        let context = OriginalCellQ24TrainingCommandContextV1 {
            dataset: completed.snapshot().clone(),
            scope: self.material.scope.clone(),
            verifier: self.material.verifier.clone(),
        };
        if context.validate()? != self.material.initial {
            return Err(Error::Binding("same original Root initial context"));
        }
        let binding = context.binding()?;
        self.peer
            .check_peer_lifetime()
            .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
        let (original_binding, fresh_now) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(
                &self.material,
            )?;
        let verified_at =
            OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
                &completed,
                &self.material,
            )?;
        if original_binding != self.initial_binding
            || fresh_now < started_at
            || verified_at < fresh_now
        {
            return Err(Error::Binding(
                "same original Trainer connection and fresh Material cut",
            ));
        }
        let (execution_requested, retained) = match self.origin {
            Origin::Fresh => (false, None),
            Origin::Recovered(expected) => (
                true,
                expected
                    .map(|original| {
                        wire::authenticate_receipt(
                            &context,
                            original.receipt,
                            original.attestation,
                            verified_at,
                        )
                    })
                    .transpose()?,
            ),
        };
        Ok(OriginalCellQ24TrainingCommandClientV1 {
            channel: Mutex::new(Some(Channel {
                peer: self.peer,
                next_request_id: 1,
                execution_requested,
            })),
            context,
            binding,
            retained: Mutex::new(retained),
        })
    }
}

#[cfg(test)]
#[path = "cell_q24_training_command_connection_support_tests.rs"]
mod tests;
#[cfg(test)]
pub(crate) use tests::fresh_peer;
#[cfg(test)]
pub(crate) use tests::recovered_peer;
