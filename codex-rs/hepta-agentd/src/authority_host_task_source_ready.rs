//! A private, single-task scheduling hint. It never authenticates completion.
//! Every notification follows the original same-Task/Cell/Source read; every
//! recipient performs its own current read before any Source data is accepted.

use std::sync::{Condvar, Mutex};
use std::time::Instant;
use codex_hepta_neuron::AnchorWitnessStore;
use crate::{AgentdError, OriginalRootCircuitTaskCustodyV1};
use super::{PreparedRootHostCircuitTaskV1, invalid};

enum State { Waiting, Observed }

/// One latch belongs to the concrete Root task and its once-exported reader.
/// The state is only a wake-up hint, not a cached Source publication or grant.
pub(super) struct Hint { state: Mutex<State>, changed: Condvar }

impl Hint {
    pub(super) fn new() -> Self {
        Self { state: Mutex::new(State::Waiting), changed: Condvar::new() }
    }

    fn observed(&self) -> Result<(), AgentdError> {
        let mut state = self.state.lock().map_err(|_| invalid("Source hint poisoned"))?;
        *state = State::Observed;
        self.changed.notify_one();
        Ok(())
    }

    pub(super) fn wait_original(&self, end: Instant) -> Result<(), AgentdError> {
        let state = self.state.lock().map_err(|_| invalid("Source hint poisoned"))?;
        if matches!(*state, State::Observed) {
            return require_before(end);
        }
        let remaining = end.checked_duration_since(Instant::now())
            .filter(|value| !value.is_zero())
            .ok_or_else(|| invalid("the original Source startup expired"))?;
        // A spurious wake-up is a refusal, not a retry or a fresh time window.
        // No Source, Cell, Current, issuer or lease lock spans this wait.
        let (state, result) = self.changed.wait_timeout(state, remaining)
            .map_err(|_| invalid("Source hint poisoned"))?;
        if result.timed_out() || !matches!(*state, State::Observed) {
            return Err(invalid("the original Source publication was not observed"));
        }
        require_before(end)
    }
}

impl<SW, CW> PreparedRootHostCircuitTaskV1<SW, CW>
where SW: AnchorWitnessStore + Send + 'static, CW: AnchorWitnessStore + Send + 'static,
{
    /// Only the fixed task service calls this after its successful original
    /// publication path. A fresh same-Arc read is required before waking the
    /// private Material observer; no caller can set readiness from a digest.
    pub(crate) fn observe_original_root_source_publication(&self) -> Result<(), AgentdError> {
        PreparedRootHostCircuitTaskV1::read_original_root_task_generation(self)?;
        OriginalRootCircuitTaskCustodyV1::require_original_completed_source(&self.custody)?;
        PreparedRootHostCircuitTaskV1::read_original_root_task_generation(self)?;
        self.source_ready.observed()
    }
}

fn require_before(end: Instant) -> Result<(), AgentdError> {
    if Instant::now() >= end { return Err(invalid("the original Source startup expired")); }
    Ok(())
}

#[cfg(test)]
#[path = "authority_host_task_source_ready_tests.rs"]
mod tests;
