//! Real model assistance around the existing durable owner. Model assessments
//! inform separately owned candidate construction and evaluation; none of the
//! four model sessions can issue a learning acceptance credential.

use std::future::Future;

use codex_hepta_agent_components::infer_core::SelfIterationModelAssessmentV1;
use codex_hepta_agent_components::infer_core::SelfIterationModelPortV1;
use codex_hepta_agent_components::infer_core::SelfIterationModelRoleV1;
use codex_hepta_agent_components::types::StableId;

use super::*;
#[path = "self_iteration_cycle_reserved.rs"]
mod reserved;
#[path = "self_iteration_cycle_terminal.rs"]
mod terminal;

/// Constructs actual durable +1 and rollback +2 generations from bounded model
/// output. The host owns the compiler, durable inference control and Generator
/// credential. No caller supplied JSON can substitute for these handles.
pub trait AgentdSelfIterationCandidateAssemblerV1: Send {
    fn bind_round(
        &mut self,
        _round: AgentdSelfIterationRoundV1,
        _canonical: crate::CanonicalIterationEnvelopeV1,
    ) -> Result<(), AgentdError> {
        Err(invalid(
            "candidate assembler has no installed canonical round port",
        ))
    }

    /// Current baseline parameters and permitted mutation bounds, resolved by
    /// the installed host compiler rather than invented by the model.
    fn describe(&self, envelope: &IterationEnvelopeV1) -> Result<String, AgentdError>;

    /// The default makes no no-effect claim. Implementations must reject only
    /// before all original candidate intents/tasks, including cold recovery.
    fn validate_before_candidate_effects(
        &mut self,
        _envelope: &IterationEnvelopeV1,
        _proposal: &SelfIterationModelAssessmentV1,
    ) -> impl Future<Output = Result<AgentdSelfIterationCandidateEffectAdmissionV1, AgentdError>> + Send
    {
        std::future::ready(Ok(
            AgentdSelfIterationCandidateEffectAdmissionV1::ConservativeUnknown,
        ))
    }

    /// Only observe completed original effects; default cannot recover or reissue.
    fn recover_completed(
        &mut self,
        _envelope: IterationEnvelopeV1,
        _proposal: &SelfIterationModelAssessmentV1,
    ) -> impl Future<Output = Result<Option<AgentdSelfIterationCandidateV1>, AgentdError>> + Send
    {
        std::future::ready(Ok(None))
    }

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
struct PendingModel<M> {
    request_id: StableId,
    task: tokio::task::JoinHandle<(M, Result<SelfIterationModelAssessmentV1, AgentdError>)>,
}

pub struct AgentdSelfIterationModelCycleV1<M, A, O> {
    model: Option<M>,
    pending_model: Option<PendingModel<M>>,
    round: Option<AgentdSelfIterationRoundV1>,
    canonical: Option<crate::CanonicalIterationEnvelopeV1>,
    assembler: Option<A>,
    pending_candidate: Option<candidate_task::PendingCandidate<A>>,
    constructed_candidate: Option<AgentdSelfIterationCandidateV1>,
    actual_description: Option<String>,
    owners: O,
    runtime: AgentdSelfIterationHandleV1,
}

impl<M, A, O> AgentdSelfIterationModelCycleV1<M, A, O>
where
    M: SelfIterationModelPortV1 + 'static,
    A: AgentdSelfIterationCandidateAssemblerV1 + 'static,
    O: AgentdSelfIterationIndependentOwnersV1,
{
    pub fn new(model: M, assembler: A, owners: O, runtime: AgentdSelfIterationHandleV1) -> Self {
        Self {
            model: Some(model),
            pending_model: None,
            round: None,
            canonical: None,
            assembler: Some(assembler),
            pending_candidate: None,
            constructed_candidate: None,
            actual_description: None,
            owners,
            runtime,
        }
    }

    /// Uses the actual existing Goal and an independently installed canonical
    /// window. Reservation, quota and absolute time survive process restart.
    /// Borrow only the same actual native model owner while no retained model
    /// task owns it. Release this borrow before running the reserved cycle.
    pub fn model_mut(&mut self) -> Option<&mut M> {
        if self.pending_model.is_some() {
            None
        } else {
            self.model.as_mut()
        }
    }

    pub async fn run_for_goal(
        &mut self,
        goal: StableId,
        canonical: crate::CanonicalIterationEnvelopeV1,
        envelope: IterationEnvelopeV1,
        objective_prompt: String,
    ) -> Result<AgentdSelfIterationRecordV1, AgentdError> {
        if objective_prompt.is_empty() || objective_prompt.len() > 2 * 1024 {
            return Err(invalid("self-iteration objective prompt budget"));
        }
        let round = self
            .runtime
            .reserve_round(goal, canonical.clone(), envelope.clone())
            .await?;
        self.run_reserved_round(round, canonical, envelope, objective_prompt)
            .await
    }

    pub async fn run(
        &mut self,
        envelope: IterationEnvelopeV1,
        objective_prompt: String,
    ) -> Result<AgentdSelfIterationRecordV1, AgentdError> {
        if self.pending_model.is_some() || self.pending_candidate.is_some() {
            return Err(invalid("original model request is still owned"));
        }
        self.constructed_candidate = None;
        self.actual_description = None;
        self.round = None;
        self.canonical = None;
        self.run_inner(envelope, objective_prompt).await
    }

    async fn run_inner(
        &mut self,
        envelope: IterationEnvelopeV1,
        objective_prompt: String,
    ) -> Result<AgentdSelfIterationRecordV1, AgentdError> {
        envelope.validate().map_err(invalid)?;
        if objective_prompt.is_empty() || objective_prompt.len() > 2 * 1024 {
            return Err(invalid("self-iteration objective prompt budget"));
        }
        let envelope_deadline_ms = envelope
            .expiry_unix_seconds
            .checked_mul(1_000)
            .ok_or_else(|| invalid("iteration deadline overflow"))?;
        let deadline_ms = self
            .round
            .as_ref()
            .map(AgentdSelfIterationRoundV1::deadline_ms)
            .unwrap_or(envelope_deadline_ms);
        let now = now_ms()?;
        if deadline_ms <= now || deadline_ms > now.saturating_add(3_600_000) {
            return Err(invalid("iteration deadline"));
        }
        let current = if let Some(assembler) = &self.assembler {
            assembler.describe(&envelope)?
        } else {
            self.actual_description
                .clone()
                .ok_or_else(|| invalid("original candidate description unavailable"))?
        };
        self.actual_description = Some(current.clone());
        if current.is_empty() || current.len() > 2 * 1024 {
            return Err(invalid("host parameter description budget"));
        }
        let envelope_digest = envelope_digest(&envelope);
        let proposal = self
            .assess(
                SelfIterationModelRoleV1::Generator,
                envelope_digest,
                None,
                deadline_ms,
                generator_prompt(&objective_prompt, &current, envelope_digest)?,
            )
            .await?;
        let candidate = self
            .construct_candidate(envelope.clone(), proposal.clone())
            .await?;
        if self
            .canonical
            .as_ref()
            .map(crate::CanonicalIterationEnvelopeV1::digest)
            != candidate
                .canonical_envelope
                .as_ref()
                .map(crate::CanonicalIterationEnvelopeV1::digest)
            || self.round.is_some() && candidate.model_assessment.as_ref() != Some(&proposal)
        {
            return Err(invalid(
                "assembler changed original canonical round or Generator receipt",
            ));
        }
        if candidate.envelope != envelope {
            return Err(invalid("assembler changed frozen envelope"));
        }
        let semantic_diff = std::str::from_utf8(&candidate.semantic_diff)
            .map_err(|_| invalid("model-assisted parameter diff must be textual"))?;
        if semantic_diff.len() > 4 * 1024 {
            return Err(invalid("model-assisted parameter diff budget"));
        }
        let frozen_digest =
            Digest32::of_bytes(&self_iteration_frozen_candidate_payload_v1(&candidate)?);
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
        let request = model_request(
            self.round.as_ref(),
            role,
            envelope_digest,
            candidate_digest,
            deadline_ms,
            prompt,
        )?;
        if let Some(round) = &self.round {
            let admission = self
                .runtime
                .begin_model(round.clone(), request.clone())
                .await?;
            match admission {
                AgentdSelfIterationModelAdmissionV1::Failed(failure) => {
                    terminal::retire_failed_task(
                        &mut self.pending_model,
                        &mut self.model,
                        &request,
                        &failure,
                    )
                    .await?;
                    return Err(terminal::failure_error(&failure));
                }
                AgentdSelfIterationModelAdmissionV1::Completed(assessment) => {
                    if self
                        .pending_model
                        .as_ref()
                        .is_some_and(|pending| pending.request_id == request.request_id)
                    {
                        let pending = self
                            .pending_model
                            .as_mut()
                            .ok_or_else(|| invalid("actual model task missing"))?;
                        let (model, result) = (&mut pending.task)
                            .await
                            .map_err(|error| invalid(format!("actual model task: {error}")))?;
                        self.pending_model = None;
                        self.model = Some(model);
                        if result? != assessment {
                            return Err(invalid(
                                "original task differs from durable terminal receipt",
                            ));
                        }
                    }
                    return Ok(assessment);
                }
                AgentdSelfIterationModelAdmissionV1::Pending => {
                    if self
                        .pending_model
                        .as_ref()
                        .is_none_or(|pending| pending.request_id != request.request_id)
                    {
                        let model = self
                            .model
                            .as_mut()
                            .ok_or_else(|| invalid("original model adapter unavailable"))?;
                        if let Some(failure) =
                            model.observe_failed(&request).await.map_err(|error| {
                                invalid(format!("readonly model failure observation: {error}"))
                            })?
                        {
                            failure
                                .validate(&request)
                                .map_err(|e| invalid(e.to_string()))?;
                            self.runtime
                                .complete_failed_model(round.clone(), request, failure.clone())
                                .await?;
                            return Err(terminal::failure_error(&failure));
                        }
                        return Err(invalid(
                            "original admitted model request remains unknown; it will not be reissued",
                        ));
                    }
                }
                AgentdSelfIterationModelAdmissionV1::Fresh => {
                    if self.pending_model.is_some() {
                        return Err(invalid("another actual model request is still owned"));
                    }
                    let mut model = self
                        .model
                        .take()
                        .ok_or_else(|| invalid("original model adapter unavailable"))?;
                    let runtime = self.runtime.clone();
                    let admitted_round = round.clone();
                    let admitted_request = request.clone();
                    let task = tokio::spawn(async move {
                        let result = terminal::assess(
                            &mut model,
                            &runtime,
                            admitted_round,
                            admitted_request,
                        )
                        .await;
                        (model, result)
                    });
                    self.pending_model = Some(PendingModel {
                        request_id: request.request_id.clone(),
                        task,
                    });
                }
            }
            // Await by reference: dropping the caller's future retains the actual
            // task and adapter. Its terminal receipt is written by that task.
            let pending = self
                .pending_model
                .as_mut()
                .ok_or_else(|| invalid("actual model task missing"))?;
            let joined = (&mut pending.task).await;
            self.pending_model = None;
            let (model, result) =
                joined.map_err(|error| invalid(format!("actual model task: {error}")))?;
            self.model = Some(model);
            return result;
        }
        request
            .validate(now_ms()?)
            .map_err(|error| invalid(error.to_string()))?;
        let assessment = self
            .model
            .as_mut()
            .ok_or_else(|| invalid("original model adapter unavailable"))?
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

#[path = "self_iteration_cycle_candidate_task.rs"]
mod candidate_task;
