//! Stop interrupts queued replacement using the existing owner journals.
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::release_transaction::ReleaseTransactionPhase;
use crate::release_transaction::read_release_transaction;
use crate::release_transaction::write_release_transaction;
use crate::runtime::AgentSlot;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::read_intent;
use crate::signed_intent::write_intent;
use codex_hepta_contracts::AgentId;

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn quarantine_release_for_stop(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        slot.release_change = None;
        slot.deferred_agent_action = None;
        let record = self.record(agent_id)?;
        if let Some(transaction) = read_release_transaction(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        {
            let pending = !transaction.phase.terminal();
            let next = if pending {
                transaction
                    .with_phase(ReleaseTransactionPhase::RecoveryRequired)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?
            } else {
                transaction
            };
            slot.release_transaction = Some(next.clone());
            if pending {
                write_release_transaction(record.layout.run_root(), &next)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            }
        }
        if let Some(intent) = read_intent(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        {
            let pending = !matches!(
                intent.status,
                SignedIntentStatus::Committed
                    | SignedIntentStatus::RolledBack
                    | SignedIntentStatus::Aborted
            );
            let next = if pending {
                intent
                    .with_status(SignedIntentStatus::RecoveryRequired)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?
            } else {
                intent
            };
            slot.signed_intent = Some(next.clone());
            if pending {
                write_intent(record.layout.run_root(), &next)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            }
        }
        Ok(())
    }
}
