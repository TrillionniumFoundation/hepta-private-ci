//! The actual same-actor receiver selects this additional closed profile.
//! The original scope and Root stream checks remain the only lane authority.

use std::sync::Arc;

use super::*;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;

impl AgentdLearningCheckpointClientV1 {
    pub(crate) fn from_original_same_actor_stream_until(
        stream: UnixStream,
        peer: AgentdRootAuthorityPeer,
        root_pidfd: OwnedFd,
        initial: LearningIterationSnapshotV1,
        timeout: Duration,
        scope: FrozenLearningScopeV2,
        gate: &Arc<SameActorPhaseGate>,
    ) -> Result<Self, Error> {
        let mut closing = CloseSameActorPhaseOnDrop::new(gate);
        gate.require_open()
            .map_err(|_| Error::Store(AuthorityTrustError::Unavailable))?;
        scope.validate_snapshot(&initial).map_err(Error::Snapshot)?;
        let expected =
            LearningIterationCoordinatorV1::new(initial.request.clone(), initial.owners.clone())
                .map_err(Error::Snapshot)?;
        if expected.snapshot() != &initial {
            return Err(Error::WrongScope);
        }
        // Retain this exact connected stream before transferring it to the
        // original Root-pidfd constructor. No later remaining time is minted.
        let phase = gate
            .retain_required_original_stream(&stream)
            .map_err(|_| Error::Store(AuthorityTrustError::Unavailable))?;
        let transport = RootObservationStream::from_stream_until(
            stream,
            peer,
            root_pidfd,
            timeout,
            gate.deadline().instant(),
        )
        .map_err(|_| Error::Store(AuthorityTrustError::Unavailable))?;
        let client = Self {
            channel: Mutex::new(Some(Channel {
                transport,
                next_request_id: 1,
            })),
            initial,
            scope: Some(scope),
            phase: Some(phase),
        };
        client.require_original_phase(/*mutation*/ false)?;
        closing.disarm();
        Ok(client)
    }

    pub(super) fn original_phase_failure_scope(&self) -> Option<CloseSameActorPhaseOnDrop> {
        self.phase
            .as_ref()
            .map(|phase: &RequiredSameActorPhaseChannel| phase.failure_scope())
    }

    pub(super) fn require_original_phase(&self, mutation: bool) -> Result<(), Error> {
        if let Some(phase) = &self.phase {
            let phase: &RequiredSameActorPhaseChannel = phase;
            phase.require_open().map_err(|_| {
                if mutation {
                    Error::CommitUncertain(AuthorityTrustError::Unavailable)
                } else {
                    Error::Store(AuthorityTrustError::Unavailable)
                }
            })?;
        }
        Ok(())
    }
}
