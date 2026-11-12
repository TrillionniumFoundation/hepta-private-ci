//! Explicit evaluated Version frames. Legacy training_head frames are unchanged.
//! Only purpose/correlation crosses the wire; no future receipt or grant does.

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::Error;
use super::OriginalCircuitEvaluatedVersionProgressV1;
use super::OriginalCircuitRetainedVersionPublicationV1;
use super::OriginalCircuitRetainedVersionReadbackV1;
use super::evaluated_context::OriginalEvaluatedVersionCut;
use super::profile::VersionCut;
use super::profile::VersionPurpose;
use super::wire;

const EVALUATED_OPERATION: &str = "runtime.learning.original-evaluated-version.command.v1";

#[derive(Clone, Copy, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum EvaluatedAction {
    Prepare,
    Readback,
    PublicationProgress,
}

impl From<wire::Action> for EvaluatedAction {
    fn from(action: wire::Action) -> Self {
        match action {
            wire::Action::Prepare => Self::Prepare,
            wire::Action::Readback => Self::Readback,
        }
    }
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct EvaluatedRequest {
    schema: u8,
    purpose: String,
    request_id: u64,
    initial_binding: String,
    binding: String,
    operation_id: String,
    evaluation_head: String,
    action: EvaluatedAction,
}

impl EvaluatedRequest {
    fn new(cut: &OriginalEvaluatedVersionCut, request_id: u64, action: EvaluatedAction) -> Self {
        Self {
            schema: 1,
            purpose: EVALUATED_OPERATION.into(),
            request_id,
            initial_binding: cut.initial_binding.to_string(),
            binding: cut.binding.to_string(),
            operation_id: cut.evaluated.snapshot().request.operation_id.to_string(),
            evaluation_head: cut.evaluated.snapshot().head_digest.to_string(),
            action,
        }
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct EvaluatedResponse {
    request: EvaluatedRequest,
    result: wire::OriginalResult,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct EvaluatedProgressResponse {
    request: EvaluatedRequest,
    result: EvaluatedProgressResult,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum EvaluatedProgressResult {
    Pending,
    ReadbackAvailable,
    Busy,
    ReadbackRequired,
    FinalUseDenied,
    Uncertain,
    Unavailable,
}

impl EvaluatedProgressResult {
    pub(super) fn decode(self) -> Result<OriginalCircuitEvaluatedVersionProgressV1, Error> {
        match self {
            Self::Pending => Ok(OriginalCircuitEvaluatedVersionProgressV1::Pending),
            Self::ReadbackAvailable => Ok(OriginalCircuitEvaluatedVersionProgressV1::ReadbackAvailable),
            Self::Busy => Err(Error::Busy),
            Self::ReadbackRequired => Err(Error::ReadbackRequired),
            Self::FinalUseDenied => Err(Error::FinalUseDenied),
            Self::Uncertain => Err(Error::CommitUncertain),
            Self::Unavailable => Err(Error::Unavailable),
        }
    }
}

pub(super) enum VersionRequest {
    TrainingNoUpdate(wire::Request),
    Evaluated(EvaluatedRequest),
}

impl VersionRequest {
    pub(super) fn new(cut: &VersionCut, request_id: u64, action: wire::Action) -> Self {
        match cut {
            VersionCut::TrainingNoUpdate(original) => Self::TrainingNoUpdate(wire::Request::new(original, request_id, action)),
            VersionCut::Evaluated(original) => Self::Evaluated(EvaluatedRequest::new(original, request_id, action.into())),
        }
    }

    pub(super) fn publication_progress(cut: &VersionCut, request_id: u64) -> Result<Self, Error> {
        let VersionCut::Evaluated(original) = cut else {
            return Err(Error::Binding("evaluated-only Version progress purpose"));
        };
        Ok(Self::Evaluated(EvaluatedRequest::new(
            original, request_id, EvaluatedAction::PublicationProgress,
        )))
    }

    pub(super) fn is_publication_progress(&self) -> bool {
        matches!(self, Self::Evaluated(request) if request.action == EvaluatedAction::PublicationProgress)
    }

    pub(super) fn decode(bytes: &[u8], purpose: VersionPurpose) -> Result<Self, Error> {
        match purpose {
            VersionPurpose::TrainingNoUpdate => Ok(Self::TrainingNoUpdate(serde_json::from_slice(bytes)?)),
            VersionPurpose::Evaluated => Ok(Self::Evaluated(serde_json::from_slice(bytes)?)),
        }
    }

    pub(super) fn encode(&self) -> Result<Vec<u8>, Error> {
        Ok(match self {
            Self::TrainingNoUpdate(original) => serde_json::to_vec(original)?,
            Self::Evaluated(original) => serde_json::to_vec(original)?,
        })
    }

    pub(super) fn action(&self) -> Result<wire::Action, Error> {
        match self {
            Self::TrainingNoUpdate(original) => Ok(original.action),
            Self::Evaluated(original) => match original.action {
                EvaluatedAction::Prepare => Ok(wire::Action::Prepare),
                EvaluatedAction::Readback => Ok(wire::Action::Readback),
                EvaluatedAction::PublicationProgress => Err(Error::Binding("progress is not an original Version readback")),
            },
        }
    }

    pub(super) fn require_initial(
        &self,
        purpose: VersionPurpose,
        request_id: u64,
        initial_binding: Digest32,
        initial: &LearningIterationSnapshotV1,
    ) -> Result<(), Error> {
        let (schema, operation, actual_id, initial_pin, binding, operation_id, head) = match (self, purpose) {
            (Self::TrainingNoUpdate(original), VersionPurpose::TrainingNoUpdate) => (
                original.schema, original.purpose.as_str(), original.request_id,
                &original.initial_binding, &original.binding, &original.operation_id, &original.training_head,
            ),
            (Self::Evaluated(original), VersionPurpose::Evaluated) => (
                original.schema, original.purpose.as_str(), original.request_id,
                &original.initial_binding, &original.binding, &original.operation_id, &original.evaluation_head,
            ),
            _ => return Err(Error::Binding("original Version protocol profile")),
        };
        let expected_operation = match purpose {
            VersionPurpose::TrainingNoUpdate => wire::OPERATION,
            VersionPurpose::Evaluated => EVALUATED_OPERATION,
        };
        if schema != 1
            || operation != expected_operation
            || actual_id != request_id
            || !(1..=128).contains(&request_id)
            || initial_pin != &initial_binding.to_string()
            || operation_id != &initial.request.operation_id.to_string()
        {
            return Err(Error::Binding("same original Version initial purpose and operation"));
        }
        wire::digest(binding)?;
        wire::digest(head)?;
        Ok(())
    }

    pub(super) fn require_cut(&self, cut: &VersionCut, request_id: u64) -> Result<(), Error> {
        match (self, cut) {
            (Self::TrainingNoUpdate(request), VersionCut::TrainingNoUpdate(original)) => request.require_cut(original, request_id),
            (Self::Evaluated(request), VersionCut::Evaluated(original)) => {
                if request != &EvaluatedRequest::new(original, request_id, request.action)
                    || !(1..=128).contains(&request_id)
                {
                    return Err(Error::Binding("exact original evaluated Version request"));
                }
                Ok(())
            }
            _ => Err(Error::Binding("original Version cut profile")),
        }
    }

    pub(super) fn decode_response(&self, raw: &[u8]) -> Result<wire::OriginalResult, Error> {
        if self.is_publication_progress() {
            return Err(Error::Binding("progress cannot decode original Version publication"));
        }
        match self {
            Self::TrainingNoUpdate(request) => {
                let response: wire::Response = serde_json::from_slice(raw)?;
                if &response.request != request {
                    return Err(Error::Binding("exact original Version response"));
                }
                Ok(response.result)
            }
            Self::Evaluated(request) => {
                let response: EvaluatedResponse = serde_json::from_slice(raw)?;
                if &response.request != request {
                    return Err(Error::Binding("exact original evaluated Version response"));
                }
                Ok(response.result)
            }
        }
    }

    pub(super) fn encode_response(self, result: wire::OriginalResult) -> Result<Vec<u8>, Error> {
        if self.is_publication_progress() {
            return Err(Error::Binding("progress cannot encode original Version publication"));
        }
        Ok(match self {
            Self::TrainingNoUpdate(request) => serde_json::to_vec(&wire::Response { request, result })?,
            Self::Evaluated(request) => serde_json::to_vec(&EvaluatedResponse { request, result })?,
        })
    }

    pub(super) fn decode_progress_response(&self, raw: &[u8]) -> Result<EvaluatedProgressResult, Error> {
        let Self::Evaluated(request) = self else {
            return Err(Error::Binding("evaluated-only Version progress response"));
        };
        if request.action != EvaluatedAction::PublicationProgress {
            return Err(Error::Binding("original Version action is not progress"));
        }
        let response: EvaluatedProgressResponse = serde_json::from_slice(raw)?;
        if &response.request != request {
            return Err(Error::Binding("exact original evaluated Version progress response"));
        }
        Ok(response.result)
    }

    pub(super) fn encode_progress_response(self, result: EvaluatedProgressResult) -> Result<Vec<u8>, Error> {
        let Self::Evaluated(request) = self else {
            return Err(Error::Binding("evaluated-only Version progress response"));
        };
        if request.action != EvaluatedAction::PublicationProgress {
            return Err(Error::Binding("original Version action is not progress"));
        }
        Ok(serde_json::to_vec(&EvaluatedProgressResponse { request, result })?)
    }
}

pub(super) fn decode_result(
    result: wire::OriginalResult,
    cut: &VersionCut,
) -> Result<OriginalCircuitRetainedVersionReadbackV1, Error> {
    let original = match cut {
        VersionCut::TrainingNoUpdate(original) => return result.decode(original),
        VersionCut::Evaluated(original) => original,
    };
    match result {
        wire::OriginalResult::Prepared { intent } => Ok(OriginalCircuitRetainedVersionReadbackV1 {
            intent: wire::digest(&intent)?,
            publication: None,
        }),
        wire::OriginalResult::Installed { intent, publication, task, selection, bundle, run } => {
            let request = &original.evaluated.snapshot().request;
            let baseline = request.selected_bundle.digest()
                .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
            let run = StableId::new(run).map_err(|_| Error::Binding("original distinct evaluated C run"))?;
            if wire::digest(&bundle)? != baseline || run == request.source_run_id {
                return Err(Error::Binding("same evaluated retained bundle and distinct original C"));
            }
            let intent = wire::digest(&intent)?;
            Ok(OriginalCircuitRetainedVersionReadbackV1 {
                intent,
                publication: Some(OriginalCircuitRetainedVersionPublicationV1 {
                    intent,
                    publication: wire::digest(&publication)?,
                    task: wire::digest(&task)?,
                    selection: wire::digest(&selection)?,
                    bundle: baseline,
                    run,
                }),
            })
        }
        wire::OriginalResult::Busy => Err(Error::Busy),
        wire::OriginalResult::ReadbackRequired => Err(Error::ReadbackRequired),
        wire::OriginalResult::FinalUseDenied => Err(Error::FinalUseDenied),
        wire::OriginalResult::Uncertain => Err(Error::CommitUncertain),
        wire::OriginalResult::Unavailable => Err(Error::Unavailable),
    }
}
