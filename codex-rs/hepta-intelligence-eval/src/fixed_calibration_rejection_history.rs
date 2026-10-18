//! Read a completed calibration veto as history, never as current admission.
use super::*;
use serde::Serialize;

#[derive(Clone, Debug, Serialize)]
pub struct HistoricalCalibrationRejectionV1 {
    schema: &'static str,
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

fn validate_completion(
    completion: &Value,
    config_digest: Digest32,
    current_request: &Value,
    result_digest: Digest32,
    now: u64,
) -> HostResult<u64> {
    let completed = completion["completed_at_ms"]
        .as_u64()
        .ok_or("completion time")?;
    let started = completion["native_started_at_ms"]
        .as_u64()
        .ok_or("original cycle time")?;
    if completion["schema"] != "hepta.fixed-calibration-cycle.completed.v1"
        || completion["scope"] != "calibration-only"
        || completion["config_digest"] != config_digest.to_string()
        || completion["independent_result_digest"] != result_digest.to_string()
        || completion["original_inputs"] != *current_request
        || completion["qualified"] != false
        || completion["holdout_consumed"] != false
        || completion["production_activation"] != false
        || completion["authority_grants_any"] != false
        || completed == 0
        || started == 0
        || started > completed
        || completed > now
    {
        return Err("original completed calibration history binding".into());
    }
    Ok(completed)
}

/// Root verifies the original protected policy, executable, result and ledger
/// at their completed historical timestamp. This type exports only bounded
/// counts/digests and explicitly grants no current authentication or effect.
/// No private key, task labels or final-holdout file is opened by this reader.
pub fn inspect_completed_calibration_rejection(
    config_path: &Path,
    expected_config: Digest32,
    expected_completion: Digest32,
) -> HostResult<HistoricalCalibrationRejectionV1> {
    root_boundary()?;
    if expected_config.is_zero() || expected_completion.is_zero() {
        return Err("original calibration history pins required".into());
    }
    let config_bytes = read_root_review_input(config_path, 32 * 1024)?;
    if Digest32::of_bytes(&config_bytes) != expected_config {
        return Err("original calibration config changed".into());
    }
    let config: Config = serde_json::from_slice(&config_bytes)?;
    if config.schema != "hepta.fixed-calibration-cycle-config.v1" {
        return Err("completed fixed cycle required".into());
    }
    let current: Value =
        serde_json::from_slice(&source(&config.current_custody_request, 32 * 1024)?)?;
    let original: Value =
        serde_json::from_slice(&source(&config.original_custody_request, 32 * 1024)?)?;
    let old_eval: Value =
        serde_json::from_slice(&source(&config.original_evaluator_config, 32 * 1024)?)?;
    let eval_bytes = source(&config.current_evaluator_config, 32 * 1024)?;
    let new_eval: Value = serde_json::from_slice(&eval_bytes)?;
    let custody = Digest32::of_bytes(&source(&config.custody_program, 128 * 1024 * 1024)?);
    let evaluator = Digest32::of_bytes(&source(&config.evaluator_program, 128 * 1024 * 1024)?);
    validate_requests(
        &original, &current, &old_eval, &new_eval, custody, evaluator,
    )?;
    let completion_path = config.phase_directory.join("completion.json");
    let completion_bytes = read_root_review_input(&completion_path, 256 * 1024)?;
    if Digest32::of_bytes(&completion_bytes) != expected_completion {
        return Err("original calibration completion changed".into());
    }
    let completion: Value = serde_json::from_slice(&completion_bytes)?;
    let result_path = config.phase_directory.join("evaluator.stdout.json");
    let result = read_root_review_input(&result_path, 64 * 1024)?;
    let result_digest = Digest32::of_bytes(&result);
    let completed = validate_completion(
        &completion,
        expected_config,
        &current,
        result_digest,
        now_ms()?,
    )?;
    let approval: Value =
        serde_json::from_slice(&source(&config.current_program_approval, 16 * 1024)?)?;
    if approval["effective_at_ms"]
        .as_u64()
        .is_none_or(|at| at > completed)
        || approval["expires_at_ms"]
            .as_u64()
            .is_none_or(|at| completed >= at)
    {
        return Err("original approval was not effective at completion".into());
    }
    // This verification is explicitly historical. The returned value below
    // discards the old 'current' predicate and cannot qualify a new execution.
    let verified = read_fixed_calibration_result(&eval_bytes, evaluator, &result, completed)?;
    if verified["state"] != "rejected"
        || verified["current_authentication"] != true
        || verified != completion["independent_evaluation"]
    {
        return Err("original independent signed rejection did not authenticate".into());
    }
    let signed = &verified["original_signed_result"];
    let number = |name| signed[name].as_u64().ok_or("bounded historical count");
    let pairs = number("labeled_pairs")?;
    let candidate = number("candidate_correct")?;
    let baseline = number("baseline_correct")?;
    if !(1..=4096).contains(&pairs) || candidate > pairs || baseline > pairs {
        return Err("historical calibration count bounds".into());
    }
    for (path, maximum, expected) in [
        (completion_path.as_path(), 256 * 1024, expected_completion),
        (result_path.as_path(), 64 * 1024, result_digest),
        (config_path, 32 * 1024, expected_config),
    ] {
        if Digest32::of_bytes(&read_root_review_input(path, maximum)?) != expected {
            return Err("original rejection source changed during historical read".into());
        }
    }
    Ok(HistoricalCalibrationRejectionV1 {
        schema: "hepta.historical-calibration-rejection.v1",
        config_digest: expected_config.to_string(),
        completion_digest: expected_completion.to_string(),
        result_digest: result_digest.to_string(),
        objective_digest: new_eval["objective_digest"]
            .as_str()
            .ok_or("objective")?
            .parse::<Digest32>()?
            .to_string(),
        candidate_weights_digest: new_eval["candidate_weights_digest"]
            .as_str()
            .ok_or("candidate")?
            .parse::<Digest32>()?
            .to_string(),
        baseline_weights_digest: new_eval["baseline_weights_digest"]
            .as_str()
            .ok_or("baseline")?
            .parse::<Digest32>()?
            .to_string(),
        dataset_digest: signed["dataset_digest"]
            .as_str()
            .ok_or("dataset")?
            .parse::<Digest32>()?
            .to_string(),
        completed_at_ms: completed,
        labeled_pairs: pairs,
        candidate_correct: candidate,
        baseline_correct: baseline,
        qualified: false,
        current_authentication: false,
        authority_grants_any: false,
        holdout_consumed: false,
        production_activation: false,
    })
}

#[cfg(test)]
#[path = "fixed_calibration_rejection_history_tests.rs"]
mod tests;
