//! Ordinary signed ObjectiveStart → the original bounded Circuit/Cell owner.

use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_automation::AutomationStore;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_types::StableId;

use super::AgentdState;
use super::poisoned_state;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::CircuitTaskErrorV1;
use crate::CircuitTaskReceiptV1;
use crate::CircuitTaskRequestV1;

struct AdmittedTask(Arc<AtomicUsize>);

impl Drop for AdmittedTask {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::AcqRel);
    }
}

/// Host-owned mapping and result consumer for one explicit execution profile.
/// The complete request must be stable across retry and owner restart. This
/// provider cannot submit work directly or manufacture a sealed result.
pub trait AgentdCircuitTaskInvocationProviderV1: Send + Sync {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<CircuitTaskRequestV1, AgentdError>;

    /// Durably publish the original result, idempotently by run/result identity.
    /// A failed ACK leaves the task committed; retry publishes the same verified
    /// receipt without another inference. This observation grants no reward,
    /// training, adoption, signing or external-effect authority.
    fn publish_result(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        receipt: &CircuitTaskReceiptV1,
    ) -> Result<(), AgentdError>;
}

impl AgentdState {
    /// Enable completion delivery only for the explicit learning bootstrap's
    /// sources. Ordinary tasks cannot fill a learning queue by default.
    #[cfg(test)]
    pub(crate) fn attach_circuit_learning_source(
        &self,
        source_run_id: StableId,
    ) -> Result<(), AgentdError> {
        self.attach_circuit_learning_sources(vec![source_run_id])
    }

    pub(crate) fn attach_circuit_learning_sources(
        &self,
        sources: Vec<StableId>,
    ) -> Result<(), AgentdError> {
        if sources.is_empty()
            || sources.len() > crate::learning_iteration::MAX_REGISTERED_CIRCUIT_LEARNING
            || sources.iter().enumerate().any(|(index, source)| sources[..index].contains(source))
        {
            return Err(AgentdError::Invalid("Circuit learning source registry differs".into()));
        }
        self.circuit_learning_source
            .set(sources)
            .map_err(|_| AgentdError::Invalid("Circuit learning source already attached".into()))
    }

    #[cfg(test)]
    pub(crate) fn circuit_learning_source(&self) -> Option<&StableId> {
        self.circuit_learning_sources().first()
    }

    pub(crate) fn circuit_learning_sources(&self) -> &[StableId] {
        self.circuit_learning_source.get().map(Vec::as_slice).unwrap_or_default()
    }

    pub(crate) fn circuit_task_enabled(&self) -> bool {
        self.circuit_task.get().is_some() || self.circuit_task_invocation.get().is_some()
    }

    pub(crate) fn circuit_task_store(&self) -> Result<AutomationStore, AgentdError> {
        self.automation
            .lock()
            .map_err(poisoned_state)?
            .clone()
            .ok_or_else(|| {
                AgentdError::Protocol("Circuit task AutomationStore is unavailable".into())
            })
    }

    pub(crate) fn circuit_task_pending_count(&self) -> usize {
        self.circuit_task_admissions
            .load(Ordering::Acquire)
            .saturating_add(
                self.circuit_task
                    .get()
                    .map_or(0, crate::CircuitTaskHandleV1::pending_count),
            )
    }

    /// Consult durable history even when this process did not enable a Circuit
    /// profile. A restarted owner cannot hide old work by dropping its handle.
    /// Drain callers close admission first. Count active work before opening
    /// the read snapshot so a concurrent late commit cannot disappear between
    /// an older snapshot and the worker dropping its final pending guard.
    pub(crate) async fn circuit_task_drain_blockers(&self) -> Result<u32, AgentdError> {
        let pending = self.circuit_task_pending_count();
        if pending != 0 {
            return u32::try_from(pending).map_err(|_| {
                AgentdError::Protocol("Circuit task pending count exceeds u32".into())
            });
        }
        let store = self.automation.lock().map_err(poisoned_state)?.clone();
        let durable = match store {
            Some(store) => store.circuit_drain_blockers().await.map_err(|error| {
                AgentdError::Protocol(format!("Circuit drain history unavailable: {error}"))
            })?,
            None => {
                return Err(AgentdError::Protocol(
                    "Circuit drain owner is unavailable".into(),
                ));
            }
        };
        let pending = u32::try_from(self.circuit_task_pending_count())
            .map_err(|_| AgentdError::Protocol("Circuit task pending count exceeds u32".into()))?;
        durable
            .checked_add(pending)
            .ok_or_else(|| AgentdError::Protocol("Circuit drain blocker count overflow".into()))
    }

    pub(crate) async fn execute_circuit_task_record(
        &self,
        record: &RunStartRecordV1,
    ) -> Result<Option<CircuitTaskReceiptV1>, AgentdError> {
        let (handle, provider) = match (self.circuit_task.get(), self.circuit_task_invocation.get())
        {
            (None, None) => return Ok(None),
            (Some(handle), Some(provider)) => (handle, provider),
            _ => {
                return Err(AgentdError::Protocol(
                    "incomplete Circuit task profile".into(),
                ));
            }
        };
        self.require_current_run_start(record)?;
        let _admitted = {
            // Serialize the entire ingress lifetime against admission close.
            // The worker's pending guard overlaps this guard and survives a
            // cancelled caller; this one also covers result publication.
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            if !runtime.admission_open
                || runtime.fenced
                || runtime.lifecycle != codex_hepta_fleet::AgentLifecycle::Running
                || runtime.current_generation != record.snapshot.generation
            {
                return Err(AgentdError::GenerationFenced(
                    "Circuit task admission closed".into(),
                ));
            }
            self.circuit_task_admissions.fetch_add(1, Ordering::AcqRel);
            AdmittedTask(Arc::clone(&self.circuit_task_admissions))
        };
        let request = provider.build(self.identity(), record)?;
        request
            .validate_record(record, record.snapshot.generation)
            .map_err(task_error)?;
        self.require_current_run_start(record)?;
        let receipt = match handle.submit(request.clone(), record.clone()).await {
            Err(CircuitTaskErrorV1::CommitUncertain) => {
                // Observation only: never resubmit computation after ACK loss.
                self.require_current_run_start(record)?;
                handle
                    .readback(request, record.clone())
                    .await
                    .map_err(task_error)?
            }
            result => result.map_err(task_error)?,
        };
        if receipt.trace().run().outcome().is_none() || receipt.trace().run().unresolved() != 0 {
            return Err(task_error(CircuitTaskErrorV1::ReconciliationRequired));
        }
        self.require_current_run_start(record)?;
        provider.publish_result(self.identity(), record, &receipt)?;
        self.require_current_run_start(record)?;
        // Only explicitly registered iteration sources enter the outbox.
        // This also runs on its completed-task readback path after ACK loss.
        if self
            .circuit_learning_sources()
            .iter()
            .any(|source| source.as_str() == record.snapshot.run_id.as_str())
        {
            let objective = codex_hepta_contracts::Sha256Digest::parse(
                record.snapshot.objective_digest.to_string(),
            )
            .map_err(|error| {
                AgentdError::Protocol(format!("Circuit learning objective: {error}"))
            })?;
            self.circuit_task_store()?
                .enqueue_circuit_learning(receipt.trace(), objective)
                .await
                .map_err(|error| {
                    AgentdError::Protocol(format!("Circuit learning outbox: {error:?}"))
                })?;
        }
        self.require_current_run_start(record)?;
        Ok(Some(receipt))
    }
}

fn task_error(error: CircuitTaskErrorV1) -> AgentdError {
    AgentdError::Protocol(format!("Circuit task execution failed: {error}"))
}
