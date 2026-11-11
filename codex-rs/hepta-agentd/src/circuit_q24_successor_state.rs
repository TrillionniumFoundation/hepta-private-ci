//! Finite waiting state; queued ordinary tasks are never carried across install.
//! Installation remains a drain blocker after cancellation until its worker joins.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use tokio::sync::watch;
use tokio_util::sync::CancellationToken;

use crate::CircuitTaskErrorV1;
use crate::CircuitTaskHandleV1;
use crate::DurableCircuitTaskSourceV1;
use crate::LearningIterationRuntimeErrorV1 as LearningError;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Phase { Pending, Installing, Ready, Closed }

struct Installed {
    handle: CircuitTaskHandleV1,
    invocation: Arc<DurableCircuitTaskSourceV1<FileAnchorWitnessStore>>,
}

struct State {
    phase: Phase,
    decision: Option<LearningIterationSnapshotV1>,
    installed: Option<Installed>,
    generation: bool,
}

pub(crate) struct SuccessorSlot {
    state: Mutex<State>,
    changed: watch::Sender<()>,
    pub(super) closed: CancellationToken,
    active: Arc<AtomicUsize>,
}

pub(super) struct CloseOnDrop {
    pub(super) slot: Arc<SuccessorSlot>,
    armed: bool,
}
impl CloseOnDrop {
    pub(super) fn new(slot: &Arc<SuccessorSlot>) -> Self {
        Self { slot: Arc::clone(slot), armed: true }
    }
    pub(super) fn disarm(&mut self) { self.armed = false; }
}
impl Drop for CloseOnDrop {
    fn drop(&mut self) { if self.armed { self.slot.close(); } }
}

pub(super) struct InstallationWork(Arc<AtomicUsize>);
impl Drop for InstallationWork {
    fn drop(&mut self) { self.0.fetch_sub(1, Ordering::AcqRel); }
}

impl SuccessorSlot {
    pub(crate) fn new_pending_slot() -> Arc<Self> {
        Arc::new(Self {
            state: Mutex::new(State { phase: Phase::Pending, decision: None, installed: None, generation: false }),
            changed: watch::channel(()).0,
            closed: CancellationToken::new(),
            active: Arc::new(AtomicUsize::new(/*value*/ 0)),
        })
    }

    pub(crate) fn close(&self) {
        self.closed.cancel();
        if let Ok(mut state) = self.state.lock() { state.phase = Phase::Closed; }
        self.changed.send_replace(());
    }

    pub(super) fn require_open(&self) -> Result<(), CircuitTaskErrorV1> {
        if self.closed.is_cancelled() { return Err(CircuitTaskErrorV1::Unavailable); }
        Ok(())
    }

    /// The same worker-owned slot is checked inside the original owner lane,
    /// immediately before a new effect. Cancellation never starts deferred work.
    pub(crate) fn require_installation_open(&self) -> Result<(), CircuitTaskErrorV1> {
        self.require_open()?;
        let state = self.state.lock().map_err(|_| CircuitTaskErrorV1::Unavailable)?;
        if state.phase != Phase::Installing || self.closed.is_cancelled() {
            return Err(CircuitTaskErrorV1::Unavailable);
        }
        Ok(())
    }

    pub(super) fn begin_installation(&self) -> Result<InstallationWork, CircuitTaskErrorV1> {
        self.require_open()?;
        let mut state = self.state.lock().map_err(|_| CircuitTaskErrorV1::Unavailable)?;
        if state.phase != Phase::Pending || state.decision.is_none() || self.closed.is_cancelled() {
            drop(state);
            self.close();
            return Err(CircuitTaskErrorV1::Unavailable);
        }
        state.phase = Phase::Installing;
        self.active.fetch_add(1, Ordering::AcqRel);
        Ok(InstallationWork(Arc::clone(&self.active)))
    }

    pub(super) fn install_original_owner(
        &self,
        handle: CircuitTaskHandleV1,
        invocation: Arc<DurableCircuitTaskSourceV1<FileAnchorWitnessStore>>,
    ) -> Result<(), CircuitTaskErrorV1> {
        self.require_open()?;
        handle.require_direct_original_handle()?;
        let mut state = self.state.lock().map_err(|_| CircuitTaskErrorV1::Unavailable)?;
        if state.phase != Phase::Installing || state.installed.is_some() || self.closed.is_cancelled() {
            drop(state);
            self.close();
            return Err(CircuitTaskErrorV1::Unavailable);
        }
        state.installed = Some(Installed { handle, invocation });
        state.phase = Phase::Ready;
        self.changed.send_replace(());
        Ok(())
    }

    pub(crate) fn actual_handle(&self) -> Result<CircuitTaskHandleV1, CircuitTaskErrorV1> {
        self.require_open()?;
        let state = self.state.lock().map_err(|_| CircuitTaskErrorV1::Unavailable)?;
        if state.phase != Phase::Ready { return Err(CircuitTaskErrorV1::Unavailable); }
        Ok(state.installed.as_ref().ok_or(CircuitTaskErrorV1::Unavailable)?.handle.clone())
    }

    pub(super) fn actual_invocation(&self) -> Result<Arc<DurableCircuitTaskSourceV1<FileAnchorWitnessStore>>, CircuitTaskErrorV1> {
        self.require_open()?;
        let state = self.state.lock().map_err(|_| CircuitTaskErrorV1::Unavailable)?;
        if state.phase != Phase::Ready { return Err(CircuitTaskErrorV1::Unavailable); }
        Ok(Arc::clone(&state.installed.as_ref().ok_or(CircuitTaskErrorV1::Unavailable)?.invocation))
    }

    pub(crate) fn pending_count(&self) -> usize {
        let active = self.active.load(Ordering::Acquire);
        // Closing does not discard the actual handle or hide its in-flight work.
        match self.state.lock() {
            Ok(state) => active.saturating_add(state.installed.as_ref().map_or(0, |owner| owner.handle.pending_count())),
            Err(_) => active.max(1),
        }
    }

    pub(super) fn require_decision(&self, expected: &LearningIterationSnapshotV1) -> Result<(), LearningError> {
        self.require_open().map_err(|_| LearningError::Unavailable)?;
        let state = self.state.lock().map_err(|_| LearningError::Unavailable)?;
        if state.decision.as_ref() != Some(expected) { return Err(LearningError::WrongScope); }
        Ok(())
    }

    pub(super) async fn decision(&self, expiry: u64) -> Result<LearningIterationSnapshotV1, LearningError> {
        let mut changes = self.changed.subscribe();
        loop {
            self.require_open().map_err(|_| LearningError::Unavailable)?;
            if let Some(snapshot) = self.state.lock().map_err(|_| LearningError::Unavailable)?.decision.clone() { return Ok(snapshot); }
            tokio::select! {
                _ = self.closed.cancelled() => return Err(LearningError::Unavailable),
                result = tokio::time::timeout(remaining(expiry)?, changes.changed()) => {
                    result.map_err(|_| LearningError::DeadlineExceeded)?.map_err(|_| LearningError::Unavailable)?;
                }
            }
        }
    }

    pub(crate) async fn wait_original_generation(
        self: &Arc<Self>,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(), LearningError> {
        let mut close = CloseOnDrop::new(self);
        let mut changes = self.changed.subscribe();
        {
            let mut state = self.state.lock().map_err(|_| LearningError::Unavailable)?;
            if let Some(original) = &state.decision {
                if snapshot.request != original.request || snapshot.owners != original.owners
                    || !snapshot.receipts.starts_with(&original.receipts)
                { return Err(LearningError::WrongScope); }
            } else { state.decision = Some(snapshot.clone()); }
        }
        self.changed.send_replace(());
        loop {
            self.require_open().map_err(|_| LearningError::Unavailable)?;
            remaining(snapshot.request.envelope.expiry_unix_seconds)?;
            if self.state.lock().map_err(|_| LearningError::Unavailable)?.generation {
                close.disarm();
                return Ok(());
            }
            tokio::select! {
                _ = self.closed.cancelled() => return Err(LearningError::Unavailable),
                result = tokio::time::timeout(remaining(snapshot.request.envelope.expiry_unix_seconds)?, changes.changed()) => {
                    result.map_err(|_| LearningError::DeadlineExceeded)?.map_err(|_| LearningError::Unavailable)?;
                }
            }
        }
    }

    pub(crate) fn original_generation_installed(&self, snapshot: &LearningIterationSnapshotV1) -> Result<(), LearningError> {
        self.require_open().map_err(|_| LearningError::Unavailable)?;
        let mut state = self.state.lock().map_err(|_| LearningError::Unavailable)?;
        let original = state.decision.as_ref().ok_or(LearningError::WrongScope)?;
        if state.phase != Phase::Ready || state.generation || snapshot.request != original.request
            || snapshot.owners != original.owners || !snapshot.receipts.starts_with(&original.receipts)
        {
            drop(state);
            self.close();
            return Err(LearningError::WrongScope);
        }
        state.generation = true;
        self.changed.send_replace(());
        Ok(())
    }
}

#[cfg(test)]
#[path = "circuit_q24_successor_state_tests.rs"]
mod tests;

pub(super) fn remaining(expiry: u64) -> Result<Duration, LearningError> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH).map_err(|_| LearningError::Unavailable)?;
    Duration::from_secs(expiry).checked_sub(now).filter(|remaining| !remaining.is_zero())
        .ok_or(LearningError::DeadlineExceeded)
}
