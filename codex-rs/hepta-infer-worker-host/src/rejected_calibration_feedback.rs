//! Installed historical veto feedback under the existing serial model owner.
use super::calibration_reference_batch::storage::SourceOwnership;
use super::calibration_reference_batch::storage::read_regular;
use super::*;
use codex_hepta_infer_core::SelfIterationModelPortV1;
use codex_hepta_infer_core::SelfIterationModelRequestV1;
use codex_hepta_infer_core::SelfIterationModelRoleV1;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RejectedCalibrationFeedbackConfigV1 {
    pub summary_path: PathBuf,
    pub summary_digest: String,
    pub historical_objective_digest: String,
    pub proposal_receipt_path: PathBuf,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct HistoricalSummary {
    schema: String,
    config_digest: String,
    completion_digest: String,
    result_digest: String,
    objective_digest: String,
    candidate_weights_digest: String,
    baseline_weights_digest: String,
    dataset_digest: String,
    completed_at_ms: u64,
    labeled_pairs: u64,
    candidate_correct: u64,
    baseline_correct: u64,
    qualified: bool,
    current_authentication: bool,
    authority_grants_any: bool,
    holdout_consumed: bool,
    production_activation: bool,
}

pub(super) struct RejectedFeedback {
    config: RejectedCalibrationFeedbackConfigV1,
    summary: HistoricalSummary,
    pin: Digest32,
    host_pin: Digest32,
}

impl RejectedFeedback {
    pub(super) fn open(
        config: RejectedCalibrationFeedbackConfigV1,
        identity: &AgentdIdentity,
        host_pin: Digest32,
    ) -> Result<Self, AgentdError> {
        let pin = parse_digest(&config.summary_digest)?;
        let bytes = read_regular(
            &config.summary_path,
            16 * 1024,
            SourceOwnership::RootProtected,
        )?;
        if Digest32::of_bytes(&bytes) != pin {
            return Err(invalid("historical rejected summary changed"));
        }
        let summary: HistoricalSummary =
            serde_json::from_slice(&bytes).map_err(|error| invalid(error.to_string()))?;
        validate_summary(&summary, &config.historical_objective_digest, now_ms()?)?;
        if !config.proposal_receipt_path.is_absolute()
            || !config
                .proposal_receipt_path
                .starts_with(&identity.home_root)
            || config.proposal_receipt_path.file_name().is_none()
        {
            return Err(invalid(
                "rejection proposal receipt must be in the original Agent home",
            ));
        }
        private_parent(&config.proposal_receipt_path)?;
        Ok(Self {
            config,
            summary,
            pin,
            host_pin,
        })
    }

    pub(super) async fn run_step<M: SelfIterationModelPortV1>(
        &self,
        model: &mut M,
        installed: &SelfIterationHostConfigV1,
        identity: &AgentdIdentity,
    ) -> Result<serde_json::Value, AgentdError> {
        let path = &self.config.proposal_receipt_path;
        // An admitted or uncertain native call is not replayed under a new
        // request/deadline after process restart. Existing native maintenance
        // retains and reconciles its original journal record.
        match std::fs::symlink_metadata(path) {
            Ok(_) => {
                let bytes = read_regular(path, 32 * 1024, SourceOwnership::PrivateOwner)?;
                let receipt: serde_json::Value =
                    serde_json::from_slice(&bytes).map_err(|error| invalid(error.to_string()))?;
                validate_receipt(&receipt, &self.summary, self.pin, self.host_pin, identity)?;
                return Ok(receipt);
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
        let now = now_ms()?;
        let request = request(
            installed,
            identity,
            &self.summary,
            self.pin,
            self.host_pin,
            now,
        )?;
        let mut receipt = serde_json::json!({
            "schema":"hepta.rejected-calibration-next-proposal.v1",
            "history_digest":self.pin.to_string(), "host_config_digest":self.host_pin.to_string(),
            "agent_id":identity.agent_id.to_string(), "worker_generation":identity.spawn_generation,
            "request_id":request.request_id.to_string(), "original_deadline_ms":request.deadline_ms,
            "historical_rejection":self.summary, "state":"admitted_native_proposal",
            "qualified":false, "current_authentication":false,
            "authority_grants_any":false, "holdout_consumed":false,"production_activation":false,
        });
        publish_status(path, &receipt)?;
        // The production port owns its current UnixFinalUseAuthorizer and
        // physical execution journal. Historical E evidence issues no grant.
        match model.assess(request.clone()).await {
            Ok(assessment) => {
                assessment
                    .validate(&request)
                    .map_err(|error| invalid(error.to_string()))?;
                receipt["state"] = serde_json::json!("rejected_candidate_next_proposal_observed");
                receipt["model_output"] = serde_json::json!(assessment.model_output);
                receipt["native_run_digest"] =
                    serde_json::json!(assessment.native_run_digest.to_string());
            }
            Err(error) => {
                receipt["state"] = serde_json::json!("pending_original_native_proposal");
                receipt["diagnostic"] =
                    serde_json::json!(error.to_string().chars().take(2048).collect::<String>());
            }
        }
        publish_status(path, &receipt)?;
        Ok(receipt)
    }
}

fn now_ms() -> Result<u64, AgentdError> {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|error| invalid(error.to_string()))?
        .as_millis()
        .try_into()
        .map_err(|_| invalid("historical feedback clock overflow"))
}

fn validate_summary(
    summary: &HistoricalSummary,
    objective: &str,
    now: u64,
) -> Result<(), AgentdError> {
    if summary.schema != "hepta.historical-calibration-rejection.v1"
        || summary.objective_digest != objective
        || summary.completed_at_ms == 0
        || summary.completed_at_ms > now
        || !(1..=4096).contains(&summary.labeled_pairs)
        || summary.candidate_correct > summary.labeled_pairs
        || summary.baseline_correct > summary.labeled_pairs
        || summary.qualified
        || summary.current_authentication
        || summary.authority_grants_any
        || summary.holdout_consumed
        || summary.production_activation
    {
        return Err(invalid(
            "historical rejection cannot provide current qualification",
        ));
    }
    for digest in [
        &summary.config_digest,
        &summary.completion_digest,
        &summary.result_digest,
        &summary.objective_digest,
        &summary.candidate_weights_digest,
        &summary.baseline_weights_digest,
        &summary.dataset_digest,
    ] {
        parse_digest(digest)?;
    }
    Ok(())
}

fn validate_receipt(
    receipt: &serde_json::Value,
    summary: &HistoricalSummary,
    pin: Digest32,
    host_pin: Digest32,
    identity: &AgentdIdentity,
) -> Result<(), AgentdError> {
    if receipt["schema"] != "hepta.rejected-calibration-next-proposal.v1"
        || receipt["history_digest"] != pin.to_string()
        || receipt["host_config_digest"] != host_pin.to_string()
        || receipt["agent_id"] != identity.agent_id.to_string()
        || receipt["historical_rejection"]
            != serde_json::to_value(summary).map_err(|error| invalid(error.to_string()))?
        || receipt["worker_generation"]
            .as_u64()
            .is_none_or(|generation| generation == 0 || generation > identity.spawn_generation)
        || !matches!(
            receipt["state"].as_str(),
            Some(
                "admitted_native_proposal"
                    | "pending_original_native_proposal"
                    | "rejected_candidate_next_proposal_observed"
            )
        )
        || receipt["original_deadline_ms"]
            .as_u64()
            .is_none_or(|at| at == 0)
        || receipt["request_id"]
            != format!(
                "iteration.rejected.{}",
                request_binding(pin, host_pin, identity)
            )
        || receipt["qualified"] != false
        || receipt["current_authentication"] != false
        || receipt["authority_grants_any"] != false
        || receipt["holdout_consumed"] != false
        || receipt["production_activation"] != false
    {
        return Err(invalid(
            "original rejected feedback proposal receipt changed",
        ));
    }
    if receipt["state"] == "rejected_candidate_next_proposal_observed"
        && (receipt["native_run_digest"]
            .as_str()
            .is_none_or(|value| parse_digest(value).is_err())
            || receipt["model_output"]
                .as_str()
                .is_none_or(|value| value.is_empty() || value.len() > 8 * 1024))
    {
        return Err(invalid(
            "observed proposal lacks its original native result",
        ));
    }
    Ok(())
}

fn request_binding(pin: Digest32, host_pin: Digest32, identity: &AgentdIdentity) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.installed.rejected-calibration-next-proposal.v1",
        pin.as_array(),
        host_pin.as_array(),
        identity.agent_id.to_string().as_bytes(),
    ])
}

fn request(
    installed: &SelfIterationHostConfigV1,
    identity: &AgentdIdentity,
    summary: &HistoricalSummary,
    pin: Digest32,
    host_pin: Digest32,
    now: u64,
) -> Result<SelfIterationModelRequestV1, AgentdError> {
    let binding = request_binding(pin, host_pin, identity);
    let request = SelfIterationModelRequestV1 {
        request_id: StableId::new(format!("iteration.rejected.{binding}"))
            .map_err(|error| invalid(error.to_string()))?,
        role: SelfIterationModelRoleV1::Generator,
        envelope_digest: binding,
        candidate_digest: None,
        prompt: format!(
            "Generate the next bounded candidate and a concrete training/evaluation plan.\nObjective: {}\nOriginal independently verified calibration rejection: candidate {} correct, baseline {} correct, {} pairs; candidate weights {}; baseline weights {}; dataset {}; original result {}.\nThis result is historical and grants no current qualification. Keep the currently installed baseline serving. Use a fresh preregistered disjoint cut from the public training source; do not read or rerun the original 99 calibration or 72 reserved holdout. Do not claim a new candidate was trained, evaluated, selected or installed. Only the current physical model authorizer permits this advisory turn. Return bounded candidate parameters and the next independent evaluation inputs.",
            installed.objective_prompt,
            summary.candidate_correct,
            summary.baseline_correct,
            summary.labeled_pairs,
            summary.candidate_weights_digest,
            summary.baseline_weights_digest,
            summary.dataset_digest,
            summary.result_digest,
        ),
        deadline_ms: now
            .checked_add(
                installed
                    .proposal_timeout_seconds
                    .checked_mul(1000)
                    .ok_or_else(|| invalid("proposal timeout overflow"))?,
            )
            .ok_or_else(|| invalid("proposal deadline overflow"))?,
        maximum_response_bytes: 8 * 1024,
    };
    request
        .validate(now)
        .map_err(|error| invalid(error.to_string()))?;
    Ok(request)
}

#[cfg(test)]
#[path = "rejected_calibration_feedback_tests.rs"]
mod tests;
