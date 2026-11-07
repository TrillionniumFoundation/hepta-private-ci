//! Cold PQ recovery consumes externally retained history. A local status,
//! transaction or release-state hash cannot promote an operation to completed.
use crate::ManagedProcess;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::read_intent;
use crate::signed_intent::read_recovery_directive;
use crate::signed_intent_recovery::ProcessRecoveryStatus;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentRecord;

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn recover_current_signed_intent(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        process_recovery: ProcessRecoveryStatus,
    ) -> Result<(), SupervisorError> {
        let intent = match read_intent(record.layout.run_root()) {
            Ok(intent) => intent,
            Err(error) => {
                slot.intent_publication_fenced = true;
                self.contain_signed_intent_processes(agent_id, slot)?;
                return Err(SupervisorError::Invalid(error.to_string()));
            }
        };
        slot.signed_intent = intent.clone();
        let mut history = if self.registry.is_release_intent_reconciliation() {
            None
        } else {
            self.registry.observe_release_intent_history(agent_id).ok()
        };
        let exact = history.as_ref().is_some_and(|history| {
            crate::signed_intent_anchor::check_previous(
                history.observed_anchor(),
                intent.as_ref(),
                record,
            )
            .is_ok()
        });
        if exact
            && intent.as_ref().is_none_or(|intent| {
                matches!(
                    intent.status,
                    SignedIntentStatus::Committed | SignedIntentStatus::RolledBack
                ) || intent.status == SignedIntentStatus::Aborted && !intent.requires_recovery()
            })
        {
            slot.intent_publication_fenced = false;
            return Ok(());
        }
        // An unavailable frontier, a local rollback, or an unconfirmed CAS is
        // not absence. Preserve both snapshots for an explicit current ceremony.
        slot.intent_publication_fenced = true;
        let Some(intent) = intent else {
            drop(history);
            return self.contain_signed_intent_processes(agent_id, slot);
        };
        if intent.agent_id != agent_id.as_str() {
            drop(history);
            self.contain_signed_intent_processes(agent_id, slot)?;
            return Err(SupervisorError::Invalid(
                "signed intent agent differs from its owner".to_string(),
            ));
        }
        let mut recovery = intent.clone();
        if exact
            && matches!(
                intent.status,
                SignedIntentStatus::Prepared | SignedIntentStatus::Queued
            )
        {
            recovery = intent
                .with_status(SignedIntentStatus::RecoveryRequired)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            if let Some(history) = history.take()
                && crate::signed_intent_anchor::publish_retained_history(
                    history, record, &intent, &recovery,
                )
                .is_ok()
            {
                slot.intent_publication_fenced = false;
            }
            // The write may have succeeded before an uncertain external CAS.
            slot.signed_intent = read_intent(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        } else if exact && intent.requires_recovery() {
            slot.intent_publication_fenced = false;
        }
        // Containment may enter other owners. Never carry the history lock
        // into that phase or into a later explicit recovery directive.
        drop(history);
        self.contain_signed_intent_processes(agent_id, slot)?;
        if slot.intent_publication_fenced
            || matches!(process_recovery, ProcessRecoveryStatus::Faulted)
            || !recovery.requires_recovery()
            || recovery.status == SignedIntentStatus::Aborted
        {
            return Ok(());
        }
        if let Some(directive) = read_recovery_directive(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        {
            if directive.intent_sha256 != intent.intent_sha256 {
                return Err(SupervisorError::Invalid(
                    "signed intent recovery directive is stale".to_string(),
                ));
            }
            let aborted = recovery
                .with_status(SignedIntentStatus::Aborted)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            let current_record = self.record(agent_id)?;
            slot.intent_publication_fenced = true;
            crate::signed_intent_anchor::publish_history(
                &self.registry,
                &current_record,
                &recovery,
                &aborted,
            )?;
            slot.signed_intent = Some(aborted);
            slot.intent_publication_fenced = false;
        }
        Ok(())
    }

    /// Only the independently recovered process handles may be terminated.
    /// Keep failed kills fenced and retryable; never infer that a lease vanished.
    pub(crate) fn contain_signed_intent_processes(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        slot.restart_pending = false;
        slot.release_change = None;
        let lifecycle = self.record(agent_id)?.lifecycle;
        if matches!(
            lifecycle.lifecycle,
            AgentLifecycle::Starting | AgentLifecycle::Running | AgentLifecycle::Draining
        ) {
            self.transition_without_runtime(
                agent_id,
                slot,
                lifecycle.generation,
                AgentLifecycle::Failed,
            )?;
        }
        let matrix_error = self.kill_matrix_now(agent_id, slot).err();
        let mut primary_error = None;
        if let Some(runtime) = slot.runtime.as_mut() {
            let requested = runtime.fenced && matches!(runtime.phase, RuntimePhase::Killing);
            runtime.fenced = true;
            runtime.healthy = false;
            if !requested {
                runtime.phase = RuntimePhase::Stopping {
                    deadline: std::time::Instant::now(),
                };
                match runtime.process.kill() {
                    Ok(()) => runtime.phase = RuntimePhase::Killing,
                    Err(error) => {
                        primary_error = Some(crate::runtime::driver_error(agent_id, error))
                    }
                }
            }
        }
        if let Some(error) = matrix_error.or(primary_error) {
            return Err(error);
        }
        Ok(())
    }
}
