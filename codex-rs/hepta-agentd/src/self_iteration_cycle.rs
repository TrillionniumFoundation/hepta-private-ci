//! Real model assistance around the existing durable owner. Model assessments
//! inform separately owned candidate construction and evaluation; none of the
//! four model sessions can issue a learning acceptance credential.

use std::future::Future;

use codex_hepta_agent_components::infer_core::SelfIterationModelAssessmentV1;
use codex_hepta_agent_components::infer_core::SelfIterationModelPortV1;
use codex_hepta_agent_components::infer_core::SelfIterationModelRequestV1;
use codex_hepta_agent_components::infer_core::SelfIterationModelRoleV1;
use codex_hepta_agent_components::types::StableId;

use super::*;

/// Constructs actual durable +1 and rollback +2 generations from bounded model
/// output. The host owns the compiler, durable inference control and Generator
/// credential. No caller supplied JSON can substitute for these handles.
pub trait AgentdSelfIterationCandidateAssemblerV1: Send {
    /// Current baseline parameters and permitted mutation bounds, resolved by
    /// the installed host compiler rather than invented by the model.
    fn describe(&self, envelope: &IterationEnvelopeV1) -> Result<String, AgentdError>;

    fn assemble(
        &mut self,
        envelope: IterationEnvelopeV1,
        proposal: &SelfIterationModelAssessmentV1,
    ) -> impl Future<Output = Result<AgentdSelfIterationCandidateV1, AgentdError>> + Send;
}

/// Independently owned acceptance ports. Implementations must run the frozen
/// test plan against candidate and baseline and obtain their original role
/// evidence. The durable coordinator rechecks credential separation and facts.
pub trait AgentdSelfIterationIndependentOwnersV1: Send {
    fn evaluate(
        &mut self,
        candidate: &AgentdSelfIterationCandidateV1,
        frozen: &AgentdSelfIterationRecordV1,
        assessment: &SelfIterationModelAssessmentV1,
    ) -> impl Future<Output = Result<AgentdSignedEvaluationV1, AgentdError>> + Send;

    fn select(
        &mut self,
        evaluated: &AgentdSelfIterationRecordV1,
        assessment: &SelfIterationModelAssessmentV1,
    ) -> impl Future<Output = Result<SignedLearningEvidenceV1, AgentdError>> + Send;

    fn observe(
        &mut self,
        canary: &AgentdSelfIterationRecordV1,
        assessment: &SelfIterationModelAssessmentV1,
    ) -> impl Future<
        Output = Result<
            (AgentdSelfIterationCanaryVerdictV1, SignedLearningEvidenceV1),
            AgentdError,
        >,
    > + Send;
}

/// A cycle owns its model session adapter, durable generation assembler and
/// independent acceptance ports. `run` performs actual native model turns and
/// physical canary/rollback through the bounded Agentd runtime handle.
pub struct AgentdSelfIterationModelCycleV1<M, A, O> {
    model: M,
    assembler: A,
    owners: O,
    runtime: AgentdSelfIterationHandleV1,
}

impl<M, A, O> AgentdSelfIterationModelCycleV1<M, A, O>
where
    M: SelfIterationModelPortV1,
    A: AgentdSelfIterationCandidateAssemblerV1,
    O: AgentdSelfIterationIndependentOwnersV1,
{
    pub fn new(model: M, assembler: A, owners: O, runtime: AgentdSelfIterationHandleV1) -> Self {
        Self {
            model,
            assembler,
            owners,
            runtime,
        }
    }

    pub async fn run(
        &mut self,
        envelope: IterationEnvelopeV1,
        objective_prompt: String,
    ) -> Result<AgentdSelfIterationRecordV1, AgentdError> {
        envelope.validate().map_err(invalid)?;
        if objective_prompt.is_empty() || objective_prompt.len() > 2 * 1024 {
            return Err(invalid("self-iteration objective prompt budget"));
        }
        let deadline_ms = envelope
            .expiry_unix_seconds
            .checked_mul(1_000)
            .ok_or_else(|| invalid("iteration deadline overflow"))?;
        let now = now_ms()?;
        if deadline_ms <= now || deadline_ms > now.saturating_add(3_600_000) {
            return Err(invalid("iteration deadline"));
        }
        let current = self.assembler.describe(&envelope)?;
        if current.is_empty() || current.len() > 2 * 1024 {
            return Err(invalid("host parameter description budget"));
        }
        let envelope_digest = envelope_digest(&envelope);
        let proposal = self.assess(SelfIterationModelRoleV1::Generator,
            envelope_digest, None, deadline_ms, format!(
                "Propose a bounded durable Neuron generation change and its rollback.\nObjective: {objective_prompt}\nActual baseline and permitted mutations: {current}\nEnvelope: {envelope_digest}\nNo acceptance or signing authority is granted."
            )).await?;
        let candidate = self.assembler.assemble(envelope.clone(), &proposal).await?;
        if candidate.envelope != envelope {
            return Err(invalid("assembler changed frozen envelope"));
        }
        let semantic_diff = std::str::from_utf8(&candidate.semantic_diff)
            .map_err(|_| invalid("model-assisted parameter diff must be textual"))?;
        if semantic_diff.len() > 4 * 1024 {
            return Err(invalid("model-assisted parameter diff budget"));
        }
        let frozen_digest = Digest32::of_bytes(&self_iteration_candidate_payload_v1(&candidate)?);
        let frozen = self.runtime.freeze(candidate.clone()).await?;
        if frozen.frozen_digest != frozen_digest {
            return Err(invalid("cycle changed frozen candidate identity"));
        }
        if matches!(
            frozen.phase,
            AgentdSelfIterationPhaseV1::Accepted
                | AgentdSelfIterationPhaseV1::RolledBack
                | AgentdSelfIterationPhaseV1::Rejected
        ) {
            return Ok(frozen);
        }
        let assessment = self.assess(SelfIterationModelRoleV1::Evaluator,
            envelope_digest, Some(frozen_digest), deadline_ms, format!(
                "Assess the frozen candidate for objective alignment and propose adversarial tests.\nObjective: {objective_prompt}\nFrozen candidate: {frozen_digest}\nDiff identity: {}\nFull semantic diff: {semantic_diff}\nTest plan: {}\nModel text is advisory; the independent owner executes the complete frozen plan.",
                candidate.candidate.semantic_diff_digest, candidate.candidate.test_plan_digest
            )).await?;
        let evidence = self
            .owners
            .evaluate(&candidate, &frozen, &assessment)
            .await?;
        let metrics = format!(
            "scope={:?}; metrics={:?}",
            evidence.bundle.claim_scope, evidence.bundle.metrics
        );
        if metrics.len() > 4 * 1024 {
            return Err(invalid("model selection metric context budget"));
        }
        let evaluated = self.runtime.evaluate(frozen_digest, evidence).await?;
        if evaluated.phase == AgentdSelfIterationPhaseV1::Rejected {
            return Ok(evaluated);
        }
        let selection = self.assess(SelfIterationModelRoleV1::Selector,
            envelope_digest, Some(frozen_digest), deadline_ms, format!(
                "Assess selection of frozen candidate {frozen_digest}.\nObjective: {objective_prompt}\nAuthenticated independent evaluation: {:?}\nActual independently measured intervals: {metrics}\nOnly the independent Selector owner can select.", evaluated.evaluation_digest
            )).await?;
        let attestation = self.owners.select(&evaluated, &selection).await?;
        let canary = self.runtime.select(frozen_digest, attestation).await?;
        if canary.phase == AgentdSelfIterationPhaseV1::RolledBack {
            return Ok(canary);
        }
        if canary.phase != AgentdSelfIterationPhaseV1::Canary {
            return Err(invalid("physical canary did not commit"));
        }
        let observation = self.assess(SelfIterationModelRoleV1::Observer,
            envelope_digest, Some(frozen_digest), deadline_ms, format!(
                "Assess the actual durable canary and recommend acceptance or rollback.\nObjective: {objective_prompt}\nGeneration: {}\nNative operation: {:?}\nNative checkpoint: {:?}\nActual receipt measurements: {:?}\nThe independent Observer must resolve and verify the actual receipt before signing.",
                canary.successor_generation, canary.canary_operation_digest,
                canary.canary_checkpoint_digest, canary.canary_observation
            )).await?;
        let (verdict, attestation) = self.owners.observe(&canary, &observation).await?;
        self.runtime
            .observe(frozen_digest, verdict, attestation)
            .await
    }

    async fn assess(
        &mut self,
        role: SelfIterationModelRoleV1,
        envelope_digest: Digest32,
        candidate_digest: Option<Digest32>,
        deadline_ms: u64,
        prompt: String,
    ) -> Result<SelfIterationModelAssessmentV1, AgentdError> {
        let identity = Digest32::of_parts(&[
            b"hepta.self-iteration.model-request.v1",
            envelope_digest.as_array(),
            candidate_digest.unwrap_or(Digest32::ZERO).as_array(),
            &[role as u8],
        ]);
        let request = SelfIterationModelRequestV1 {
            request_id: StableId::new(format!("iteration.{identity}"))
                .map_err(|error| invalid(error.to_string()))?,
            role,
            envelope_digest,
            candidate_digest,
            prompt,
            deadline_ms,
            maximum_response_bytes: 8 * 1024,
        };
        request
            .validate(now_ms()?)
            .map_err(|error| invalid(error.to_string()))?;
        let assessment = self
            .model
            .assess(request.clone())
            .await
            .map_err(|error| invalid(format!("model assessment: {error}")))?;
        assessment
            .validate(&request)
            .map_err(|error| invalid(error.to_string()))?;
        Ok(assessment)
    }
}

pub fn envelope_digest(envelope: &IterationEnvelopeV1) -> Digest32 {
    let mut bytes = b"hepta.self-iteration.envelope.v1\0".to_vec();
    bytes.extend_from_slice(envelope.envelope_id.as_str().as_bytes());
    for digest in [
        envelope.base_commit,
        envelope.base_tree,
        envelope.objective_digest,
        envelope.grammar_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for value in [
        envelope.maximum_files as u64,
        envelope.maximum_diff_bytes,
        envelope.maximum_candidates as u64,
        envelope.maximum_parallel_sandboxes as u64,
        envelope.expiry_unix_seconds,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

pub(super) fn now_ms() -> Result<u64, AgentdError> {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| invalid("iteration clock"))?
        .as_millis()
        .try_into()
        .map_err(|_| invalid("iteration clock overflow"))
}
