//! Bounded original round observation codec; authenticated transport supplies origin.
use super::*;

/// Read-only projection from the original reserved round. It grants no model,
/// custody, publication or result-use authority to the requester.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentdSelfIterationRoundStatusV1 {
    pub round: AgentdSelfIterationRoundV1,
    #[serde(with = "super::super::codec::optional_digest")]
    pub frozen_digest: Option<Digest32>,
    #[serde(with = "super::super::codec::optional_stable_id")]
    pub generator_request_id: Option<StableId>,
    #[serde(with = "super::super::codec::optional_digest")]
    pub generator_model_request_digest: Option<Digest32>,
    pub generator_output: Option<String>,
    pub maximum_policy_candidates: u32,
    pub admitted_policy_candidates: u32,
    pub policy_admitted_at_ms: u64,
    pub policy_deadline_ms: u64,
    pub observed_clock_ms: u64,
    pub candidate_effects: AgentdSelfIterationCandidateEffectsV1,
    #[serde(with = "super::super::codec::optional_digest")]
    pub generator_native_run_digest: Option<Digest32>,
    #[serde(with = "super::super::codec::optional_digest")]
    pub generator_output_digest: Option<Digest32>,
    pub terminal: bool,
    pub rejected_proposal: Option<AgentdSelfIterationProposalRejectionV1>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub model_stages: Vec<AgentdSelfIterationModelStageStatusV1>,
}

impl AgentdSelfIterationRoundStatusV1 {
    pub fn to_json(&self) -> Result<String, AgentdError> {
        self.validate()?;
        let json = serde_json::to_string(self).map_err(|error| invalid(error.to_string()))?;
        if json.len() as u64 > crate::MAX_CONTROL_FRAME_BYTES {
            return Err(invalid("whole round status exceeds control frame"));
        }
        Ok(json)
    }
    pub fn from_json(json: &str) -> Result<Self, AgentdError> {
        if json.is_empty() || json.len() as u64 > crate::MAX_CONTROL_FRAME_BYTES {
            return Err(invalid("round status byte bound"));
        }
        let status: Self =
            serde_json::from_str(json).map_err(|error| invalid(error.to_string()))?;
        if status.to_json()? != json {
            return Err(invalid("noncanonical original round status"));
        }
        Ok(status)
    }
    fn validate(&self) -> Result<(), AgentdError> {
        self.round.validate()?;
        super::model_status::validate(self)?;
        if self.maximum_policy_candidates == 0
            || self.maximum_policy_candidates > 32
            || self.admitted_policy_candidates < self.round.candidate_admissions()
            || self.admitted_policy_candidates > self.maximum_policy_candidates
            || self.policy_admitted_at_ms == 0
            || self.policy_admitted_at_ms > self.round.admitted_at_ms()
            || self.policy_deadline_ms != self.round.deadline_ms()
            || self.observed_clock_ms < self.round.admitted_at_ms()
            || self.generator_request_id.is_some() != self.generator_model_request_digest.is_some()
            || self
                .generator_model_request_digest
                .is_some_and(Digest32::is_zero)
            || self.generator_request_id.as_ref().is_some_and(|id| {
                self.round
                    .model_request_id(SelfIterationModelRoleV1::Generator, None)
                    .ok()
                    .as_ref()
                    != Some(id)
            })
            || self.generator_output.is_some() != self.generator_native_run_digest.is_some()
            || self.generator_output_digest
                != self
                    .generator_output
                    .as_ref()
                    .map(|output| Digest32::of_bytes(output.as_bytes()))
            || self
                .generator_output
                .as_ref()
                .is_some_and(|output| output.is_empty() || output.len() > 8192)
            || self
                .generator_native_run_digest
                .is_some_and(Digest32::is_zero)
            || self.generator_output.is_some() && self.generator_request_id.is_none()
            || self.frozen_digest.is_some() && self.generator_native_run_digest.is_none()
            || self.frozen_digest.is_some_and(Digest32::is_zero)
            || self.rejected_proposal.is_some()
                && (!self.terminal
                    || self.frozen_digest.is_some()
                    || self.candidate_effects != AgentdSelfIterationCandidateEffectsV1::NotStarted)
        {
            return Err(invalid("original round observation tuple"));
        }
        Ok(())
    }
}
impl RoundJournal {
    pub(in crate::self_iteration) fn status(
        &self,
        goal: &StableId,
        policy: Digest32,
    ) -> Result<AgentdSelfIterationRoundStatusV1, AgentdError> {
        let current = self
            .current
            .as_ref()
            .ok_or_else(|| invalid("round not reserved"))?;
        if current.permit.goal != goal.as_str() || current.permit.policy != policy {
            return Err(invalid("read-only round Goal or policy differs"));
        }
        let generator = current.stages.first();
        let window = self
            .windows
            .iter()
            .find(|window| window.policy == policy)
            .ok_or_else(|| invalid("round lacks original policy window"))?;
        Ok(AgentdSelfIterationRoundStatusV1 {
            round: current.permit.clone(),
            frozen_digest: current.frozen,
            generator_request_id: generator
                .map(|_| {
                    current
                        .permit
                        .model_request_id(SelfIterationModelRoleV1::Generator, None)
                })
                .transpose()?,
            generator_model_request_digest: generator.map(|stage| stage.request),
            generator_output: generator.and_then(|stage| stage.output.clone()),
            maximum_policy_candidates: window.maximum,
            admitted_policy_candidates: window.admitted,
            policy_admitted_at_ms: window.admitted_at_ms,
            policy_deadline_ms: window.deadline_ms,
            observed_clock_ms: self.watermark_ms,
            candidate_effects: current
                .candidate_effects
                .unwrap_or(AgentdSelfIterationCandidateEffectsV1::LegacyUnknown),
            generator_native_run_digest: generator.and_then(|stage| stage.native_run),
            generator_output_digest: generator
                .and_then(|stage| stage.output.as_ref())
                .map(|output| Digest32::of_bytes(output.as_bytes())),
            terminal: current.terminal,
            rejected_proposal: current.rejected_proposal.as_ref().map(|fact| fact.reason),
            model_stages: super::model_status::project(current)?,
        })
    }
}
