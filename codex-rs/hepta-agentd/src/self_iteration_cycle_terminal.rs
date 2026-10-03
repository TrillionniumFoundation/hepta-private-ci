//! Retained model task records only actual terminal facts through the original writer.
use super::*;
use codex_hepta_agent_components::infer_core::SelfIterationModelFailureV1;
use codex_hepta_agent_components::infer_core::SelfIterationModelRequestV1;

pub(super) fn failure_error(failure: &SelfIterationModelFailureV1) -> AgentdError {
    AgentdError::SelfIterationModelFailed {
        role: failure.role as u8,
        facts_digest: failure.facts_digest.to_string(),
    }
}

pub(super) async fn retire_failed_task<M>(
    pending_model: &mut Option<PendingModel<M>>,
    model: &mut Option<M>,
    request: &SelfIterationModelRequestV1,
    failure: &SelfIterationModelFailureV1,
) -> Result<(), AgentdError> {
    if pending_model
        .as_ref()
        .is_some_and(|pending| pending.request_id == request.request_id)
    {
        let pending = pending_model
            .as_mut()
            .ok_or_else(|| invalid("actual model task missing"))?;
        let (returned, result) = (&mut pending.task)
            .await
            .map_err(|error| invalid(format!("actual model task: {error}")))?;
        *pending_model = None;
        *model = Some(returned);
        if !matches!(result, Err(AgentdError::SelfIterationModelFailed {role,facts_digest})
            if role == failure.role as u8 && facts_digest == failure.facts_digest.to_string())
        {
            return Err(invalid(
                "owned model task differs from durable actual failure",
            ));
        }
    }
    Ok(())
}

impl<M, A, O> AgentdSelfIterationModelCycleV1<M, A, O>
where
    M: SelfIterationModelPortV1,
    A: AgentdSelfIterationCandidateAssemblerV1,
    O: AgentdSelfIterationIndependentOwnersV1,
{
    /// Observe a cold terminal even after the original deadline. This never
    /// reserves, reissues, constructs a candidate or restores result authority.
    pub async fn reconcile_failed_model(
        &mut self,
        request: SelfIterationModelRequestV1,
    ) -> Result<Option<SelfIterationModelFailureV1>, AgentdError> {
        let current = self
            .runtime
            .inspect_current_round()
            .await?
            .ok_or_else(|| invalid("model failure lacks original round"))?;
        let stage = current
            .status
            .model_stages
            .get(request.role as usize)
            .ok_or_else(|| invalid("model failure lacks original admitted stage"))?;
        if stage.request_digest != self_iteration_model_request_digest_v1(&request)
            || request.request_id
                != current
                    .status
                    .round
                    .model_request_id(request.role, request.candidate_digest)?
            || request.envelope_digest != current.status.round.execution_envelope_digest()
            || request.deadline_ms != current.status.round.deadline_ms()
        {
            return Err(invalid(
                "failure observation changed original admitted request",
            ));
        }
        if let Some(fact) = &stage.failure {
            let failure = SelfIterationModelFailureV1 {
                request_id: request.request_id.clone(),
                role: request.role,
                envelope_digest: request.envelope_digest,
                candidate_digest: request.candidate_digest,
                kind: fact.kind.clone(),
                native_run_digest: fact.native_run_digest,
                provider_failure_digest: fact.provider_failure_digest,
                facts_digest: fact.facts_digest,
                observed_at_ms: fact.observed_at_ms,
                authority: codex_hepta_agent_components::types::AuthorityPosture::DENY_ALL,
            };
            failure
                .validate(&request)
                .map_err(|e| invalid(e.to_string()))?;
            return Ok(Some(failure));
        }
        if stage.output_digest.is_some() {
            return Ok(None);
        }
        let Some(model) = self.model.as_mut() else {
            return Ok(None);
        };
        let Some(failure) = model
            .observe_failed(&request)
            .await
            .map_err(|e| invalid(format!("readonly model failure observation: {e}")))?
        else {
            return Ok(None);
        };
        failure
            .validate(&request)
            .map_err(|e| invalid(e.to_string()))?;
        self.runtime
            .complete_failed_model(current.status.round, request, failure.clone())
            .await?;
        Ok(Some(failure))
    }
}

pub(super) async fn assess<M: SelfIterationModelPortV1>(
    model: &mut M,
    runtime: &AgentdSelfIterationHandleV1,
    round: AgentdSelfIterationRoundV1,
    request: SelfIterationModelRequestV1,
) -> Result<SelfIterationModelAssessmentV1, AgentdError> {
    let assessment =
        match model.assess(request.clone()).await {
            Ok(assessment) => assessment,
            Err(error) => {
                // An error string does not prove terminality. Only the original
                // native owner joined to independently protected failure facts can.
                if let Some(failure) = model.observe_failed(&request).await.map_err(|error| {
                    invalid(format!("readonly model failure observation: {error}"))
                })? {
                    failure
                        .validate(&request)
                        .map_err(|e| invalid(e.to_string()))?;
                    runtime
                        .complete_failed_model(round, request, failure.clone())
                        .await?;
                    return Err(failure_error(&failure));
                }
                return Err(invalid(format!("model assessment: {error}")));
            }
        };
    assessment
        .validate(&request)
        .map_err(|e| invalid(e.to_string()))?;
    runtime
        .complete_model(round, request, assessment.clone())
        .await?;
    Ok(assessment)
}
