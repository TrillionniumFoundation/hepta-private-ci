//! Recover signed mutations and consume exact operator abort directives.

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentRecord;

use crate::H7H89ProductionTransition;
use crate::ManagedProcess;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::release_transaction::ReleaseTransactionKind;
use crate::release_transaction::ReleaseTransactionPhase;
use crate::release_transaction::read_release_transaction;
use crate::release_transaction::write_release_transaction;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::signed_intent::SignedIntentRecoveryAction;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::read_intent;
use crate::signed_intent::read_recovery_directive;
use crate::signed_intent::write_intent;

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn restore_signed_intent(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
    ) -> Result<(), SupervisorError> {
        let intent = read_intent(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        if intent
            .as_ref()
            .is_some_and(|intent| intent.agent_id != agent_id.to_string())
        {
            return Err(SupervisorError::Invalid(
                "signed supervisor intent agent binding mismatch".to_string(),
            ));
        }
        // Adoption::Rejected is not proof of process exit. Hydrate the intent
        // before adoption so those branches retain unresolved owner leases.
        slot.signed_intent = intent;
        Ok(())
    }

    pub(crate) fn recover_signed_intent(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
    ) -> Result<(), SupervisorError> {
        let Some(intent) = slot.signed_intent.clone() else {
            return Ok(());
        };
        if intent.status.terminal() {
            return Ok(());
        }

        let expected_kind = match intent.transition {
            H7H89ProductionTransition::Upgrade => ReleaseTransactionKind::Upgrade,
            H7H89ProductionTransition::Rollback => ReleaseTransactionKind::ExplicitRollback,
        };
        let abort_requested = read_recovery_directive(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
            .is_some_and(|directive| match directive.action {
                SignedIntentRecoveryAction::Abort => {
                    directive.intent_sha256 == intent.intent_sha256
                }
            });

        // A terminal release transaction is the durable owner witness that the
        // exact signed transition crossed its lifecycle boundary. This closes
        // the crash cut between terminal transaction publication and the
        // matching signed-intent update. Matching release state is required so
        // a detached or unrelated terminal journal cannot close the intent.
        if let Some(transaction) = read_release_transaction(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        {
            let kind_matches = transaction.kind == expected_kind;
            let terminal_status = if kind_matches
                && transaction.grant_sha256.as_ref() == Some(&intent.grant_sha256)
                && transaction.source_release == intent.source_release
                && transaction.target_release == intent.target_release
            {
                let current = record
                    .release_state
                    .current
                    .as_ref()
                    .map(codex_hepta_fleet::ReleaseId::as_str);
                let previous = record
                    .release_state
                    .previous
                    .as_ref()
                    .map(codex_hepta_fleet::ReleaseId::as_str);
                match (intent.transition, transaction.phase) {
                    (H7H89ProductionTransition::Upgrade, ReleaseTransactionPhase::Committed)
                        if current == Some(intent.target_release.as_str())
                            && previous == Some(intent.source_release.as_str()) =>
                    {
                        Some(SignedIntentStatus::Committed)
                    }
                    (H7H89ProductionTransition::Upgrade, ReleaseTransactionPhase::RolledBack)
                        if current == Some(intent.source_release.as_str()) =>
                    {
                        Some(SignedIntentStatus::RolledBack)
                    }
                    (H7H89ProductionTransition::Rollback, ReleaseTransactionPhase::RolledBack)
                        if current == Some(intent.target_release.as_str())
                            && previous == Some(intent.source_release.as_str()) =>
                    {
                        Some(SignedIntentStatus::RolledBack)
                    }
                    _ => None,
                }
            } else {
                None
            };
            if let Some(status) = terminal_status {
                let terminal = intent
                    .with_status(status)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                write_intent(record.layout.run_root(), &terminal)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                slot.signed_intent = Some(terminal);
                return Ok(());
            }
        }

        // Keep the daemon reachable for the status/recovery ceremony while
        // quarantining this Agent generation. Ordinary mutation admission is
        // blocked until the signed intent reaches a terminal state.
        let recovery = intent
            .with_status(SignedIntentStatus::RecoveryRequired)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        if !abort_requested {
            write_intent(record.layout.run_root(), &recovery)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        }
        // Keep an accepted abort bound to the exact durable intent while its
        // children exit. Normalizing that digest would strand the directive
        // across another daemon restart. The live slot still remains quarantined.
        slot.signed_intent = Some(recovery);
        slot.restart_pending = false;
        slot.restart_not_before = None;
        slot.release_change = None;
        slot.deferred_agent_action = None;
        slot.matrix.restart_after_exit = false;
        slot.matrix.retry_at = None;
        if crate::restart_journal::read_main_restart_budget(record.layout.run_root())?
            .is_some_and(|budget| budget.pending)
        {
            crate::restart_budget::complete_restart(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        }

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
        self.kill_matrix_now(agent_id, slot)?;
        if let Some(runtime) = slot.runtime.as_mut() {
            // Process adoption may already have fenced and successfully requested
            // termination. Hydrating the signed-intent fence is not a second kill.
            let already_requested =
                runtime.fenced && matches!(runtime.phase, RuntimePhase::Killing);
            runtime.fenced = true;
            if !already_requested {
                runtime
                    .process
                    .kill()
                    .map_err(|error| crate::runtime::driver_error(agent_id, error))?;
                runtime.phase = RuntimePhase::Killing;
            }
        }
        if abort_requested
            && slot.runtime.is_none()
            && slot.matrix.runtime.is_none()
            && crate::lease::read_lease(record.layout.run_root())?.is_none()
            && crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.is_none()
        {
            if let Some(transaction) = read_release_transaction(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
            {
                if transaction.agent_id != intent.agent_id
                    || transaction.kind != expected_kind
                    || transaction.grant_sha256.as_ref() != Some(&intent.grant_sha256)
                    || transaction.source_release != intent.source_release
                    || transaction.target_release != intent.target_release
                    || transaction.authority_epoch != Some(intent.authority_epoch)
                    || transaction.expected_lifecycle_generation
                        != intent.expected_lifecycle_generation
                    || (transaction.phase.terminal()
                        && transaction.phase != ReleaseTransactionPhase::Aborted)
                {
                    return Err(SupervisorError::Invalid(
                        "abort directive does not match the unresolved release transaction".into(),
                    ));
                }
                let aborted = transaction
                    .with_phase(ReleaseTransactionPhase::Aborted)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                write_release_transaction(record.layout.run_root(), &aborted)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                slot.release_transaction = Some(aborted);
            }
            // Only terminalize after both process owners and their durable
            // leases are absent. Killing a child is not observing its exit.
            let aborted = intent
                .with_status(SignedIntentStatus::Aborted)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            write_intent(record.layout.run_root(), &aborted)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            slot.signed_intent = Some(aborted);
        }
        Ok(())
    }
}
