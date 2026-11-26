//! Recover the existing signed-intent owner without inferring an ambiguous effect.

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
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::read_intent;
use crate::signed_intent::read_recovery_directive;
use crate::signed_intent::write_intent;

pub(crate) enum ProcessRecoveryStatus {
    Complete,
    Faulted,
}

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn recover_signed_intent(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        process_recovery: ProcessRecoveryStatus,
    ) -> Result<(), SupervisorError> {
        let intent = read_intent(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let Some(intent) = intent else {
            return Ok(());
        };
        if intent.agent_id != agent_id.to_string() {
            return Err(SupervisorError::Invalid(
                "signed supervisor intent agent binding mismatch".to_string(),
            ));
        }
        slot.signed_intent = Some(intent.clone());
        if matches!(
            intent.status,
            SignedIntentStatus::Committed | SignedIntentStatus::RolledBack
        ) || (intent.status == SignedIntentStatus::Aborted && !intent.requires_recovery())
        {
            return Ok(());
        }

        // A terminal release transaction is the durable owner witness that the
        // exact signed transition crossed its lifecycle boundary. This closes
        // the crash cut between terminal transaction publication and the
        // matching signed-intent update. Matching release state is required so
        // a detached or unrelated terminal journal cannot close the intent.
        if let Some(transaction) = read_release_transaction(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        {
            let kind_matches = matches!(
                (intent.transition, transaction.kind),
                (
                    H7H89ProductionTransition::Upgrade,
                    ReleaseTransactionKind::Upgrade
                ) | (
                    H7H89ProductionTransition::Rollback,
                    ReleaseTransactionKind::ExplicitRollback
                )
            );
            // An aborted grant cannot be reinterpreted by an ordinary terminal
            // journal. Only a subsequently verified signed recovery decision
            // may close its transaction-before-intent crash cut.
            let terminal_status = if kind_matches
                && (intent.status != SignedIntentStatus::Aborted
                    || transaction.recovery_decision_sha256.is_some())
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
        // blocked until a signed outcome resolves the ambiguity. Local abort
        // abandons the grant but cannot supply that outcome.
        // Read against the pre-recovery digest: the CLI may have inspected a
        // Prepared or Queued intent. A crash before terminal publication makes
        // that directive stale and requires a new inspection.
        let directive = if intent.status == SignedIntentStatus::Aborted {
            Ok(None)
        } else {
            read_recovery_directive(record.layout.run_root())
        };
        let recovery = if intent.requires_recovery() {
            intent.clone()
        } else {
            intent
                .with_status(SignedIntentStatus::RecoveryRequired)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        };
        write_intent(record.layout.run_root(), &recovery)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        slot.signed_intent = Some(recovery.clone());

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
        let mut main_error = None;
        if let Some(runtime) = slot.runtime.as_mut() {
            // Process adoption may already have fenced and successfully requested
            // termination. Hydrating the signed-intent fence is not a second kill.
            let already_requested =
                runtime.fenced && matches!(runtime.phase, RuntimePhase::Killing);
            runtime.fenced = true;
            runtime.healthy = false;
            if !already_requested {
                runtime.phase = RuntimePhase::Stopping {
                    deadline: std::time::Instant::now(),
                };
                match runtime.process.kill() {
                    Ok(()) => runtime.phase = RuntimePhase::Killing,
                    Err(error) => main_error = Some(crate::runtime::driver_error(agent_id, error)),
                }
            }
        }
        if let Some(error) = matrix_error.or(main_error) {
            // Both handles remain fenced and retryable. Never consume a local
            // abort directive after an unsuccessful termination request.
            return Err(error);
        }
        // A missing in-memory handle after an adoption error is not proof of
        // process absence. Keep Unknown quarantined and retain the directive.
        if matches!(process_recovery, ProcessRecoveryStatus::Faulted) {
            return Ok(());
        }
        if let Some(directive) =
            directive.map_err(|error| SupervisorError::Invalid(error.to_string()))?
        {
            if directive.intent_sha256 != intent.intent_sha256 {
                return Err(SupervisorError::Invalid(
                    "signed intent recovery directive is stale or belongs to another intent"
                        .to_string(),
                ));
            }
            // The local directive only abandons the grant. It cannot establish
            // a release outcome, close the release transaction, or authorize a
            // new process. Aborted therefore retains the recovery fence.
            if read_intent(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                .as_ref()
                != Some(&recovery)
            {
                return Err(SupervisorError::Invalid(
                    "signed supervisor intent changed during recovery".to_string(),
                ));
            }
            let aborted = recovery
                .with_status(SignedIntentStatus::Aborted)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            write_intent(record.layout.run_root(), &aborted)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            slot.signed_intent = Some(aborted);
        }
        Ok(())
    }
}
