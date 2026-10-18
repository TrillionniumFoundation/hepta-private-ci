//! Explicitly dispose of an unknown signed effect in the original owner. The
//! disposition and retained history are one atomic intent publication.
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::release_transaction::read_release_transaction;
use crate::runtime::AgentSlot;
use crate::signed_authority::*;
use crate::signed_intent::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::ReleaseId;

impl<D: ProcessDriver> Supervisor<D> {
    #[expect(
        clippy::too_many_arguments,
        reason = "existing owner passes its exact locked observations"
    )]
    pub(crate) fn resolve_unknown_recovery_in_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        intent: &SignedSupervisorIntent,
        decision: &ProductionRecoveryDecision,
        verifier: &H7H89ProductionGrantVerifier,
        expected_authority_epoch: u64,
        now_unix_seconds: u64,
    ) -> Result<ProductionMutationReceipt, SupervisorError> {
        if intent.agent_id != agent_id.to_string()
            || !intent.requires_recovery()
            || slot.runtime.is_some()
            || slot.matrix.runtime.is_some()
            || !matches!(
                record.lifecycle.lifecycle,
                AgentLifecycle::Failed | AgentLifecycle::Stopped
            )
            || crate::lease::read_lease(record.layout.run_root())?.is_some()
            || crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.is_some()
            || read_release_transaction(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                .is_some()
        {
            return Err(SupervisorError::SignedIntentRecoveryRequired(
                agent_id.clone(),
            ));
        }
        let source_id = ReleaseId::parse(intent.source_release.clone())?;
        if record.release_state.current.as_ref() != Some(&source_id) {
            return Err(SupervisorError::ProductionAuthority(
                "unknown disposition cannot select another current release".to_string(),
            ));
        }
        // The catalog owner rechecks revocation and the complete material binding.
        let source = self
            .registry
            .resolve_release_binding(agent_id, &source_id)?;
        let observation = decision.unknown_observation.as_ref().ok_or_else(|| {
            SupervisorError::ProductionAuthority("missing v2 observation".to_string())
        })?;
        if observation.release_state_generation != record.release_state.generation
            || observation.admission_frontier_sha256.as_str() != source.admission_frontier_sha256
        {
            return Err(SupervisorError::ProductionAuthority(
                "source frontier or release generation changed".to_string(),
            ));
        }
        let parse = |value: &str| Sha256Digest::parse(value).map_err(SupervisorError::Invalid);
        verifier
            .verify_recovery(
                decision,
                agent_id,
                &intent.grant_sha256,
                &intent.intent_sha256,
                &absent_release_transaction_digest(),
                &intent.source_release,
                &parse(&source.manifest_sha256)?,
                &parse(&source.agentd_program_sha256)?,
                source
                    .matrixd_program_sha256
                    .as_deref()
                    .map(parse)
                    .transpose()?
                    .as_ref(),
                record.lifecycle.generation,
                expected_authority_epoch,
                now_unix_seconds,
            )
            .map_err(|error| SupervisorError::ProductionAuthority(error.to_string()))?;
        let terminal = intent
            .abandon_unknown(decision)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let next_revision = slot
            .control_revision
            .checked_add(1)
            .ok_or_else(|| SupervisorError::Invalid("control revision overflow".to_string()))?;
        // Revalidate immediately before the existing single writer publishes.
        // No transaction, release selection, or unknown fact is synthesized.
        if self.record(agent_id)?.release_state != record.release_state
            || self.record(agent_id)?.lifecycle != record.lifecycle
            || self
                .registry
                .resolve_release_binding(agent_id, &source_id)?
                != source
            || crate::lease::read_lease(record.layout.run_root())?.is_some()
            || crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.is_some()
            || read_intent(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                .as_ref()
                != Some(intent)
            || read_release_transaction(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                .is_some()
        {
            return Err(SupervisorError::SignedIntentRecoveryRequired(
                agent_id.clone(),
            ));
        }
        write_intent(record.layout.run_root(), &terminal)
            .map_err(|_| SupervisorError::SignedIntentRecoveryRequired(agent_id.clone()))?;
        slot.signed_intent = Some(terminal.clone());
        slot.control_revision = next_revision;
        // Restart budget is retained. Normal lifecycle admission must still
        // revalidate the source before any future spawn.
        Ok(ProductionMutationReceipt {
            grant_sha256: terminal.grant_sha256,
            agent_id: terminal.agent_id,
            transition: terminal.transition,
            source_release: terminal.source_release,
            target_release: terminal.target_release,
            control_revision: next_revision,
            status: ProductionMutationStatus::Aborted,
            production_authority: true,
            external_effects: true,
            operator_acceptance: true,
            promotion: false,
        })
    }
}
