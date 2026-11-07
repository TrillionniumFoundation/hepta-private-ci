//! A fresh signed ceremony confirms one exact hot-owner completion proposal.
//! Cold local hashes never synthesize completion, and no process is dispatched.
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
use crate::signed_intent::SignedSupervisorIntent;
use crate::signed_intent::read_intent;
use crate::signed_intent_anchor::snapshot_matches;
use crate::signed_intent_anchor::terminal_witness;
use crate::signed_intent_confirmation::SignedIntentPublicationConfirmation;
use crate::signed_intent_confirmation::{self};
use crate::signed_intent_policy::digest_bytes;
use crate::signed_intent_policy::terminal_owner_matches;
use crate::unknown_recovery_publication::ensure_stopped;
use crate::unknown_recovery_publication::expected_sha256;
use crate::unknown_recovery_publication::state_sha256;
use crate::unknown_recovery_publication::verify_decision;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ReleaseIntentWitnessKindV1;

impl<D: ProcessDriver> Supervisor<D> {
    #[expect(
        clippy::too_many_arguments,
        reason = "the existing owner binds the entire retained terminal publication"
    )]
    pub(crate) fn confirm_completed_publication(
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
        let status = match decision.outcome {
            ProductionRecoveryOutcome::ConfirmCommittedPublication => {
                ProductionMutationStatus::Committed
            }
            ProductionRecoveryOutcome::ConfirmRolledBackPublication => {
                ProductionMutationStatus::RolledBack
            }
            ProductionRecoveryOutcome::Committed
            | ProductionRecoveryOutcome::RolledBack
            | ProductionRecoveryOutcome::AbandonUnknown
            | ProductionRecoveryOutcome::ConfirmUnknownPublication
            | ProductionRecoveryOutcome::RetryRetainedPublication => return Err(denied()),
        };
        ensure_stopped(record, slot)?;
        if !self.registry.is_release_intent_reconciliation() || intent.agent_id != agent.as_str() {
            return Err(denied());
        }
        let proof = intent.pq_authority.as_ref().ok_or_else(denied)?;
        proof.verify_historical_for(intent)?;
        let admission = CurrentRecoveryAdmission::acquire(&self.registry, verifier)?;
        if admission.replacement().is_some() {
            return Err(denied());
        }
        let expected = admission.expected(agent)?;
        let pending = admission.pending().ok_or_else(denied)?.clone();
        let pending_digest = admission.pending_publication_sha256()?;
        if !snapshot_matches(&pending, intent)? {
            return Err(denied());
        }
        let original_witness = pending.terminal_witness.as_ref().ok_or_else(denied)?;
        if original_witness.kind != ReleaseIntentWitnessKindV1::CompletedReleaseCas {
            return Err(denied());
        }
        let observation = decision
            .completion_observation
            .as_ref()
            .ok_or_else(denied)?;
        let expected_digest = expected_sha256(
            expected.as_ref(),
            agent,
            Some(&observation.predecessor),
            true,
        )?;
        if digest_bytes(&observation.pending_publication_sha256)? != pending_digest
            || observation.release_state_sha256 != state_sha256(record)?
            || observation.release_state_generation != record.release_state.generation
        {
            return Err(denied());
        }
        let transaction = read_release_transaction(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
            .ok_or_else(denied)?;
        if !terminal_owner_matches(intent, &transaction, record) {
            return Err(denied());
        }
        let mut actual_witness = terminal_witness(intent, record)?.ok_or_else(denied)?;
        actual_witness.publication_confirmation_sha256 =
            original_witness.publication_confirmation_sha256;
        if &actual_witness != original_witness {
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
        verify_decision(
            verifier,
            decision,
            intent,
            record,
            &binding,
            &transaction.transaction_sha256,
            authority_epoch,
            admission.now_seconds()?,
        )?;
        let material = SignedIntentPublicationConfirmation::new(
            intent,
            verifier.policy_bytes().ok_or_else(denied)?,
            decision.clone(),
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let material_digest = digest_bytes(
            &material
                .digest()
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?,
        )?;
        let mut next = pending.clone();
        next.terminal_witness
            .as_mut()
            .ok_or_else(denied)?
            .publication_confirmation_sha256 = Some(material_digest);
        next.validate()?;
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
        {
            return Err(denied());
        }
        ensure_stopped(record, slot)?;
        admission.check_window(decision)?;
        slot.intent_publication_fenced = true;
        let old = signed_intent_confirmation::read_current(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        signed_intent_confirmation::write_current(
            record.layout.run_root(),
            old.as_ref(),
            Some(&material),
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        if terminal_witness(intent, record)? != next.terminal_witness
            || read_release_transaction(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                .as_ref()
                != Some(&transaction)
            || self.record(agent)?.release_state != record.release_state
            || self.record(agent)?.lifecycle != record.lifecycle
            || admission.binding(&self.registry, agent, &release)? != binding
        {
            return Err(denied());
        }
        admission.commit_completion(
            &next,
            decision,
            material_digest,
            expected_digest,
            pending_digest,
        )?;
        crate::signed_intent::predecessor::clear_after_confirmation(
            record.layout.run_root(),
            intent,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        slot.signed_intent = Some(intent.clone());
        slot.control_revision = next_revision;
        // The explicit recovery Registry stays fenced, including after success.
        // Ordinary authenticated reopen supplies all future launch authority.
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
            promotion: true,
        })
    }
}
