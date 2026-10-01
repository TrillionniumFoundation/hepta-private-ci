//! Plain reference prompts through the same serial native owner and authority.
use super::AppServerSelfIterationModelPortV1;
use super::NativeAdmission;
use super::NativeReservationState;
use super::NativeRunOutput;
use super::NativeRunRecord;
use super::SelfIterationModelErrorV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeReferenceObservationV1 {
    pub native_request_id: String,
    pub prompt_digest: String,
    pub original_deadline_ms: u64,
    pub replayed: bool,
    /// Only a fresh, successful terminal call establishes original latency.
    /// Recovery never replaces this with the time spent reading cached output.
    pub fresh_execution_latency_us: Option<u64>,
    pub attempt_elapsed_us: u64,
    pub attempt_started_at_ms: u64,
    pub attempt_finished_at_ms: u64,
    pub native_record: Option<NativeRunRecord>,
    pub native_output: Option<NativeRunOutput>,
    pub native_receipt_digest: Option<String>,
    pub diagnostic: Option<String>,
    pub succeeded: bool,
}

impl AppServerSelfIterationModelPortV1 {
    #[cfg(feature = "agentd-host")]
    pub(crate) fn reference_can_reconcile(
        &self,
        request_id: &str,
    ) -> Result<bool, SelfIterationModelErrorV1> {
        self.control
            .native_record_resolved(request_id)
            .map(|record| {
                record.is_some_and(|record| {
                    record.state != NativeReservationState::Reserved || record.dispatch.is_some()
                })
            })
            .map_err(|error| SelfIterationModelErrorV1::Provider(error.to_string()))
    }

    /// The installed owner calls this only for its checksum-pinned private batch.
    /// This does not construct another control owner, queue or signing authority.
    pub async fn run_reference_prompt(
        &mut self,
        request_id: String,
        prompt: String,
        original_deadline_ms: u64,
    ) -> Result<NativeReferenceObservationV1, SelfIterationModelErrorV1> {
        if StableId::new(request_id.clone()).is_err()
            || prompt.is_empty()
            || prompt.len() > super::NATIVE_PROMPT_LIMIT
            || original_deadline_ms == 0
        {
            return Err(SelfIterationModelErrorV1::InvalidRequest);
        }
        let before = self
            .control
            .native_record_resolved(&request_id)
            .map_err(|error| SelfIterationModelErrorV1::Provider(error.to_string()))?;
        let replayed = before.as_ref().is_some_and(|record| {
            record.state != NativeReservationState::Reserved || record.dispatch.is_some()
        });
        let prompt_digest = Digest32::of_bytes(prompt.as_bytes()).to_string();
        let attempt_started_at_ms = reference_unix_ms()?;
        let started = std::time::Instant::now();
        // The native owner checks exact prompt/deadline/config binding even on
        // replay. It reconciles possibly dispatched work without turn/start.
        let result = self
            .driver
            .run_with_deadline(
                &mut self.control,
                NativeAdmission {
                    request_id: request_id.clone(),
                    maximum_in_flight: self.maximum_in_flight,
                },
                prompt,
                original_deadline_ms,
                &self.cancellation,
            )
            .await;
        let elapsed = u64::try_from(started.elapsed().as_micros())
            .map_err(|_| SelfIterationModelErrorV1::InvalidResponse)?;
        let attempt_finished_at_ms = reference_unix_ms()?;
        let record = self
            .control
            .native_record_resolved(&request_id)
            .map_err(|error| SelfIterationModelErrorV1::Provider(error.to_string()))?;
        let diagnostic = result.as_ref().err().map(ToString::to_string);
        let output = result
            .ok()
            .or_else(|| record.as_ref().and_then(|r| r.observation.clone()));
        let succeeded = successful_terminal(
            &request_id,
            record.as_ref(),
            output.as_ref(),
            diagnostic.as_ref(),
        );
        let native_receipt_digest = record_digest(record.as_ref())?;
        Ok(NativeReferenceObservationV1 {
            native_request_id: request_id,
            prompt_digest,
            original_deadline_ms,
            replayed,
            fresh_execution_latency_us: (!replayed && succeeded).then_some(elapsed),
            attempt_elapsed_us: elapsed,
            attempt_started_at_ms,
            attempt_finished_at_ms,
            native_record: record,
            native_output: output,
            native_receipt_digest,
            diagnostic,
            succeeded,
        })
    }
}

fn reference_unix_ms() -> Result<u64, SelfIterationModelErrorV1> {
    let duration = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|error| SelfIterationModelErrorV1::Provider(error.to_string()))?;
    u64::try_from(duration.as_millis()).map_err(|_| SelfIterationModelErrorV1::InvalidResponse)
}
fn record_digest(
    record: Option<&NativeRunRecord>,
) -> Result<Option<String>, SelfIterationModelErrorV1> {
    record
        .map(|record| {
            serde_json::to_vec(&("hepta.reference.native-terminal.v1", record))
                .map(|bytes| Digest32::of_bytes(&bytes).to_string())
        })
        .transpose()
        .map_err(|error| SelfIterationModelErrorV1::Provider(error.to_string()))
}
fn successful_terminal(
    request_id: &str,
    record: Option<&NativeRunRecord>,
    output: Option<&NativeRunOutput>,
    diagnostic: Option<&String>,
) -> bool {
    diagnostic.is_none()
        && record.is_some_and(|record| {
            record.request.request_id == request_id
                && record.state == NativeReservationState::Released
                && record.dispatch.is_some()
                && record
                    .terminal_publication
                    .as_ref()
                    .is_none_or(|p| !p.pending())
                && output.is_some_and(|output| {
                    output.succeeded()
                        && record.turn_id.as_deref() == Some(output.turn_id.as_str())
                        && record.observation.as_ref() == Some(output)
                })
        })
}
impl NativeReferenceObservationV1 {
    #[cfg(any(feature = "agentd-host", test))]
    pub(crate) fn validate(&self) -> Result<(), SelfIterationModelErrorV1> {
        let expected_success = successful_terminal(
            &self.native_request_id,
            self.native_record.as_ref(),
            self.native_output.as_ref(),
            self.diagnostic.as_ref(),
        );
        if self.succeeded != expected_success
            || self.native_receipt_digest != record_digest(self.native_record.as_ref())?
            || self.fresh_execution_latency_us
                != (!self.replayed && self.succeeded).then_some(self.attempt_elapsed_us)
            || self.attempt_started_at_ms == 0
            || self.attempt_finished_at_ms == 0
            || self.native_record.as_ref().is_some_and(|record| {
                record.request.request_id != self.native_request_id
                    || self
                        .native_output
                        .as_ref()
                        .is_some_and(|output| record.observation.as_ref() != Some(output))
                    || record
                        .dispatch
                        .as_ref()
                        .and_then(|d| d.codex_deadline_ms)
                        .is_some_and(|deadline| deadline != self.original_deadline_ms)
            })
        {
            return Err(SelfIterationModelErrorV1::InvalidResponse);
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "self_iteration_reference_tests.rs"]
mod tests;
