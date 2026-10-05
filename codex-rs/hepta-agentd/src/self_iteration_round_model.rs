//! Four bounded model intents, stored by the original round journal.
use super::*;

impl RoundJournal {
    pub(in crate::self_iteration) fn begin(
        &mut self,
        permit: &AgentdSelfIterationRoundV1,
        request: &SelfIterationModelRequestV1,
        now: u64,
    ) -> Result<AgentdSelfIterationModelAdmissionV1, AgentdError> {
        if now < self.watermark_ms {
            return Err(invalid("original model admission clock regressed"));
        }
        let current = self.current_mut(permit)?;
        let role = request.role as usize;
        if request.envelope_digest != permit.execution
            || request.request_id
                != permit.model_request_id(request.role, request.candidate_digest)?
            || request.deadline_ms != permit.deadline_ms
            || request.maximum_response_bytes != 8 * 1024
            || request.role == SelfIterationModelRoleV1::Generator
                && request.candidate_digest.is_some()
            || request.role != SelfIterationModelRoleV1::Generator
                && (current.frozen.is_none() || request.candidate_digest != current.frozen)
        {
            return Err(invalid("model request differs from original round"));
        }
        let digest = request_digest(request);
        if let Some(stage) = current.stages.get(role) {
            if stage.request != digest {
                return Err(invalid("reserved model request changed"));
            }
            if let Some(failure) = &stage.failure {
                return Ok(AgentdSelfIterationModelAdmissionV1::Failed(
                    failure.for_request(request)?,
                ));
            }
            return match (&stage.output, stage.native_run) {
                (Some(output), Some(native_run_digest)) => {
                    Ok(AgentdSelfIterationModelAdmissionV1::Completed(
                        SelfIterationModelAssessmentV1 {
                            request_id: request.request_id.clone(),
                            role: request.role,
                            envelope_digest: request.envelope_digest,
                            candidate_digest: request.candidate_digest,
                            model_output: output.clone(),
                            native_run_digest,
                            authority: AuthorityPosture::DENY_ALL,
                        },
                    ))
                }
                (None, None) => Ok(AgentdSelfIterationModelAdmissionV1::Pending),
                _ => Err(invalid("incomplete actual model terminal receipt")),
            };
        }
        request.validate(now).map_err(|e| invalid(e.to_string()))?;
        if current.terminal
            || current.stages.len() != role
            || current
                .stages
                .last()
                .is_some_and(|stage| stage.output.is_none())
        {
            return Err(invalid("model stage ordering or unresolved prior request"));
        }
        current.stages.push(ModelStage {
            role: role as u8,
            request: digest,
            output: None,
            native_run: None,
            failure: None,
        });
        Ok(AgentdSelfIterationModelAdmissionV1::Fresh)
    }
    pub(in crate::self_iteration) fn complete(
        &mut self,
        permit: &AgentdSelfIterationRoundV1,
        request: &SelfIterationModelRequestV1,
        assessment: &SelfIterationModelAssessmentV1,
    ) -> Result<(), AgentdError> {
        assessment
            .validate(request)
            .map_err(|e| invalid(e.to_string()))?;
        let current = self.current_mut(permit)?;
        let stage = current
            .stages
            .get_mut(request.role as usize)
            .ok_or_else(|| invalid("model request never durably admitted"))?;
        if stage.request != request_digest(request) {
            return Err(invalid(
                "model completion differs from original admitted request",
            ));
        }
        if stage.failure.is_some() {
            return Err(invalid("actual failed model cannot become successful"));
        }
        if let Some(previous) = &stage.output
            && (previous != &assessment.model_output
                || stage.native_run != Some(assessment.native_run_digest))
        {
            return Err(invalid("actual terminal model receipt changed"));
        }
        stage.output = Some(assessment.model_output.clone());
        stage.native_run = Some(assessment.native_run_digest);
        Ok(())
    }
}

pub(in crate::self_iteration) fn request_digest(request: &SelfIterationModelRequestV1) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.self-iteration.admitted-model-request.v1",
        request.request_id.as_str().as_bytes(),
        &[request.role as u8],
        request.envelope_digest.as_array(),
        request
            .candidate_digest
            .unwrap_or(Digest32::ZERO)
            .as_array(),
        Digest32::of_bytes(request.prompt.as_bytes()).as_array(),
        &request.deadline_ms.to_be_bytes(),
        &request.maximum_response_bytes.to_be_bytes(),
    ])
}
