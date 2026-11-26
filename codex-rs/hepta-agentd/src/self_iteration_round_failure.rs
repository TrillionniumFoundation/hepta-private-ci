//! Compact terminal facts live in the original round journal, never a second ledger.
use super::*;
use codex_hepta_agent_components::infer_core::SelfIterationModelFailureKindV1;

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ModelFailure {
    kind: SelfIterationModelFailureKindV1,
    #[serde(with = "super::super::codec::digest")]
    native_run_digest: Digest32,
    #[serde(with = "super::super::codec::digest")]
    provider_failure_digest: Digest32,
    #[serde(with = "super::super::codec::digest")]
    facts_digest: Digest32,
    observed_at_ms: u64,
}
impl ModelFailure {
    pub(super) fn observation(&self) -> AgentdSelfIterationModelFailureStatusV1 {
        AgentdSelfIterationModelFailureStatusV1 {
            kind: self.kind.clone(),
            native_run_digest: self.native_run_digest,
            provider_failure_digest: self.provider_failure_digest,
            facts_digest: self.facts_digest,
            observed_at_ms: self.observed_at_ms,
        }
    }
    pub(super) fn validate(&self, admitted: u64, watermark: u64) -> Result<(), AgentdError> {
        if self.native_run_digest.is_zero()
            || self.provider_failure_digest.is_zero()
            || self.facts_digest.is_zero()
            || self.observed_at_ms < admitted
            || self.observed_at_ms > watermark
            || matches!(self.kind, SelfIterationModelFailureKindV1::HttpRejection { status }
                if !(100..=599).contains(&status) || (200..=299).contains(&status))
        {
            return Err(invalid("original failed model terminal tuple"));
        }
        Ok(())
    }
    pub(super) fn for_request(
        &self,
        request: &SelfIterationModelRequestV1,
    ) -> Result<SelfIterationModelFailureV1, AgentdError> {
        let result = SelfIterationModelFailureV1 {
            request_id: request.request_id.clone(),
            role: request.role,
            envelope_digest: request.envelope_digest,
            candidate_digest: request.candidate_digest,
            kind: self.kind.clone(),
            native_run_digest: self.native_run_digest,
            provider_failure_digest: self.provider_failure_digest,
            facts_digest: self.facts_digest,
            observed_at_ms: self.observed_at_ms,
            authority: AuthorityPosture::DENY_ALL,
        };
        result
            .validate(request)
            .map_err(|e| invalid(e.to_string()))?;
        Ok(result)
    }
}
impl ModelStage {
    pub(super) fn pending(&self) -> bool {
        self.output.is_none() && self.failure.is_none()
    }
}
pub(super) fn failed_before_candidate_effects(current: &RoundState) -> bool {
    current.terminal
        && current.frozen.is_none()
        && current.rejected_proposal.is_none()
        && current.candidate_effects == Some(AgentdSelfIterationCandidateEffectsV1::NotStarted)
        && current.stages.len() == 1
        && current.stages[0].failure.is_some()
}
impl RoundJournal {
    pub(in crate::self_iteration) fn complete_failed(
        &mut self,
        permit: &AgentdSelfIterationRoundV1,
        request: &SelfIterationModelRequestV1,
        failure: &SelfIterationModelFailureV1,
    ) -> Result<(), AgentdError> {
        failure
            .validate(request)
            .map_err(|e| invalid(e.to_string()))?;
        let watermark = self.watermark_ms;
        let current = self.current_mut(permit)?;
        let fact = ModelFailure {
            kind: failure.kind.clone(),
            native_run_digest: failure.native_run_digest,
            provider_failure_digest: failure.provider_failure_digest,
            facts_digest: failure.facts_digest,
            observed_at_ms: failure.observed_at_ms,
        };
        fact.validate(permit.admitted_at_ms, watermark)?;
        let role = request.role as usize;
        let stage = current
            .stages
            .get(role)
            .ok_or_else(|| invalid("failed model request never durably admitted"))?;
        if stage.request != model::request_digest(request)
            || stage.output.is_some()
            || stage.native_run.is_some()
            || stage
                .failure
                .as_ref()
                .is_some_and(|previous| previous != &fact)
        {
            return Err(invalid(
                "actual failure differs from admitted model request",
            ));
        }
        if request.role == SelfIterationModelRoleV1::Generator {
            if current.frozen.is_some()
                || current.rejected_proposal.is_some()
                || current.candidate_effects
                    != Some(AgentdSelfIterationCandidateEffectsV1::NotStarted)
                || current.stages.len() != 1
            {
                return Err(invalid(
                    "Generator failure cannot retire started candidate effects",
                ));
            }
            current.terminal = true;
        }
        current.stages[role].failure = Some(fact);
        Ok(())
    }
}
