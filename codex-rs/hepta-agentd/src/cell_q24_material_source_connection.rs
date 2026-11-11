//! An original Material Source connection bound before Dataset exists.
//! Finalization consumes this sealed value and keeps the same transport and
//! session deadline; it cannot accept a decoded batch or reset peer lifetime.
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;

use super::Channel;
use super::Error;
use super::OriginalCellQ24RemoteMaterialClientV1;
use super::now;
use super::verify_context;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationEvidencePeerV1;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalCellQ24TrainingSourceConfigV1;
use crate::root_observation_stream::RootObservationStream;

pub struct OriginalCellQ24MaterialSourceConnectionV1 {
    transport: RootObservationStream,
    initial: LearningIterationSnapshotV1,
    scope: FrozenLearningScopeV2,
    baseline: Arc<LoadedCellQ24ModelV1>,
}

impl OriginalCellQ24MaterialSourceConnectionV1 {
    /// Bind the original descriptor, process and lifetime immediately. No
    /// Dataset receipt, future head, batch, label or signer is supplied.
    pub fn from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        initial: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        baseline: Arc<LoadedCellQ24ModelV1>,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        let coordinator = LearningIterationCoordinatorV1::new(
            initial.request.clone(), initial.owners.clone(),
        )?;
        scope.validate_snapshot(&initial)?;
        // SAFETY: read only this process's original credentials.
        let same_uid = peer.uid == unsafe { libc::getuid() }
            || peer.uid == unsafe { libc::geteuid() };
        if coordinator.snapshot() != &initial
            || same_uid
            || peer.pid == std::process::id()
            || peer.actor_id != initial.owners.dataset
            || baseline.components() != &initial.request.selected_bundle.components
        {
            return Err(Error::Binding("original Material connection and empty Root cut"));
        }
        let transport = RootObservationStream::from_stream_for_uid(
            stream,
            AgentdRootAuthorityPeer {
                pid: peer.pid, boot_id: peer.boot_id,
                process_start_ticks: peer.process_start_ticks,
            },
            original_owner_pidfd,
            timeout,
            lifetime,
            peer.uid,
        ).map_err(|_| Error::Unavailable)?;
        if now()? < started_at {
            return Err(Error::Binding("Material connection clock moved backwards"));
        }
        Ok(Self { transport, initial, scope, baseline })
    }

    pub(crate) fn require_initial_context(
        &self,
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
        baseline: &LoadedCellQ24ModelV1,
    ) -> Result<(), Error> {
        if &self.initial != initial || &self.scope != scope
            || self.baseline.components() != baseline.components()
            || self.baseline.components() != &initial.request.selected_bundle.components
        {
            return Err(Error::Binding("same original Material connection context"));
        }
        Ok(())
    }

    pub(crate) fn bind_original_dataset(
        self,
        config: OriginalCellQ24TrainingSourceConfigV1,
    ) -> Result<OriginalCellQ24RemoteMaterialClientV1, Error> {
        verify_context(&config, now()?)?;
        let initial = LearningIterationCoordinatorV1::new(
            config.dataset.request.clone(), config.dataset.owners.clone(),
        )?;
        self.require_initial_context(initial.snapshot(), &config.scope, &self.baseline)?;
        Ok(OriginalCellQ24RemoteMaterialClientV1 {
            channel: Mutex::new(Some(Channel {
                transport: self.transport,
                next_request_id: 1,
            })),
            config,
            baseline: self.baseline,
        })
    }
}
