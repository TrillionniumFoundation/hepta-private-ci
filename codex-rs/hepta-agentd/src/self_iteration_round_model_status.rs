//! Bounded projection of admitted model identities from the same original journal.
use super::*;
use codex_hepta_agent_components::infer_core::SelfIterationModelFailureKindV1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentdSelfIterationModelFailureStatusV1 {
    pub kind: SelfIterationModelFailureKindV1,
    #[serde(with = "super::super::codec::digest")]
    pub native_run_digest: Digest32,
    #[serde(with = "super::super::codec::digest")]
    pub provider_failure_digest: Digest32,
    #[serde(with = "super::super::codec::digest")]
    pub facts_digest: Digest32,
    pub observed_at_ms: u64,
}
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentdSelfIterationModelStageStatusV1 {
    pub role: u8,
    pub request_id: String,
    #[serde(with = "super::super::codec::optional_digest")]
    pub candidate_digest: Option<Digest32>,
    #[serde(with = "super::super::codec::digest")]
    pub request_digest: Digest32,
    #[serde(with = "super::super::codec::optional_digest")]
    pub output_digest: Option<Digest32>,
    #[serde(with = "super::super::codec::optional_digest")]
    pub native_run_digest: Option<Digest32>,
    pub failure: Option<AgentdSelfIterationModelFailureStatusV1>,
}
pub(super) fn project(
    current: &RoundState,
) -> Result<Vec<AgentdSelfIterationModelStageStatusV1>, AgentdError> {
    current
        .stages
        .iter()
        .map(|stage| {
            let role = role(stage.role)?;
            let candidate_digest = if role == SelfIterationModelRoleV1::Generator {
                None
            } else {
                current.frozen
            };
            Ok(AgentdSelfIterationModelStageStatusV1 {
                role: stage.role,
                request_digest: stage.request,
                request_id: current
                    .permit
                    .model_request_id(role, candidate_digest)?
                    .to_string(),
                candidate_digest,
                output_digest: stage
                    .output
                    .as_ref()
                    .map(|output| Digest32::of_bytes(output.as_bytes())),
                native_run_digest: stage.native_run,
                failure: stage
                    .failure
                    .as_ref()
                    .map(failure::ModelFailure::observation),
            })
        })
        .collect()
}
pub(super) fn validate(status: &AgentdSelfIterationRoundStatusV1) -> Result<(), AgentdError> {
    if status.model_stages.len() > 4 {
        return Err(invalid("original model stage observation bound"));
    }
    for (index, stage) in status.model_stages.iter().enumerate() {
        if stage.role as usize != index
            || stage.request_digest.is_zero()
            || stage.candidate_digest
                != (if index == 0 {
                    None
                } else {
                    status.frozen_digest
                })
            || stage.request_id
                != status
                    .round
                    .model_request_id(role(stage.role)?, stage.candidate_digest)?
                    .as_str()
            || stage.output_digest.is_some() != stage.native_run_digest.is_some()
            || stage.output_digest.is_some_and(Digest32::is_zero)
            || stage.native_run_digest.is_some_and(Digest32::is_zero)
            || stage.failure.is_some()
                && (stage.output_digest.is_some() || stage.native_run_digest.is_some())
            || index + 1 < status.model_stages.len() && stage.output_digest.is_none()
            || index != 0 && status.frozen_digest.is_none()
        {
            return Err(invalid("original model stage observation tuple or order"));
        }
        if let Some(failure) = &stage.failure
            && (failure.native_run_digest.is_zero()
                || failure.provider_failure_digest.is_zero()
                || failure.facts_digest.is_zero()
                || failure.observed_at_ms < status.round.admitted_at_ms()
                || failure.observed_at_ms > status.observed_clock_ms
                || matches!(failure.kind, SelfIterationModelFailureKindV1::HttpRejection {status}
                    if !(100..=599).contains(&status) || (200..=299).contains(&status))
                || index == 0
                    && (!status.terminal
                        || status.frozen_digest.is_some()
                        || status.rejected_proposal.is_some()
                        || status.candidate_effects
                            != AgentdSelfIterationCandidateEffectsV1::NotStarted))
        {
            return Err(invalid("original failed model observation"));
        }
    }
    if let Some(generator) = status.model_stages.first()
        && (Some(generator.request_digest) != status.generator_model_request_digest
            || Some(generator.request_id.as_str())
                != status.generator_request_id.as_ref().map(StableId::as_str)
            || generator.output_digest != status.generator_output_digest
            || generator.native_run_digest != status.generator_native_run_digest)
    {
        return Err(invalid(
            "Generator summary differs from complete original stage",
        ));
    }
    Ok(())
}

fn role(role: u8) -> Result<SelfIterationModelRoleV1, AgentdError> {
    match role {
        0 => Ok(SelfIterationModelRoleV1::Generator),
        1 => Ok(SelfIterationModelRoleV1::Evaluator),
        2 => Ok(SelfIterationModelRoleV1::Selector),
        3 => Ok(SelfIterationModelRoleV1::Observer),
        _ => Err(invalid("original model role")),
    }
}
