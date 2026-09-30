//! Constructor recovery faults deny serving and mutation without dropping any
//! acquired process owner. This local denial is reconstructed from persistent
//! evidence; it does not replace an intent, lease, or exact exit witness.

use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentRecord;

use crate::ManagedProcess;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::bounded_message;
use crate::signed_intent::SignedIntentStatus;

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn recovery_control_fault_is_retryable(
        slot: &AgentSlot<D::Process>,
        error: &SupervisorError,
    ) -> bool {
        matches!(error, SupervisorError::Driver { .. })
            && slot.pending_control.is_some_and(|pending| {
                slot.runtime
                    .as_ref()
                    .is_some_and(|runtime| pending.applies_to(runtime))
            })
    }

    pub(super) fn ensure_mutation_admitted(
        &self,
        agent_id: &AgentId,
    ) -> Result<(), SupervisorError> {
        self.ensure_recovery_unblocked(agent_id)?;
        if self.slots.get(agent_id).is_some_and(|slot| {
            slot.signed_intent
                .as_ref()
                .is_some_and(|intent| intent.status == SignedIntentStatus::RecoveryRequired)
        }) {
            return Err(SupervisorError::SignedIntentRecoveryRequired(
                agent_id.clone(),
            ));
        }
        Ok(())
    }

    pub(super) fn ensure_recovery_unblocked(
        &self,
        agent_id: &AgentId,
    ) -> Result<(), SupervisorError> {
        let slot = self
            .slots
            .get(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
        if let Some(reason) = &slot.recovery_blocker {
            return Err(SupervisorError::Invalid(format!(
                "agent {agent_id} requires durable recovery before mutation: {reason}"
            )));
        }
        Ok(())
    }

    pub(super) fn validate_durable_recovery(
        &self,
        agent_id: &AgentId,
        record: &AgentRecord,
    ) -> Vec<SupervisorError> {
        let root = record.layout.run_root();
        // Read every safety-critical codec before effectful restoration. A
        // broken restart record must not conceal a broken signed/release record.
        [
            crate::restart_budget::pending_restart(root, self.config.restart_max_attempts)
                .map(|_| ())
                .map_err(|error| SupervisorError::Invalid(error.to_string())),
            crate::restart_journal::read_restart_journal(root).and_then(|journal| {
                if journal.is_some_and(|journal| journal.agent_id != *agent_id) {
                    return Err(SupervisorError::CorruptLease(
                        "restart budget journal belongs to another Agent".to_string(),
                    ));
                }
                Ok(())
            }),
            crate::restart_lineage::validate_recovery(root, agent_id)
                .map_err(|error| SupervisorError::Invalid(error.to_string())),
            crate::release_transaction::read_release_transaction(root)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))
                .and_then(|transaction| {
                    if transaction
                        .is_some_and(|transaction| transaction.agent_id != agent_id.to_string())
                    {
                        return Err(SupervisorError::Invalid(
                            "release transaction agent binding mismatch".to_string(),
                        ));
                    }
                    Ok(())
                }),
            crate::signed_intent::read_intent(root)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))
                .and_then(|intent| {
                    if intent.is_some_and(|intent| intent.agent_id != agent_id.to_string()) {
                        return Err(SupervisorError::Invalid(
                            "signed supervisor intent agent binding mismatch".to_string(),
                        ));
                    }
                    Ok(())
                }),
        ]
        .into_iter()
        .filter_map(Result::err)
        .collect()
    }

    pub(super) fn deny_failed_recovery(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        error: &SupervisorError,
        now: Instant,
    ) {
        slot.recovery_blocker
            .get_or_insert_with(|| bounded_message(error.to_string()));
        slot.pending_control = None;
        slot.deferred_agent_action = None;
        slot.restart_pending = false;
        slot.restart_not_before = None;
        slot.matrix.restart_after_exit = false;
        slot.matrix.retry_at = None;
        if let Some(runtime) = slot.runtime.as_mut() {
            // Recovery may already have attempted containment after acquiring
            // this exact handle. Retain a failed attempt for the next tick;
            // another constructor fault is not another control operation.
            let containment_attempted = runtime.fenced;
            runtime.healthy = false;
            runtime.fenced = true;
            if !containment_attempted && !matches!(runtime.phase, RuntimePhase::Killing) {
                runtime.phase = RuntimePhase::Stopping { deadline: now };
                let generation = runtime.generation;
                match runtime.process.kill() {
                    Ok(()) => {
                        runtime.phase = RuntimePhase::Killing;
                        slot.event(generation, SupervisorEventKind::KillRequested);
                    }
                    Err(fault) => slot.event(
                        generation,
                        SupervisorEventKind::DriverFault(bounded_message(fault.to_string())),
                    ),
                }
            }
        }
        // Collect independently: a failed main kill cannot skip the already
        // owned companion, and a failed kill never drops either exact handle.
        if slot
            .matrix
            .runtime
            .as_ref()
            .is_some_and(|runtime| !runtime.fenced)
            && let Err(fault) = self.kill_matrix_now(agent_id, slot)
        {
            slot.event(
                0,
                SupervisorEventKind::DriverFault(bounded_message(fault.to_string())),
            );
        }
    }
}
