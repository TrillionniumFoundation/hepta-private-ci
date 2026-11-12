//! Private normal-retirement transitions for one actual learning Work.
//! A C request is an owned capability. No count, boolean or decoded message
//! can construct the returned terminal/ACK/real-join owner facts.

use super::*;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use crate::circuit_learning_delivery::OriginalDurableLearningAcknowledgement;
use crate::circuit_task::OriginalSameActorCQuiescence;

pub(super) struct OriginalLearningRetirement {
    state: Mutex<OriginalLearningRetirementState>,
    changed: Notify,
}

enum OriginalLearningRetirementState {
    Open,
    Requested(Box<OriginalSameActorCQuiescence>),
    Taken,
    StopAuthorized(Box<LearningIterationSnapshotV1>),
    StopTaken,
}

/// Created only by consuming the one stop state authorized by the actual
/// C capability and original durable delivery ACK.
pub(crate) struct OriginalLearningStop {
    work: Arc<OriginalSameActorLearningWork>,
    snapshot: LearningIterationSnapshotV1,
}

/// Only the normal join path creates this after admission is closed and every
/// retained real handle has joined, every output was delivered, and every job
/// holder has released custody.
pub(crate) struct OriginalLearningWorkJoined {
    work: Arc<OriginalSameActorLearningWork>,
}

impl OriginalLearningRetirement {
    pub(super) fn new() -> Self {
        Self {
            state: Mutex::new(OriginalLearningRetirementState::Open),
            changed: Notify::new(),
        }
    }
}

impl OriginalSameActorLearningWork {
    pub(crate) fn require_original_retirement_identity(
        &self,
        identity: &AgentdIdentity,
        gate: &Arc<SameActorPhaseGate>,
    ) -> Result<(), AgentdError> {
        if self.context.identity() != identity || !Arc::ptr_eq(self.gate(), gate) {
            self.gate().close();
            return Err(refused("retired learning Work has another original phase or identity"));
        }
        self.gate().require_open().map(|_| ()).map_err(refused)
    }

    pub(crate) fn require_original_delivery_request(
        &self,
        request: &codex_hepta_learning_artifacts::LearningIterationRequestV1,
        owners: &codex_hepta_learning_artifacts::LearningIterationOwnersV1,
    ) -> Result<(), AgentdError> {
        self.require_original_retirement_identity(self.context.identity(), self.gate())?;
        if request != &self.prepared.initial().request
            || owners != &self.prepared.initial().owners
        {
            self.gate().close();
            return Err(refused("delivery request differs from original Prepared"));
        }
        self.prepared.scope().validate_request(request, owners).map_err(refused)
    }

    pub(crate) fn require_original_terminal_snapshot(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(), AgentdError> {
        self.require_original_retirement_identity(self.context.identity(), self.gate())?;
        if snapshot.request != self.prepared.initial().request
            || snapshot.owners != self.prepared.initial().owners
        {
            self.gate().close();
            return Err(refused("terminal checkpoint differs from its original Prepared"));
        }
        self.prepared.scope().validate_snapshot(snapshot).map_err(refused)?;
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())
            .map_err(refused)?;
        if coordinator.next_stage().is_some() {
            self.gate().close();
            return Err(refused("original learning checkpoint is not terminal"));
        }
        Ok(())
    }

    pub(crate) fn request_original_normal_retirement(
        self: &Arc<Self>,
        quiescence: OriginalSameActorCQuiescence,
    ) -> Result<(), AgentdError> {
        let mut closing = self.original_failure_scope();
        self.require_identity_and_gate(self.context.identity(), self.gate())?;
        OriginalSameActorCQuiescence::require_original_phase(
            &quiescence, self.context.identity(), self.gate(),
        )?;
        OriginalSameActorCQuiescence::require_original_learning_work(&quiescence, self)?;
        let mut state = self.retirement.state.lock().map_err(refused)?;
        if !matches!(*state, OriginalLearningRetirementState::Open) {
            return Err(refused("original C retirement request was already used"));
        }
        *state = OriginalLearningRetirementState::Requested(Box::new(quiescence));
        drop(state);
        self.retirement.changed.notify_waiters();
        self.gate().notify_original_waiters();
        closing.disarm();
        Ok(())
    }

    pub(crate) async fn take_original_normal_retirement(
        self: &Arc<Self>,
    ) -> Result<OriginalSameActorCQuiescence, AgentdError> {
        let mut closing = self.original_failure_scope();
        loop {
            let changed = self.retirement.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            self.require_original_retirement_identity(self.context.identity(), self.gate())?;
            let taken = {
                let mut state = self.retirement.state.lock().map_err(refused)?;
                match &*state {
                    OriginalLearningRetirementState::Open => None,
                    OriginalLearningRetirementState::Requested(_) => {
                        let OriginalLearningRetirementState::Requested(original) =
                            std::mem::replace(&mut *state, OriginalLearningRetirementState::Taken)
                        else {
                            return Err(refused("original retirement state changed under its lock"));
                        };
                        Some(*original)
                    }
                    _ => return Err(refused("original C retirement capability was already taken")),
                }
            };
            if let Some(original) = taken {
                OriginalSameActorCQuiescence::require_original_phase(
                    &original, self.context.identity(), self.gate(),
                )?;
                OriginalSameActorCQuiescence::require_original_learning_work(&original, self)?;
                closing.disarm();
                return Ok(original);
            }
            tokio::select! {
                _ = changed => {},
                _ = self.gate().cancelled() => {
                    return Err(refused("original phase closed before C retirement"));
                }
                _ = tokio::time::sleep_until(tokio::time::Instant::from_std(
                    self.gate().deadline().instant(),
                )) => return Err(refused("original phase ended before C retirement")),
            }
        }
    }

    pub(crate) fn authorize_original_learning_stop(
        self: &Arc<Self>,
        quiescence: &OriginalSameActorCQuiescence,
        acknowledged: &OriginalDurableLearningAcknowledgement,
    ) -> Result<(), AgentdError> {
        let mut closing = self.original_failure_scope();
        OriginalSameActorCQuiescence::require_original_phase(
            quiescence, self.context.identity(), self.gate(),
        )?;
        OriginalSameActorCQuiescence::require_original_learning_work(quiescence, self)?;
        OriginalDurableLearningAcknowledgement::require_original_work(acknowledged, self)?;
        OriginalSameActorCQuiescence::require_original_learning_snapshot(
            quiescence, acknowledged.snapshot(),
        )?;
        self.require_original_terminal_snapshot(acknowledged.snapshot())?;
        let mut state = self.retirement.state.lock().map_err(refused)?;
        if !matches!(*state, OriginalLearningRetirementState::Taken) {
            return Err(refused("original learning stop was not authorized exactly once"));
        }
        *state = OriginalLearningRetirementState::StopAuthorized(
            Box::new(acknowledged.snapshot().clone()),
        );
        drop(state);
        self.retirement.changed.notify_waiters();
        self.gate().notify_original_waiters();
        closing.disarm();
        Ok(())
    }

    pub(crate) fn original_normal_retirement_change(&self) -> &Notify {
        &self.retirement.changed
    }

    pub(crate) fn take_original_learning_stop(
        self: &Arc<Self>,
    ) -> Result<Option<OriginalLearningStop>, AgentdError> {
        self.require_original_retirement_identity(self.context.identity(), self.gate())?;
        let mut state = self.retirement.state.lock().map_err(|error| {
            self.gate().close();
            refused(error)
        })?;
        if !matches!(*state, OriginalLearningRetirementState::StopAuthorized(_)) {
            return match *state {
                OriginalLearningRetirementState::StopTaken => {
                    self.gate().close();
                    Err(refused("original learning stop was already consumed"))
                }
                _ => Ok(None),
            };
        }
        let OriginalLearningRetirementState::StopAuthorized(snapshot) =
            std::mem::replace(&mut *state, OriginalLearningRetirementState::StopTaken)
        else {
            self.gate().close();
            return Err(refused("original learning stop state changed under its lock"));
        };
        drop(state);
        Ok(Some(OriginalLearningStop { work: Arc::clone(self), snapshot: *snapshot }))
    }

    pub(crate) async fn join_original_normal_work(
        self: &Arc<Self>,
        learning: &crate::learning_iteration::OriginalLearningLoopRetired,
        delivery: &crate::learning_iteration::OriginalLearningDeliveryRetired,
    ) -> Result<OriginalLearningWorkJoined, AgentdError> {
        let mut closing = self.original_failure_scope();
        crate::learning_iteration::OriginalLearningLoopRetired::require_original_work(learning, self)?;
        crate::learning_iteration::OriginalLearningDeliveryRetired::require_original_work(delivery, self)?;
        let result = self.jobs.join_original_normal().await;
        if let Err(error) = result {
            self.gate().close();
            let cleanup = self.close_and_join_original_work().await;
            return Err(refused(match cleanup {
                Ok(()) => error,
                Err(cleanup) => format!("{error}; original fault cleanup: {cleanup}"),
            }));
        }
        self.require_original_retirement_identity(self.context.identity(), self.gate())?;
        crate::learning_iteration::OriginalLearningLoopRetired::require_original_work(learning, self)?;
        crate::learning_iteration::OriginalLearningDeliveryRetired::require_original_work(delivery, self)?;
        closing.disarm();
        Ok(OriginalLearningWorkJoined { work: Arc::clone(self) })
    }
}

impl OriginalLearningStop {
    pub(crate) fn require_original_work(
        &self,
        work: &Arc<OriginalSameActorLearningWork>,
    ) -> Result<(), AgentdError> {
        if !Arc::ptr_eq(&self.work, work) {
            self.work.gate().close();
            work.gate().close();
            return Err(refused("original learning stop belongs to another Work"));
        }
        work.require_original_terminal_snapshot(&self.snapshot)
    }

    pub(crate) fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        &self.snapshot
    }
}

impl OriginalLearningWorkJoined {
    pub(crate) fn require_original_work(
        &self,
        work: &Arc<OriginalSameActorLearningWork>,
    ) -> Result<(), AgentdError> {
        if !Arc::ptr_eq(&self.work, work) {
            self.work.gate().close();
            work.gate().close();
            return Err(refused("original joined work belongs to another phase"));
        }
        work.require_original_retirement_identity(work.context.identity(), work.gate())
    }
}

fn refused(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::GenerationFenced(error.to_string())
}
