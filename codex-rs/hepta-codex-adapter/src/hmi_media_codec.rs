//! Private decoder for the native media process protocol.
use super::*;

#[derive(Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub(super) enum NativeEvent {
    MediaAck {
        request_id: u64,
        operation: String,
        error: Option<String>,
    },
    SourceTranscript {
        source: HmiCapturedAudioRefV1,
        transcript: NativeTranscript,
    },
    TurnInterrupt {
        stream: HmiCaptureStreamV1,
        request: NativeInterrupt,
        local_error: Option<String>,
    },
    Presentation {
        identity: NativeOutputIdentity,
        state: NativePresentationState,
        error: Option<String>,
    },
    UnboundTranscript {
        stream: HmiCaptureStreamV1,
        transcript: NativeTranscript,
    },
    MediaTerminal {
        request_id: Option<u64>,
        input_errors: u64,
    },
}
#[derive(Deserialize)]
pub(super) struct NativeTranscript {
    pub(super) text: String,
    pub(super) finalized: bool,
    pub(super) result: Option<Value>,
}
#[derive(Deserialize)]
pub(super) struct NativeInterrupt {
    pub(super) output_epoch: u64,
}
#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum NativePresentationState {
    Submitted,
    Unknown,
}
#[derive(Deserialize)]
pub(super) struct NativeOutputIdentity {
    stream: HmiCaptureStreamV1,
    turn_id: String,
    utterance_id: String,
    sequence: u64,
    pub(super) output_epoch: u64,
}
impl NativeOutputIdentity {
    pub(super) fn scope(self, connection_id: u64) -> HmiOutputScopeV1 {
        let s = self.stream;
        HmiOutputScopeV1 {
            principal_id: s.principal_id,
            device_id: s.device_id,
            device_generation: s.device_generation,
            organ_id: s.organ_id,
            organ_generation: s.organ_generation,
            logical_session_id: s.logical_session_id,
            utterance_sequence: self.sequence,
            utterance_id: Some(self.utterance_id),
            connection_id,
            output_epoch: self.output_epoch,
            turn_id: Some(self.turn_id),
        }
    }
}
