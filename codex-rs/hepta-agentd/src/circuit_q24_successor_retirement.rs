//! Normal C retirement is a separate one-shot transition. Only the capability
//! produced by the real C task drain may request the local worker stop; only
//! that worker's actual returned future can create its joined capability.

use super::*;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::OriginalQ24InstalledSuccessorV1;
use crate::circuit_task::OriginalCQuiescenceOrigin;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;

/// The fields never escape as a Direct handle or invocation provider.
pub(crate) struct OriginalRetiredSuccessorOwners {
    _original: Installed,
}

/// No Clone, data constructor or externally supplied result. The original
/// PendingSuccessorOwner creates this only after awaiting its real run future.
pub(crate) struct OriginalSuccessorWorkerJoined {
    closing: CloseSameActorPhaseOnDrop,
    slot_closing: CloseOnDrop,
    slot: Arc<SuccessorSlot>,
    origin: Arc<OriginalCQuiescenceOrigin>,
}

impl SuccessorSlot {
    pub(crate) fn require_original_c_installation(
        &self,
        original: &OriginalQ24InstalledSuccessorV1,
        identity: &AgentdIdentity,
    ) -> Result<(), AgentdError> {
        self.require_open().map_err(retirement_error)?;
        let state = self.state.lock().map_err(retirement_error)?;
        if state.phase != Phase::Ready || self.closed.is_cancelled() {
            return Err(retirement_error("original C slot is not ready"));
        }
        let installed = state.installed.as_ref().ok_or_else(|| {
            retirement_error("original C slot has no actual installed owner")
        })?;
        installed.handle.require_direct_original_handle().map_err(retirement_error)?;
        installed
            .invocation
            .require_original_installed_custody(original, identity)
    }

    pub(crate) fn require_original_retirement_snapshot(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(), AgentdError> {
        self.require_open().map_err(retirement_error)?;
        let state = self.state.lock().map_err(retirement_error)?;
        let original = state.decision.as_ref().ok_or_else(|| {
            retirement_error("original C retirement has no actual decision")
        })?;
        if state.phase != Phase::Ready
            || !state.generation
            || snapshot.request != original.request
            || snapshot.owners != original.owners
            || !snapshot.receipts.starts_with(&original.receipts)
        {
            return Err(retirement_error("original C retirement checkpoint differs"));
        }
        Ok(())
    }

    pub(crate) fn request_original_retirement(
        &self,
        origin: Arc<OriginalCQuiescenceOrigin>,
    ) -> Result<(), AgentdError> {
        origin.require_original_slot(self)?;
        self.require_open().map_err(retirement_error)?;
        let mut state = self.state.lock().map_err(retirement_error)?;
        if state.phase != Phase::Ready
            || state.retirement.is_some()
            || !state.generation
            || self.closed.is_cancelled()
            || self.active.load(Ordering::Acquire) != 0
            || state.installed.as_ref().is_none_or(|owner| owner.handle.pending_count() != 0)
        {
            return Err(retirement_error("original C retirement is not available"));
        }
        state.retirement = Some(origin);
        state.phase = Phase::Retiring;
        drop(state);
        // This is the exact local token already awaited by the original C
        // driver. It is not the common phase Gate or a worker-abort request.
        self.closed.cancel();
        self.changed.send_replace(());
        Ok(())
    }

    pub(in crate::circuit_q24_successor) fn finish_original_retirement_join(
        self: &Arc<Self>,
        identity: &AgentdIdentity,
        gate: &Arc<SameActorPhaseGate>,
        closing: CloseSameActorPhaseOnDrop,
    ) -> Result<OriginalSuccessorWorkerJoined, AgentdError> {
        gate.require_open().map_err(retirement_error)?;
        let origin = {
            let mut state = self.state.lock().map_err(retirement_error)?;
            if state.phase != Phase::Retiring
                || !state.generation
                || !self.closed.is_cancelled()
                || self.active.load(Ordering::Acquire) != 0
                || state.installed.as_ref().is_none_or(|owner| owner.handle.pending_count() != 0)
            {
                return Err(retirement_error("original C worker did not join its retirement"));
            }
            let origin = state.retirement.as_ref().cloned().ok_or_else(|| {
                retirement_error("original C retirement origin is missing")
            })?;
            origin.require_original_binding(identity, gate)?;
            origin.require_original_slot(self.as_ref())?;
            state.phase = Phase::JoinedRetirement;
            origin
        };
        self.changed.send_replace(());
        Ok(OriginalSuccessorWorkerJoined {
            slot: Arc::clone(self),
            origin,
            closing,
            slot_closing: CloseOnDrop::new(self),
        })
    }

    pub(crate) fn require_original_retired_slot(
        &self,
        origin: &Arc<OriginalCQuiescenceOrigin>,
    ) -> Result<(), AgentdError> {
        origin.require_original_slot(self)?;
        let state = self.state.lock().map_err(retirement_error)?;
        if state.phase != Phase::Retired
            || state.installed.is_some()
            || !self.closed.is_cancelled()
            || self.active.load(Ordering::Acquire) != 0
            || !state.retirement.as_ref().is_some_and(|actual| Arc::ptr_eq(actual, origin))
        {
            return Err(retirement_error("original C slot has not been consumed after join"));
        }
        Ok(())
    }
}

impl OriginalSuccessorWorkerJoined {
    pub(crate) fn consume_original_retirement(
        mut self,
        origin: &Arc<OriginalCQuiescenceOrigin>,
    ) -> Result<OriginalRetiredSuccessorOwners, AgentdError> {
        if !Arc::ptr_eq(&self.origin, origin) {
            return Err(retirement_error("original C joined origin differs"));
        }
        origin.require_original_slot(self.slot.as_ref())?;
        let original = {
            let mut state = self.slot.state.lock().map_err(retirement_error)?;
            if state.phase != Phase::JoinedRetirement
                || !self.slot.closed.is_cancelled()
                || self.slot.active.load(Ordering::Acquire) != 0
                || !state.retirement.as_ref().is_some_and(|actual| Arc::ptr_eq(actual, origin))
                || state.installed.as_ref().is_none_or(|owner| owner.handle.pending_count() != 0)
            {
                return Err(retirement_error("original C joined slot is not consumable"));
            }
            let original = state.installed.take().ok_or_else(|| {
                retirement_error("original C joined owner is missing")
            })?;
            state.phase = Phase::Retired;
            original
        };
        self.slot.changed.send_replace(());
        // The consuming C capability already retains its armed common-Gate
        // guard. No await or cancellation gap separates this owner handoff.
        self.slot_closing.disarm();
        self.closing.disarm();
        Ok(OriginalRetiredSuccessorOwners { _original: original })
    }
}

fn retirement_error(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::GenerationFenced(format!("original C retirement: {error}"))
}
