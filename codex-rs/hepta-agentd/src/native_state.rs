//! Native execution reads the same Fleet fence and Agentd run coordinator.

use std::sync::Arc;
use std::sync::Weak;
use std::sync::atomic::Ordering;

use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_memory::ProductionDispatchRequest;
use codex_hepta_memory::ProductionWriterError;

use crate::AgentdError;
use crate::RunPhase;
use crate::RunReceipt;

use super::AgentdState;
use super::poisoned_state;
use super::run_error;
use super::unix_now_ms;
use super::run_lifecycle;

/// A borrowed view of the original control owner, with no independent run map.
pub(crate) struct NativeEntryGate {
    pub(crate) state: Weak<AgentdState>,
    pub(crate) policy_generation: u64,
}

impl NativeEntryGate {
    pub(crate) fn state(&self) -> Result<Arc<AgentdState>, AgentdError> {
        self.state.upgrade().ok_or_else(|| AgentdError::GenerationFenced("original Agentd owner stopped".to_owned()))
    }

    /// Called only after the per-turn admission has matched the request's
    /// immutable scope and lease. The run never comes from the owner subject.
    pub(crate) fn enter_original(&self, request: &ProductionDispatchRequest, run_id: &str, generation: u64,
        dispatched_revision: u64, enter: &mut dyn FnMut() -> Result<(), ProductionWriterError>) -> Result<Box<dyn Send>, ProductionWriterError> {
        let state = self.state().map_err(|error| ProductionWriterError::AuthorityRejected(error.to_string()))?;
        if request.operation_policy_generation != self.policy_generation
            || request.operation_subject_id != state.identity.agent_id.as_str() {
            return Err(ProductionWriterError::AuthorityRejected("native operation owner or policy changed".to_owned()));
        }
        let fleet_entry = state.registry.try_enter_generation(&state.identity.agent_id, generation)
            .map_err(|error| ProductionWriterError::AuthorityRejected(error.to_string()))?;
        state.with_native_effect(run_id, |original| {
            if original.generation != generation || original.revision != dispatched_revision {
                return Err(ProductionWriterError::AuthorityRejected("native original run generation or dispatch revision changed".to_owned()));
            }
            enter()
        })?;
        // FinalUse was consumed under the original runtime/run locks. A
        // later cancellation observes a dispatched attempt, never a fresh one.
        // The writer retains its own lease through transport admission.
        // The same Fleet inode excludes supervisor publication until the
        // existing bounded transport-entry guard is dropped.
        Ok(Box::new((state, fleet_entry)))
    }
}

pub(crate) struct NativeActiveTurn(Arc<AgentdState>);

impl Drop for NativeActiveTurn {
    fn drop(&mut self) { self.0.native_active_turns.fetch_sub(1, Ordering::AcqRel); }
}

impl AgentdState {
    pub(crate) fn native_run_snapshot(&self, run_id: &str) -> Result<crate::RunSnapshot, AgentdError> {
        self.runs.lock().map_err(poisoned_state)?.run_snapshot(run_id)
            .ok_or_else(|| AgentdError::Invalid("native handoff has no original Agentd run".to_owned()))
    }

    pub(crate) fn native_recovery_record(&self, run_id: &str) -> Result<crate::RunRecovery, AgentdError> {
        self.runs.lock().map_err(poisoned_state)?.recovery_record(run_id).map_err(run_error)
    }

    pub(crate) fn restore_native_run(&self, recovery: crate::RunRecovery) -> Result<RunReceipt, AgentdError> {
        self.with_original_run_journal(|journal| {
            let run_id = codex_hepta_types::StableId::new(&recovery.snapshot.run_id).map_err(run_lifecycle::lifecycle_error)?;
            let (cancellation, closed) = match journal.as_deref() {
                Some(journal) => {
                    let cancellation = journal.cancellation(&run_id).map_err(run_lifecycle::lifecycle_error)?;
                    let closed = journal.closed(&run_id).map_err(run_lifecycle::lifecycle_error)?;
                    if cancellation.is_some() || closed.is_some() {
                        let original = journal.get(&run_id).map_err(run_lifecycle::lifecycle_error)?
                            .ok_or_else(|| run_lifecycle::lifecycle_error("lifecycle fact lost its original RunStart"))?;
                        crate::canonical_queued_input::verify_admitted_record(original, &recovery.snapshot)
                            .map_err(run_lifecycle::lifecycle_error)?;
                    }
                    (cancellation, closed)
                }
                None => (None, None),
            };
            // Journal facts retain cancellation and the highest original
            // terminal revision. They never rewrite the immutable checkpoint.
            self.runs.lock().map_err(poisoned_state)?
                .restore_original_observation(recovery, cancellation, closed).map_err(run_error)
        })
    }

    pub(crate) fn native_observation_cancelled(&self, run_id: &str) -> Result<bool, AgentdError> {
        // Closing fresh admission does not cancel observer-only recovery. An
        // explicit cancellation or deadline still applies to the original run.
        let run = self.native_run_receipt(run_id)?;
        Ok(matches!(run.phase, RunPhase::Cancelling | RunPhase::Cancelled)
            || run.cancel_reason.is_some() || run.deadline_ms <= unix_now_ms()?)
    }

    pub(crate) fn native_run_receipt(&self, run_id: &str) -> Result<RunReceipt, AgentdError> {
        self.runs.lock().map_err(poisoned_state)?.run(run_id)
            .ok_or_else(|| AgentdError::Invalid("native handoff has no original Agentd run".to_owned()))
    }

    pub(crate) fn require_native_effect(&self, run_id: &str) -> Result<RunReceipt, AgentdError> {
        self.with_native_effect(run_id, |receipt| Ok(receipt.clone()))
            .map_err(|error| AgentdError::GenerationFenced(error.to_string()))
    }

    fn with_native_effect<T>(&self, run_id: &str, enter: impl FnOnce(&RunReceipt) -> Result<T, ProductionWriterError>) -> Result<T, ProductionWriterError> {
        let rejected = |error: AgentdError| ProductionWriterError::AuthorityRejected(error.to_string());
        self.refresh_generation().inspect_err(|_| self.mark_fenced()).map_err(rejected)?;
        // Fetch the immutable signed record before taking runtime/runs locks;
        // journal admission uses its own lock order. No second registry is kept.
        let objective = if self.native_objective_executor.get().is_some() {
            Some(self.objective_runtime.get().ok_or_else(||
                ProductionWriterError::AuthorityRejected("original Objective owner missing at native entry".to_owned()))?
                .original_record(run_id).map_err(rejected)?)
        } else { None };
        self.with_original_run_journal(|journal| {
            run_lifecycle::require_fresh(journal.as_deref(), run_id)?;
            Ok((|| {
        let runtime = self.runtime.lock().map_err(poisoned_state).map_err(rejected)?;
        if runtime.lifecycle != AgentLifecycle::Running || runtime.fenced
            || !runtime.app_server_ready || !runtime.critical_stores_ready
            || !runtime.revocation_ready || !runtime.required_ports_ready || !runtime.admission_open {
            return Err(ProductionWriterError::AuthorityRejected("native effects require the original ready Running owner".to_owned()));
        }
        let runs = self.runs.lock().map_err(poisoned_state).map_err(rejected)?;
        let receipt = runs.run(run_id).ok_or_else(|| ProductionWriterError::AuthorityRejected("original native run missing".to_owned()))?;
        let now_ms = unix_now_ms().map_err(rejected)?;
        if receipt.generation != runtime.current_generation || receipt.phase != RunPhase::Dispatched
            || receipt.cancel_reason.is_some() || receipt.deadline_ms <= now_ms {
            return Err(ProductionWriterError::AuthorityRejected("native original turn is cancelled, expired, or stale".to_owned()));
        }
        if let Some(objective) = objective {
            let snapshot = runs.run_snapshot(run_id).ok_or_else(||
                ProductionWriterError::AuthorityRejected("original native snapshot missing".to_owned()))?;
            crate::canonical_queued_input::verify_admitted_record(&objective, &snapshot)
                .map_err(|error| ProductionWriterError::AuthorityRejected(error.to_string()))?;
            self.authenticate_current_run_start(&objective, runtime.current_generation, now_ms).map_err(rejected)?;
        }
        // Both original owner locks span the actual one-shot consume. They are
        // released before asynchronous transport, never while merely checking.
        enter(&receipt)
            })())
        }).map_err(rejected)?
    }

    /// A native handoff consumes the already admitted/context-attached run. It
    /// cannot create a run from a checkpoint or regenerate its original ids.
    pub(crate) fn dispatch_native_run(self: &Arc<Self>, original: &RunReceipt) -> Result<NativeActiveTurn, AgentdError> {
        self.refresh_generation()?;
        self.with_fresh_original_run(&original.run_id, || {
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            if runtime.lifecycle != AgentLifecycle::Running || !runtime.admission_open || runtime.fenced
                || original.generation != runtime.current_generation {
                return Err(AgentdError::GenerationFenced("native handoff owner is not ready".to_owned()));
            }
            let mut runs = self.runs.lock().map_err(poisoned_state)?;
            let current = runs.run(&original.run_id).ok_or_else(|| AgentdError::Invalid("original run missing".to_owned()))?;
            if current != *original || current.phase != RunPhase::ContextAttached {
                return Err(AgentdError::Invalid("native handoff must match the original context-attached receipt".to_owned()));
            }
            runs.mark_dispatched(unix_now_ms()?, &original.run_id, original.revision).map_err(run_error)?;
            Ok(())
        })?;
        self.native_active_turns.fetch_add(1, Ordering::AcqRel);
        Ok(NativeActiveTurn(Arc::clone(self)))
    }

    pub(crate) fn track_native_recovery(self: &Arc<Self>, run_id: &str) -> Result<NativeActiveTurn, AgentdError> {
        let receipt = self.native_run_receipt(run_id)?;
        if !matches!(receipt.phase, RunPhase::Dispatched | RunPhase::Cancelling | RunPhase::Indeterminate) {
            return Err(AgentdError::Invalid("native recovery requires the original unresolved run".to_owned()));
        }
        self.native_active_turns.fetch_add(1, Ordering::AcqRel);
        Ok(NativeActiveTurn(Arc::clone(self)))
    }

    /// Terminal original runs can still reconcile their saved physical
    /// operations; this tracking guard grants no fresh dispatch permission.
    pub(crate) fn track_native_observation(self: &Arc<Self>, run_id: &str) -> Result<NativeActiveTurn, AgentdError> {
        let receipt = self.native_run_receipt(run_id)?;
        if matches!(receipt.phase, RunPhase::Admitted | RunPhase::ContextAttached) {
            return Err(AgentdError::Invalid("native observation requires an original dispatched run".to_owned()));
        }
        self.native_active_turns.fetch_add(1, Ordering::AcqRel);
        Ok(NativeActiveTurn(Arc::clone(self)))
    }

    // Fixture-only direct owner observation. Production workers must carry
    // their own original revision through the checked methods below.
    #[cfg(test)]
    pub(crate) fn observe_native_run(&self, run_id: &str, phase: RunPhase) -> Result<RunReceipt, AgentdError> {
        let mut runs = self.runs.lock().map_err(poisoned_state)?;
        let current = runs.run(run_id).ok_or_else(|| AgentdError::Invalid("native original run missing".to_owned()))?;
        runs.observe_terminal(run_id, current.revision, phase, phase != RunPhase::Indeterminate).map_err(run_error)
    }

    /// Abandon only this actual dispatched attempt. A stale guard cannot
    /// downgrade a successor that reused the same logical run identity.
    pub(crate) fn abandon_native_run(&self, run_id: &str, dispatched_revision: u64) -> Result<(), AgentdError> {
        self.with_original_run_journal(|journal| {
            let mut runs = self.runs.lock().map_err(poisoned_state)?;
            let current = runs.run(run_id).ok_or_else(|| AgentdError::Invalid("native original run missing".to_owned()))?;
            if owns_native_revision(&current, dispatched_revision) {
                let receipt = runs.observe_terminal(run_id, current.revision, RunPhase::Indeterminate, false).map_err(run_error)?;
                run_lifecycle::persist(journal, &receipt)?;
            }
            Ok(())
        })
    }

    pub(crate) fn observe_native_run_at_revision(&self, run_id: &str, dispatched_revision: u64,
        phase: RunPhase) -> Result<RunReceipt, AgentdError> {
        self.with_original_run_journal(|journal| {
            let mut runs = self.runs.lock().map_err(poisoned_state)?;
            let current = runs.run(run_id).ok_or_else(|| AgentdError::Invalid("native original run missing".to_owned()))?;
            if !owns_native_revision(&current, dispatched_revision) {
                return Err(AgentdError::GenerationFenced("original native execution revision was replaced".to_owned()));
            }
            let receipt = runs.observe_terminal(run_id, current.revision, phase, phase != RunPhase::Indeterminate).map_err(run_error)?;
            run_lifecycle::persist(journal, &receipt)?;
            Ok(receipt)
        })
    }

    pub(crate) fn observe_native_recovery(&self, run_id: &str, expected_revision: u64,
        phase: RunPhase) -> Result<RunReceipt, AgentdError> {
        self.with_original_run_journal(|journal| {
            let mut runs = self.runs.lock().map_err(poisoned_state)?;
            let current = runs.run(run_id).ok_or_else(|| AgentdError::Invalid("native original run missing".to_owned()))?;
            if current.revision != expected_revision {
                return Err(AgentdError::GenerationFenced("original observation cannot replace a live continuation".to_owned()));
            }
            if matches!(current.phase, RunPhase::Cancelled | RunPhase::Succeeded | RunPhase::Failed) {
                // Reconcile old physical results without replacing an already
                // durable overall decision or advancing its original revision.
                run_lifecycle::persist(journal, &current)?;
                return Ok(current);
            }
            if !matches!(current.phase, RunPhase::Indeterminate | RunPhase::Cancelling) {
                return Err(AgentdError::GenerationFenced("original observation cannot replace a live continuation".to_owned()));
            }
            let receipt = runs.observe_terminal(run_id, current.revision, phase, phase != RunPhase::Indeterminate).map_err(run_error)?;
            run_lifecycle::persist(journal, &receipt)?;
            Ok(receipt)
        })
    }
}

fn owns_native_revision(current: &RunReceipt, dispatched_revision: u64) -> bool {
    (current.phase == RunPhase::Dispatched && current.revision == dispatched_revision)
        // The one original cancellation transition belongs to this attempt.
        // A rearmed successor is at least one further revision away.
        || (current.phase == RunPhase::Cancelling && current.cancel_reason.is_some()
            && dispatched_revision.checked_add(1) == Some(current.revision))
}
