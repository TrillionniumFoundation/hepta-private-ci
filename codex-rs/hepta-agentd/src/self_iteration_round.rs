//! Round and model intent share the original iteration journal and lease.
use super::*;
use codex_hepta_agent_components::infer_core::SelfIterationModelAssessmentV1;
use codex_hepta_agent_components::infer_core::SelfIterationModelFailureV1;
use codex_hepta_agent_components::infer_core::SelfIterationModelRequestV1;
use codex_hepta_agent_components::infer_core::SelfIterationModelRoleV1;
use codex_hepta_agent_components::types::AuthorityPosture;
use codex_hepta_agent_components::types::StableId;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentdSelfIterationRoundV1 {
    goal: String,
    ordinal: u64,
    candidate_admissions: u32,
    #[serde(with = "super::codec::digest")]
    policy: Digest32,
    #[serde(with = "super::codec::digest")]
    execution: Digest32,
    admitted_at_ms: u64,
    deadline_ms: u64,
}
impl AgentdSelfIterationRoundV1 {
    pub fn goal_id(&self) -> &str {
        &self.goal
    }
    pub fn ordinal(&self) -> u64 {
        self.ordinal
    }
    pub fn candidate_admissions(&self) -> u32 {
        self.candidate_admissions
    }
    pub fn admitted_at_ms(&self) -> u64 {
        self.admitted_at_ms
    }
    pub fn execution_envelope_digest(&self) -> Digest32 {
        self.execution
    }
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, AgentdError> {
        self.validate()?;
        serde_json::to_vec(self).map_err(|error| invalid(error.to_string()))
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, AgentdError> {
        if bytes.is_empty() || bytes.len() > 4096 {
            return Err(invalid("signed original round byte bound"));
        }
        let round: Self =
            serde_json::from_slice(bytes).map_err(|error| invalid(error.to_string()))?;
        if round.canonical_bytes()? != bytes {
            return Err(invalid("noncanonical original signed round"));
        }
        Ok(round)
    }
    pub fn canonical_policy_digest(&self) -> Digest32 {
        self.policy
    }
    pub fn deadline_ms(&self) -> u64 {
        self.deadline_ms
    }
    pub fn identity_digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.self-iteration.round.v1",
            self.goal.as_bytes(),
            &self.ordinal.to_be_bytes(),
            &self.candidate_admissions.to_be_bytes(),
            self.policy.as_array(),
            self.execution.as_array(),
            &self.admitted_at_ms.to_be_bytes(),
            &self.deadline_ms.to_be_bytes(),
        ])
    }
    pub fn model_request_id(
        &self,
        role: SelfIterationModelRoleV1,
        candidate: Option<Digest32>,
    ) -> Result<StableId, AgentdError> {
        let identity = Digest32::of_parts(&[
            b"hepta.self-iteration.model-request.v2",
            self.identity_digest().as_array(),
            &[role as u8],
            candidate.unwrap_or(Digest32::ZERO).as_array(),
        ]);
        StableId::new(format!("iteration.{identity}")).map_err(|e| invalid(e.to_string()))
    }
    fn validate(&self) -> Result<(), AgentdError> {
        if StableId::new(&self.goal).is_err()
            || self.ordinal == 0
            || self.candidate_admissions == 0
            || self.candidate_admissions > 32
            || self.policy.is_zero()
            || self.execution.is_zero()
            || self.admitted_at_ms == 0
            || self.deadline_ms <= self.admitted_at_ms
        {
            return Err(invalid("round identity or durable time bound"));
        }
        Ok(())
    }
}

/// Pending means the original request was admitted; it may not be reissued.
pub enum AgentdSelfIterationModelAdmissionV1 {
    Fresh,
    Pending,
    Completed(SelfIterationModelAssessmentV1),
    Failed(SelfIterationModelFailureV1),
}

#[derive(Clone, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RoundJournal {
    pub(super) ordinal: u64,
    watermark_ms: u64,
    windows: Vec<Window>,
    current: Option<RoundState>,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Window {
    #[serde(with = "super::codec::digest")]
    policy: Digest32,
    expires_at_ms: u64,
    admitted_at_ms: u64,
    deadline_ms: u64,
    maximum: u32,
    admitted: u32,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RoundState {
    permit: AgentdSelfIterationRoundV1,
    #[serde(with = "super::codec::optional_digest")]
    frozen: Option<Digest32>,
    terminal: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    rejected_proposal: Option<rejection::RejectedProposal>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    candidate_effects: Option<AgentdSelfIterationCandidateEffectsV1>,
    stages: Vec<ModelStage>,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ModelStage {
    role: u8,
    #[serde(with = "super::codec::digest")]
    request: Digest32,
    output: Option<String>,
    #[serde(with = "super::codec::optional_digest")]
    native_run: Option<Digest32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    failure: Option<failure::ModelFailure>,
}
impl RoundJournal {
    pub(super) fn validate(&self) -> Result<(), AgentdError> {
        if self.windows.len() > 32 {
            return Err(invalid("concurrent policy window limit"));
        }
        for (index, window) in self.windows.iter().enumerate() {
            if window.policy.is_zero()
                || window.maximum == 0
                || window.maximum > 32
                || window.admitted == 0
                || window.admitted > window.maximum
                || window.expires_at_ms == 0
                || window.admitted_at_ms == 0
                || window.deadline_ms <= window.admitted_at_ms
                || window.deadline_ms > window.expires_at_ms
                || self.windows[..index]
                    .iter()
                    .any(|previous| previous.policy == window.policy)
            {
                return Err(invalid("durable canonical policy quota"));
            }
        }
        if let Some(current) = &self.current {
            current.permit.validate()?;
            if current.permit.ordinal != self.ordinal
                || current.permit.admitted_at_ms > self.watermark_ms
                || current.stages.len() > 4
                || current.frozen.is_some_and(Digest32::is_zero)
                || current.terminal
                    && current.frozen.is_none()
                    && current.rejected_proposal.is_none()
                    && !failure::failed_before_candidate_effects(current)
            {
                return Err(invalid("durable round state"));
            }
            if let Some(rejection) = &current.rejected_proposal {
                rejection.validate(current)?;
            }
            if !self.windows.iter().any(|window| {
                window.policy == current.permit.policy
                    && window.admitted >= current.permit.candidate_admissions
                    && window.deadline_ms == current.permit.deadline_ms
                    && current.permit.admitted_at_ms >= window.admitted_at_ms
            }) {
                return Err(invalid("round lacks original aggregate policy window"));
            }
            for (index, stage) in current.stages.iter().enumerate() {
                if stage.role as usize != index
                    || stage.request.is_zero()
                    || stage.output.is_some() != stage.native_run.is_some()
                    || stage.native_run.is_some_and(Digest32::is_zero)
                    || stage.failure.is_some()
                        && (stage.output.is_some() || stage.native_run.is_some())
                    || stage
                        .output
                        .as_ref()
                        .is_some_and(|output| output.is_empty() || output.len() > 8 * 1024)
                    || index + 1 < current.stages.len() && stage.output.is_none()
                {
                    return Err(invalid("durable model intent or actual terminal receipt"));
                }
                if let Some(failure) = &stage.failure {
                    failure.validate(current.permit.admitted_at_ms, self.watermark_ms)?;
                    if index == 0 && !failure::failed_before_candidate_effects(current) {
                        return Err(invalid("Generator failure cannot retire candidate effects"));
                    }
                }
            }
        } else if self.ordinal != 0 {
            return Err(invalid("round ordinal without original record"));
        }
        Ok(())
    }
    pub(super) fn observe_clock(&mut self, now: u64, command: bool) -> Result<bool, AgentdError> {
        if now < self.watermark_ms {
            return Err(invalid("original round clock regressed"));
        }
        // No periodic idle fsync: retain only the first observed expiry. Actual
        // effect commands retain their clock before admission or rejection.
        let expired = self
            .deadline()
            .is_some_and(|deadline| now >= deadline && self.watermark_ms < deadline);
        if now > self.watermark_ms && (command || expired) {
            self.watermark_ms = now;
            return Ok(true);
        }
        Ok(false)
    }
    pub(super) fn retain_terminal_clock(&mut self, now: u64) {
        self.watermark_ms = self.watermark_ms.max(now);
    }
    pub(super) fn reserve(
        &mut self,
        goal: StableId,
        canonical: &crate::CanonicalIterationEnvelopeV1,
        execution: &IterationEnvelopeV1,
        now: u64,
    ) -> Result<AgentdSelfIterationRoundV1, AgentdError> {
        payload::validate_canonical_execution(canonical, execution)?;
        let policy = canonical.policy();
        if now < self.watermark_ms || now == 0 || now >= policy.expires_unix_ms {
            return Err(invalid("policy window or admission clock expired"));
        }
        if let Some(current) = &self.current
            && (!current.terminal || current.stages.iter().any(ModelStage::pending))
        {
            if current.permit.goal != goal.as_str()
                || current.permit.policy != canonical.digest()
                || current.permit.execution != self_iteration_envelope_digest_v1(execution)
            {
                return Err(invalid(
                    "unresolved round requires exact original Goal and policy",
                ));
            }
            // Candidate rejection cannot retire an unresolved actual model
            // request. Keep its exact reservation until its real terminal is
            // recorded, including after restart; quota and deadline stay fixed.
            return Ok(current.permit.clone());
        }
        // The whole policy window receives one elapsed allowance. Neither a
        // rejected candidate nor a later Goal can obtain a fresh wall budget.
        let initial_deadline = now
            .checked_add(policy.wall_time_micros / 1000)
            .ok_or_else(|| invalid("window deadline overflow"))?
            .min(policy.expires_unix_ms);
        self.windows.retain(|window| window.expires_at_ms > now);
        let window = match self
            .windows
            .iter_mut()
            .find(|window| window.policy == canonical.digest())
        {
            Some(window) => window,
            None => {
                if self.windows.len() >= 32 {
                    return Err(invalid("concurrent policy window limit"));
                }
                self.windows.push(Window {
                    policy: canonical.digest(),
                    expires_at_ms: policy.expires_unix_ms,
                    admitted_at_ms: now,
                    deadline_ms: initial_deadline,
                    maximum: policy.maximum_candidates,
                    admitted: 0,
                });
                self.windows
                    .last_mut()
                    .ok_or_else(|| invalid("policy window missing"))?
            }
        };
        let requested = u32::from(execution.maximum_candidates);
        if window.maximum != policy.maximum_candidates
            || window.expires_at_ms != policy.expires_unix_ms
            || window
                .admitted
                .checked_add(requested)
                .is_none_or(|total| total > window.maximum)
        {
            return Err(invalid(
                "canonical policy aggregate candidate quota exhausted",
            ));
        }
        let deadline_ms = window.deadline_ms;
        if deadline_ms <= now {
            return Err(invalid("canonical policy wall time exhausted"));
        }
        let ordinal = self
            .ordinal
            .checked_add(1)
            .ok_or_else(|| invalid("round ordinal exhausted"))?;
        let permit = AgentdSelfIterationRoundV1 {
            goal: goal.to_string(),
            ordinal,
            candidate_admissions: requested,
            policy: canonical.digest(),
            execution: self_iteration_envelope_digest_v1(execution),
            admitted_at_ms: now,
            deadline_ms,
        };
        window.admitted += requested;
        self.ordinal = ordinal;
        self.watermark_ms = now;
        self.current = Some(RoundState {
            permit: permit.clone(),
            frozen: None,
            terminal: false,
            rejected_proposal: None,
            candidate_effects: Some(AgentdSelfIterationCandidateEffectsV1::NotStarted),
            stages: Vec::new(),
        });
        Ok(permit)
    }
    fn current_mut(
        &mut self,
        permit: &AgentdSelfIterationRoundV1,
    ) -> Result<&mut RoundState, AgentdError> {
        let current = self
            .current
            .as_mut()
            .ok_or_else(|| invalid("round not reserved"))?;
        if current.permit != *permit {
            return Err(invalid("round reservation identity changed"));
        }
        Ok(current)
    }
    pub(super) fn bind_candidate(
        &mut self,
        request: &AgentdSelfIterationCandidateV1,
        frozen: Digest32,
    ) -> Result<(), AgentdError> {
        let Some(canonical) = &request.canonical_envelope else {
            if self.current.as_ref().is_some_and(|round| !round.terminal) {
                return Err(invalid(
                    "reserved canonical round cannot freeze legacy candidate",
                ));
            }
            return Ok(());
        };
        let current = self
            .current
            .as_mut()
            .ok_or_else(|| invalid("canonical candidate has no original round reservation"))?;
        let assessment = request
            .model_assessment
            .as_ref()
            .ok_or_else(|| invalid("candidate lacks actual Generator receipt"))?;
        if current.rejected_proposal.is_some() {
            return Err(invalid(
                "no-candidate rejected round cannot freeze a candidate",
            ));
        }
        let generator = current
            .stages
            .first()
            .ok_or_else(|| invalid("Generator request was not admitted"))?;
        if request.round.as_ref() != Some(&current.permit)
            || current.permit.policy != canonical.digest()
            || current.permit.execution != self_iteration_envelope_digest_v1(&request.envelope)
            || assessment.request_id
                != current
                    .permit
                    .model_request_id(SelfIterationModelRoleV1::Generator, None)?
            || generator.output.as_deref() != Some(assessment.model_output.as_str())
            || generator.native_run != Some(assessment.native_run_digest)
            || current.frozen.is_some_and(|previous| previous != frozen)
        {
            return Err(invalid(
                "candidate changed original canonical round or actual Generator receipt",
            ));
        }
        current.frozen = Some(frozen);
        Ok(())
    }
    pub(super) fn deadline(&self) -> Option<u64> {
        self.current
            .as_ref()
            .filter(|round| !round.terminal)
            .map(|round| round.permit.deadline_ms)
    }
    pub(super) fn record_phase(
        &mut self,
        record: &AgentdSelfIterationRecordV1,
    ) -> Result<(), AgentdError> {
        if let Some(current) = &mut self.current
            && current.frozen == Some(record.frozen_digest)
        {
            current.terminal = matches!(
                record.phase,
                AgentdSelfIterationPhaseV1::Accepted
                    | AgentdSelfIterationPhaseV1::RolledBack
                    | AgentdSelfIterationPhaseV1::Rejected
            );
        }
        Ok(())
    }
}
#[path = "self_iteration_round_effects.rs"]
mod effects;
#[path = "self_iteration_round_status.rs"]
mod status_codec;
pub use status_codec::AgentdSelfIterationRoundStatusV1;
#[path = "self_iteration_round_model_status.rs"]
mod model_status;
pub use model_status::AgentdSelfIterationModelFailureStatusV1;
pub use model_status::AgentdSelfIterationModelStageStatusV1;
#[path = "self_iteration_round_current.rs"]
mod current;
pub use current::AgentdSelfIterationCurrentRoundV1;

#[path = "self_iteration_round_model.rs"]
pub(super) mod model;

#[path = "self_iteration_round_failure.rs"]
mod failure;

#[path = "self_iteration_round_rejection.rs"]
mod rejection;

#[cfg(test)]
#[path = "self_iteration_round_tests.rs"]
mod tests;
