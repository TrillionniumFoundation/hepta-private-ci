//! A new current signature may retry the exact retained replacement CAS. It
//! does not change any intent, transaction, history or confirmation material.
use crate::H7H89ProductionGrantVerifier;
use crate::ProcessDriver;
use crate::ProductionMutationReceipt;
use crate::ProductionMutationStatus;
use crate::ProductionRecoveryDecision;
use crate::ProductionRecoveryOutcome;
use crate::Supervisor;
use crate::SupervisorError;
use crate::current_recovery_admission::CurrentRecoveryAdmission;
use crate::release_transaction::read_release_transaction;
use crate::runtime::AgentSlot;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::SignedSupervisorIntent;
use crate::signed_intent::read_intent;
use crate::signed_intent_anchor::check_previous;
use crate::signed_intent_policy::digest_bytes;
use crate::unknown_recovery_publication::ensure_stopped;
use crate::unknown_recovery_publication::expected_sha256;
use crate::unknown_recovery_publication::state_sha256;
use crate::unknown_recovery_publication::verify_decision;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::ReleaseId;

impl<D: ProcessDriver> Supervisor<D> {
    #[expect(
        clippy::too_many_arguments,
        reason = "fresh owner observations bind every retained publication input"
    )]
    pub(crate) fn retry_retained_publication(
        &mut self,
        agent: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        intent: &SignedSupervisorIntent,
        decision: &ProductionRecoveryDecision,
        verifier: &H7H89ProductionGrantVerifier,
        authority_epoch: u64,
    ) -> Result<ProductionMutationReceipt, SupervisorError> {
        let denied = || SupervisorError::SignedIntentRecoveryRequired(agent.clone());
        ensure_stopped(record, slot)?;
        if !self.registry.is_release_intent_reconciliation()
            || decision.outcome != ProductionRecoveryOutcome::RetryRetainedPublication
        {
            return Err(denied());
        }
        let status = match intent.status {
            SignedIntentStatus::Committed => ProductionMutationStatus::Committed,
            SignedIntentStatus::RolledBack => ProductionMutationStatus::RolledBack,
            SignedIntentStatus::Aborted if !intent.requires_recovery() => {
                ProductionMutationStatus::Aborted
            }
            SignedIntentStatus::Prepared
            | SignedIntentStatus::Queued
            | SignedIntentStatus::RecoveryRequired
            | SignedIntentStatus::Aborted => return Err(denied()),
        };
        let admission = CurrentRecoveryAdmission::acquire(&self.registry, verifier)?;
        let replacement = admission.replacement().ok_or_else(denied)?.clone();
        check_previous(Some(&replacement), Some(intent), record)?;
        if !replacement.is_closed_history() {
            return Err(denied());
        }
        let expected = admission.expected(agent)?;
        let original_digest = admission.pending_publication_sha256()?;
        let replacement_digest = admission
            .replacement_publication_sha256()?
            .ok_or_else(denied)?;
        let retained_digest = admission
            .retained_reconciliation_sha256()?
            .ok_or_else(denied)?;
        let observation = decision
            .retained_publication_observation
            .as_ref()
            .ok_or_else(denied)?;
        let expected_digest = expected_sha256(
            expected.as_ref(),
            agent,
            Some(&observation.predecessor),
            true,
        )?;
        if digest_bytes(&observation.original_pending_sha256)? != original_digest
            || digest_bytes(&observation.replacement_pending_sha256)? != replacement_digest
            || digest_bytes(&observation.retained_state_sha256)? != retained_digest
            || digest_bytes(&observation.replacement_anchor_sha256)? != replacement.sha256()?
            || observation.release_state_sha256 != state_sha256(record)?
            || observation.release_state_generation != record.release_state.generation
        {
            return Err(denied());
        }
        let release = ReleaseId::parse(decision.observed_release.clone())?;
        if record.release_state.current.as_ref() != Some(&release) {
            return Err(denied());
        }
        let binding = admission.binding(&self.registry, agent, &release)?;
        if observation.admission_frontier_sha256.as_str() != binding.admission_frontier_sha256 {
            return Err(denied());
        }
        let transaction = read_release_transaction(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let transaction_digest = transaction
            .as_ref()
            .map_or_else(crate::absent_release_transaction_digest, |transaction| {
                transaction.transaction_sha256.clone()
            });
        verify_decision(
            verifier,
            decision,
            intent,
            record,
            &binding,
            &transaction_digest,
            authority_epoch,
            admission.now_seconds()?,
        )?;
        let next_revision = slot
            .control_revision
            .checked_add(1)
            .ok_or_else(|| SupervisorError::Invalid("control revision overflow".to_string()))?;
        if self.record(agent)?.release_state != record.release_state
            || self.record(agent)?.lifecycle != record.lifecycle
            || read_intent(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                .as_ref()
                != Some(intent)
            || read_release_transaction(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                != transaction
            || admission.binding(&self.registry, agent, &release)? != binding
        {
            return Err(denied());
        }
        ensure_stopped(record, slot)?;
        check_previous(Some(&replacement), Some(intent), record)?;
        slot.intent_publication_fenced = true;
        admission.retry_retained(
            decision,
            expected_digest,
            original_digest,
            replacement_digest,
            retained_digest,
        )?;
        crate::signed_intent::predecessor::clear_after_confirmation(
            record.layout.run_root(),
            intent,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        slot.signed_intent = Some(intent.clone());
        slot.control_revision = next_revision;
        Ok(ProductionMutationReceipt {
            grant_sha256: intent.grant_sha256.clone(),
            agent_id: intent.agent_id.clone(),
            transition: intent.transition,
            source_release: intent.source_release.clone(),
            target_release: intent.target_release.clone(),
            control_revision: next_revision,
            status,
            production_authority: true,
            external_effects: true,
            operator_acceptance: true,
            promotion: status != ProductionMutationStatus::Aborted,
        })
    }
}
