//! Read signed denial before any constructor control or semantic replay.
//! Exact terminal transaction/release witnesses retain their existing recovery
//! path; an unresolved intent cannot downgrade to an unsigned transition.

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentRecord;

use super::*;

impl<D: ProcessDriver> Supervisor<D> {
    pub(super) fn prime_signed_recovery_denial(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
    ) -> Result<(), SupervisorError> {
        let Some(intent) = read_intent(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        else {
            return Ok(());
        };
        if intent.agent_id != agent_id.to_string() {
            return Err(SupervisorError::Invalid(
                "signed supervisor intent agent binding mismatch".to_string(),
            ));
        }
        if matches!(
            intent.status,
            SignedIntentStatus::Committed | SignedIntentStatus::RolledBack
        ) {
            slot.signed_intent = Some(intent);
            return Ok(());
        }
        if let Some(transaction) = read_release_transaction(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        {
            let outcome = match transaction.phase {
                ReleaseTransactionPhase::Committed => Some(ProductionRecoveryOutcome::Committed),
                ReleaseTransactionPhase::RolledBack => Some(ProductionRecoveryOutcome::RolledBack),
                ReleaseTransactionPhase::Prepared
                | ReleaseTransactionPhase::Draining
                | ReleaseTransactionPhase::TargetStarting
                | ReleaseTransactionPhase::AutomaticRollbackStarting
                | ReleaseTransactionPhase::Aborted
                | ReleaseTransactionPhase::RecoveryRequired => None,
            };
            if let Some(outcome) = outcome
                && Self::signed_recovery_outcome(
                    &intent,
                    &transaction,
                    &record.release_state,
                    outcome,
                )
                .is_ok()
            {
                // This is the same exact terminal proof consumed by the
                // later signed-intent writer, not automatic grant replay.
                let status = match outcome {
                    ProductionRecoveryOutcome::Committed => SignedIntentStatus::Committed,
                    ProductionRecoveryOutcome::RolledBack => SignedIntentStatus::RolledBack,
                };
                slot.signed_intent = Some(
                    intent
                        .with_status(status)
                        .map_err(|error| SupervisorError::Invalid(error.to_string()))?,
                );
                return Ok(());
            }
        }
        slot.signed_intent = Some(
            intent
                .with_status(SignedIntentStatus::RecoveryRequired)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?,
        );
        Ok(())
    }
}
