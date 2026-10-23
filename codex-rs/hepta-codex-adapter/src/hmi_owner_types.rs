//! Contracts implemented by the existing authenticated owner.
use super::*;
use std::future::Future;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HmiCaptureStreamV1 {
    pub principal_id: String,
    pub device_id: String,
    pub device_generation: u64,
    pub organ_id: String,
    pub organ_generation: u64,
    pub logical_session_id: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HmiCapturedAudioRefV1 {
    pub stream: HmiCaptureStreamV1,
    pub capture_generation: u64,
    pub sequence: u64,
    pub asset_id: String,
    pub sha256: String,
    pub byte_length: u64,
    pub sample_rate: u32,
    pub num_channels: u16,
    pub start_sample: u64,
    pub end_sample: u64,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HmiOwnerTranscriptV1 {
    /// Stamped by the owner reader task for its media process, not by the caller.
    pub connection_id: u64,
    pub source: HmiCapturedAudioRefV1,
    pub text: String,
    pub finalized: bool,
}
impl HmiOwnerTranscriptV1 {
    pub(super) fn payload_sha256(&self) -> Result<String, HmiError> {
        let encoded =
            serde_json::to_vec(&("hepta.hmi.source-observation.v1", &self.source, &self.text))
                .map_err(|e| HmiError::Protocol(e.to_string()))?;
        Ok(Digest32::of_bytes(&encoded).to_string())
    }
}
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HmiObservationReceiptV1 {
    pub observation_id: String,
    pub payload_sha256: String,
}
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum HmiMediaPresentationV1 {
    Generated,
    Queued,
    Submitted,
    DeviceObservedPlayback,
    Interrupted,
    Unknown,
}

/// The existing principal/device owner must check its actual current grants.
/// Implementations must not infer authentication from matching config fields.
pub trait HmiOwnerAuthorityV1: Send + Sync {
    fn check_current(&self, binding: &HmiBindingV1) -> Result<(), HmiError>;
}
/// Bound to one owned media process and connection incarnation. Sends must be
/// bounded; retire_output completes only after old local admission is fenced.
/// Submitted means device-buffer submission, never proof that a human heard it.
/// DeviceObservedPlayback requires independent device-observable evidence.
pub trait HmiOwnerMediaV1: Send + Sync {
    fn connection_id(&self) -> u64;
    fn capture_generation(&self) -> u64;
    fn verify_source(
        &self,
        source: &HmiCapturedAudioRefV1,
    ) -> impl Future<Output = Result<(), HmiError>> + Send;
    fn attach_turn(
        &self,
        scope: &HmiOutputScopeV1,
    ) -> impl Future<Output = Result<(), HmiError>> + Send;
    fn speak(
        &self,
        request: HmiSpeechRequestV1,
    ) -> impl Future<Output = Result<HmiMediaPresentationV1, HmiError>> + Send;
    fn retire_output(&self, output_epoch: u64)
    -> impl Future<Output = Result<(), HmiError>> + Send;
    fn revoke_capture(&self) -> impl Future<Output = Result<(), HmiError>> + Send;
}
/// The existing sourced-observation ingress, not a new persistence authority.
/// It must verify the principal/device grant and idempotently bind the exact
/// digest and client message ID. ReconcileOnly must never insert an observation.
/// The returned receipt is supplied only by this trusted owner port, never by
/// deserializing an untrusted media/UI assertion that a write succeeded.
pub trait HmiOwnerObservationsV1: Send + Sync {
    fn observe_final(
        &self,
        binding: &HmiBindingV1,
        input: &HmiOwnerTranscriptV1,
        client_message_id: &str,
        payload_sha256: &str,
        mode: ThreadQueueReconcileMode,
    ) -> impl Future<Output = Result<HmiObservationReceiptV1, HmiError>> + Send;
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HmiOwnerInputOutcomeV1 {
    pub input: HmiOwnerTranscriptV1,
    pub client_message_id: Option<String>,
    pub observation: Option<HmiObservationReceiptV1>,
    pub admission: Option<ThreadQueueReconcileResponse>,
    pub stage: String,
    pub error: Option<String>,
    pub interruption: Option<HmiOwnerInterruptV1>,
}
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HmiOwnerInterruptV1 {
    pub scope: HmiOutputScopeV1,
    pub local_stop_error: Option<String>,
    pub remote_interrupt_error: Option<String>,
    pub capture_stop_error: Option<String>,
    pub terminal_observed: bool,
}
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HmiOwnerOutputOutcomeV1 {
    pub event: HmiEventV1,
    pub presentation: Option<HmiMediaPresentationV1>,
    pub error: Option<String>,
    pub interruption: Option<HmiOwnerInterruptV1>,
}
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HmiOwnerMediaOutcomeV1 {
    pub event: HmiOwnedMediaEventV1,
    pub input: Option<HmiOwnerInputOutcomeV1>,
    pub interruption: Option<HmiOwnerInterruptV1>,
    pub error: Option<String>,
}
