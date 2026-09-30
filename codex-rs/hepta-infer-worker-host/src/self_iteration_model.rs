//! Self-iteration assistance through the actual Agentd/App Server worker.
//! Model assessments carry no owner authority. Final-use grants, terminal
//! correlation and durable execution remain owned by the native driver.

use codex_hepta_infer_core::SelfIterationModelAssessmentV1;
use codex_hepta_infer_core::SelfIterationModelErrorV1;
use codex_hepta_infer_core::SelfIterationModelPortV1;
use codex_hepta_infer_core::SelfIterationModelRequestV1;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use tokio_util::sync::CancellationToken;

use crate::native_app_server::AppServerModelDriver;
use crate::native_app_server::NativeAdmission;

const NATIVE_PROMPT_LIMIT: usize = 32 * 1024;

/// A bounded, durable model port. The caller configures the existing native
/// driver's final-use authorizer; this adapter neither issues grants nor signs
/// evaluation/selection evidence. The journal is retained across all roles.
pub struct AppServerSelfIterationModelPortV1 {
    driver: AppServerModelDriver,
    control: DurableInferenceControl,
    maximum_in_flight: usize,
    cancellation: CancellationToken,
}

impl AppServerSelfIterationModelPortV1 {
    pub fn new(
        driver: AppServerModelDriver,
        control: DurableInferenceControl,
        maximum_in_flight: usize,
        cancellation: CancellationToken,
    ) -> Result<Self, SelfIterationModelErrorV1> {
        if maximum_in_flight == 0 {
            return Err(SelfIterationModelErrorV1::InvalidRequest);
        }
        Ok(Self {
            driver,
            control,
            maximum_in_flight,
            cancellation,
        })
    }
}

impl SelfIterationModelPortV1 for AppServerSelfIterationModelPortV1 {
    async fn assess(
        &mut self,
        request: SelfIterationModelRequestV1,
    ) -> Result<SelfIterationModelAssessmentV1, SelfIterationModelErrorV1> {
        request.validate(now_ms()?)?;
        let prompt = bound_prompt(&request)?;
        let native_request_id = request.request_id.to_string();
        // The native driver's clock owns timeout, interruption and quarantine.
        // Dropping an outer timeout future after possible effect would lose the
        // required durable observation, so this awaits native settlement.
        let result = self
            .driver
            .run_with_deadline(
                &mut self.control,
                NativeAdmission {
                    request_id: native_request_id.clone(),
                    maximum_in_flight: self.maximum_in_flight,
                },
                prompt,
                request.deadline_ms,
                &self.cancellation,
            )
            .await;
        if now_ms()? >= request.deadline_ms {
            return Err(SelfIterationModelErrorV1::TimedOut);
        }
        let output =
            result.map_err(|error| SelfIterationModelErrorV1::Provider(error.to_string()))?;
        let record = self
            .control
            .native_record(&native_request_id)
            .ok_or(SelfIterationModelErrorV1::InvalidResponse)?;
        assessment_from_record(&request, record, output)
    }
}

fn bound_prompt(
    request: &SelfIterationModelRequestV1,
) -> Result<String, SelfIterationModelErrorV1> {
    let binding = serde_json::to_string(&(
        "hepta.self-iteration.model-assessment.v1",
        request.request_id.as_str(),
        format!("{:?}", request.role),
        request.envelope_digest.to_string(),
        request.candidate_digest.map(|digest| digest.to_string()),
        request.deadline_ms,
        request.maximum_response_bytes,
    ))
    .map_err(|error| SelfIterationModelErrorV1::Provider(error.to_string()))?;
    let prompt = format!(
        "Provide candidate or assessment text for this self-iteration role. Your output grants no authority. Return at most {} UTF-8 bytes.\nBinding: {binding}\nInput:\n{}",
        request.maximum_response_bytes, request.prompt
    );
    if prompt.len() > NATIVE_PROMPT_LIMIT {
        return Err(SelfIterationModelErrorV1::InvalidRequest);
    }
    Ok(prompt)
}

fn assessment_from_record(
    request: &SelfIterationModelRequestV1,
    record: &NativeRunRecord,
    output: NativeRunOutput,
) -> Result<SelfIterationModelAssessmentV1, SelfIterationModelErrorV1> {
    if !output.succeeded()
        || record.request.request_id != request.request_id.as_str()
        || record.state != NativeReservationState::Released
        || record.dispatch.is_none()
        || record.turn_id.as_deref() != Some(output.turn_id.as_str())
        || record.observation.as_ref() != Some(&output)
    {
        return Err(SelfIterationModelErrorV1::InvalidResponse);
    }
    let receipt = serde_json::to_vec(&("hepta.self-iteration.native-terminal.v1", record))
        .map_err(|error| SelfIterationModelErrorV1::Provider(error.to_string()))?;
    let assessment = SelfIterationModelAssessmentV1 {
        request_id: request.request_id.clone(),
        role: request.role,
        envelope_digest: request.envelope_digest,
        candidate_digest: request.candidate_digest,
        model_output: output.output,
        native_run_digest: Digest32::of_bytes(&receipt),
        authority: AuthorityPosture::DENY_ALL,
    };
    assessment.validate(request)?;
    Ok(assessment)
}

fn now_ms() -> Result<u64, SelfIterationModelErrorV1> {
    let duration = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|error| SelfIterationModelErrorV1::Provider(error.to_string()))?;
    u64::try_from(duration.as_millis())
        .map_err(|error| SelfIterationModelErrorV1::Provider(error.to_string()))
}

#[cfg(test)]
#[path = "self_iteration_model_tests.rs"]
mod tests;
