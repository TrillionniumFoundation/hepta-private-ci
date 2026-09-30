use codex_hepta_agent_components::neuron::NeuronAdmissionError;
use codex_hepta_agent_components::neuron::NeuronAdmissionGuard;
use codex_hepta_agent_components::neuron::NeuronCommitDispositionV1;
use codex_hepta_agent_components::neuron::NeuronRuntimeConfigV1;

use super::*;
use codex_hepta_agent_components::neuron::NeuronTickInputV1;

impl SelfIterationOwner {
    pub(super) fn select(
        &mut self,
        frozen: Digest32,
        attestation: SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<AgentdSelfIterationRecordV1, AgentdError> {
        if self.cancellation.is_cancelled() {
            return Err(invalid("iteration cancelled"));
        }
        let current = self
            .current
            .as_mut()
            .ok_or_else(|| invalid("candidate not frozen"))?;
        if current.record.frozen_digest != frozen || now / 1_000 >= current.record.expires_at {
            return Err(invalid("selection deadline or binding"));
        }
        let evaluation = current
            .record
            .evaluation_digest
            .ok_or_else(|| invalid("independent evaluation missing"))?;
        let evaluator = current
            .evaluator
            .as_ref()
            .ok_or_else(|| invalid("evaluation must be reauthenticated after recovery"))?;
        let selector = self
            .trust
            .verifier()
            .verify(
                LearningEvidenceRoleV1::Selector,
                &attestation,
                &self_iteration_stage_payload_v1(frozen, evaluation),
                now,
            )
            .map_err(|error| invalid(error.to_string()))?;
        for other in [&current.generator, evaluator] {
            verify_signed_actor_separation(other, &selector, now)
                .map_err(|error| invalid(error.to_string()))?;
        }
        let selection_digest =
            Digest32::of_parts(&[&attestation.signing_bytes(), &attestation.signature]);
        if current
            .record
            .selection_digest
            .is_some_and(|previous| previous != selection_digest)
        {
            return Err(invalid("recovery changed selection"));
        }
        current.selector = Some(selector);
        current.record.selection_digest = Some(selection_digest);
        if current.record.phase == AgentdSelfIterationPhaseV1::RollingBack {
            return self.rollback();
        }
        if matches!(
            current.record.phase,
            AgentdSelfIterationPhaseV1::Accepted
                | AgentdSelfIterationPhaseV1::RolledBack
                | AgentdSelfIterationPhaseV1::Rejected
        ) {
            return Ok(current.record.clone());
        }
        if current.record.phase == AgentdSelfIterationPhaseV1::Evaluated {
            current.record.phase = AgentdSelfIterationPhaseV1::Applying;
            self.journal.persist(&current.record)?;
        }
        self.host.quarantine_iteration()?;
        self.host.install_iteration_generation(
            current.request.successor.clone(),
            current.record.base_generation,
        )?;
        // A replay uses the same tick and semantic input. The durable Neuron
        // operation owner returns the original commit and never redispatches it.
        let invocation = self.host.prepare_iteration_probe(
            current.request.canary_port.run_id.clone(),
            current
                .request
                .successor
                .body_bundle_digest()
                .ok_or_else(|| invalid("durable canary body missing"))?,
            current.request.canary_tick.clone(),
        )?;
        let mut guard = IterationCanaryGuard {
            objective: current.record.objective_digest,
            generation: current.record.successor_generation,
            expires_at: current.record.expires_at,
            deadline: std::time::Instant::now()
                + std::time::Duration::from_micros(current.request.canary_port.budget_micros),
            cancellation: self.cancellation.clone(),
        };
        let commit = invocation
            .execute(&current.request.canary_port, &mut guard)
            .map_err(|error| invalid(format!("canary operation: {error}")))?;
        current.record.canary_operation_digest = Some(commit.operation_digest);
        current.record.canary_checkpoint_digest = Some(commit.output.tick.checkpoint_after);
        current.record.phase = AgentdSelfIterationPhaseV1::Canary;
        self.journal.persist(&current.record)?;
        if commit.disposition != NeuronCommitDispositionV1::CommittedReady {
            return self.rollback();
        }
        Ok(current.record.clone())
    }

    pub(super) fn observe(
        &mut self,
        frozen: Digest32,
        verdict: AgentdSelfIterationCanaryVerdictV1,
        attestation: SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<AgentdSelfIterationRecordV1, AgentdError> {
        let current = self
            .current
            .as_mut()
            .ok_or_else(|| invalid("candidate not frozen"))?;
        if current.record.frozen_digest != frozen
            || current.record.phase != AgentdSelfIterationPhaseV1::Canary
            || now / 1_000 >= current.record.expires_at
        {
            return Err(invalid("canary phase or expiry"));
        }
        let observer = self
            .trust
            .verifier()
            .verify(
                LearningEvidenceRoleV1::Observer,
                &attestation,
                &self_iteration_canary_payload_v1(&current.record, verdict)?,
                now,
            )
            .map_err(|error| invalid(error.to_string()))?;
        for other in [
            &current.generator,
            current
                .evaluator
                .as_ref()
                .ok_or_else(|| invalid("evaluator missing"))?,
            current
                .selector
                .as_ref()
                .ok_or_else(|| invalid("selector missing"))?,
        ] {
            verify_signed_actor_separation(other, &observer, now)
                .map_err(|error| invalid(error.to_string()))?;
        }
        current.record.observer_digest = Some(Digest32::of_parts(&[
            &attestation.signing_bytes(),
            &attestation.signature,
        ]));
        match verdict {
            AgentdSelfIterationCanaryVerdictV1::Accept => {
                current.record.phase = AgentdSelfIterationPhaseV1::Accepted;
                self.journal.persist(&current.record)?;
                self.host.release_iteration_quarantine()?;
                let record = current.record.clone();
                self.current = None;
                Ok(record)
            }
            AgentdSelfIterationCanaryVerdictV1::RollBack => self.rollback(),
        }
    }

    pub(super) fn expire(&mut self, now: u64) -> Result<(), AgentdError> {
        if self
            .current
            .as_ref()
            .is_none_or(|current| now / 1_000 < current.record.expires_at)
        {
            return Ok(());
        }
        let current = self
            .current
            .as_mut()
            .ok_or_else(|| invalid("expired candidate missing"))?;
        match current.record.phase {
            AgentdSelfIterationPhaseV1::Frozen | AgentdSelfIterationPhaseV1::Evaluated => {
                current.record.phase = AgentdSelfIterationPhaseV1::Rejected;
                self.journal.persist(&current.record)?;
                self.current = None;
            }
            AgentdSelfIterationPhaseV1::Applying
            | AgentdSelfIterationPhaseV1::Canary
            | AgentdSelfIterationPhaseV1::RollingBack => {
                self.rollback()?;
            }
            AgentdSelfIterationPhaseV1::Accepted
            | AgentdSelfIterationPhaseV1::RolledBack
            | AgentdSelfIterationPhaseV1::Rejected => {
                self.current = None;
            }
        }
        Ok(())
    }

    fn rollback(&mut self) -> Result<AgentdSelfIterationRecordV1, AgentdError> {
        let current = self
            .current
            .as_mut()
            .ok_or_else(|| invalid("rollback candidate missing"))?;
        current.record.phase = AgentdSelfIterationPhaseV1::RollingBack;
        self.journal.persist(&current.record)?;
        self.host.quarantine_iteration()?;
        let actual = self.host.generation_snapshot()?.active_generation;
        if ![
            current.record.base_generation,
            current.record.successor_generation,
            current.record.rollback_generation,
        ]
        .contains(&actual)
        {
            return Err(invalid("rollback predecessor changed"));
        }
        self.host
            .install_iteration_generation(current.request.rollback_successor.clone(), actual)?;
        current.record.phase = AgentdSelfIterationPhaseV1::RolledBack;
        self.journal.persist(&current.record)?;
        self.host.release_iteration_quarantine()?;
        let record = current.record.clone();
        self.current = None;
        Ok(record)
    }
}

struct IterationCanaryGuard {
    objective: Digest32,
    generation: u64,
    expires_at: u64,
    deadline: std::time::Instant,
    cancellation: tokio_util::sync::CancellationToken,
}
impl NeuronAdmissionGuard for IterationCanaryGuard {
    fn check(
        &mut self,
        _config: &NeuronRuntimeConfigV1,
        input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| NeuronAdmissionError::Unavailable)?
            .as_secs();
        if self.cancellation.is_cancelled() {
            return Err(NeuronAdmissionError::Cancelled);
        }
        if now >= self.expires_at || std::time::Instant::now() >= self.deadline {
            return Err(NeuronAdmissionError::DeadlineExceeded);
        }
        if input.objective_digest != self.objective
            || input.body_generation != Some(self.generation)
        {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        Ok(())
    }
}
