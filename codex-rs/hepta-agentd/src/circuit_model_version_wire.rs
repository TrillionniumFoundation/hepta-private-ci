//! Distinct positive Version purpose; no NoUpdate tag or uploaded Model cut.
use serde::Deserialize;
use serde::Serialize;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use super::Error;
use super::OriginalCircuitModelVersionPublicationV1 as Publication;
use super::OriginalCircuitModelVersionReadbackV1 as Readback;
use crate::OriginalCircuitModelPublicationContextV1 as Context;

pub(super) const PURPOSE: &str = "runtime.learning.original-circuit-model-version.command.v1";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Action { Publish, Readback }

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    pub schema: u8,
    pub purpose: String,
    pub request_id: u64,
    pub initial_binding: String,
    pub binding: String,
    pub operation_id: String,
    pub model_head: String,
    pub action: Action,
}
impl Request {
    pub(super) fn new(context: &Context, request_id: u64, action: Action) -> Result<Self, Error> {
        let (initial, binding) = context.original_version_binding(super::now()?)?;
        Ok(Self {
            schema: 1, purpose: PURPOSE.into(), request_id,
            initial_binding: initial.to_string(), binding: binding.to_string(),
            operation_id: context.decision().request.operation_id.to_string(),
            model_head: context.decision().head_digest.to_string(), action,
        })
    }
    pub(super) fn require_initial(
        &self, initial: Digest32, operation: &StableId, request_id: u64,
    ) -> Result<(), Error> {
        if self.schema != 1 || self.purpose != PURPOSE
            || self.request_id != request_id || !(1..=128).contains(&request_id)
            || self.initial_binding != initial.to_string()
            || self.operation_id != operation.as_str()
        {
            return Err(Error::Binding("same original positive Version initial purpose"));
        }
        digest(&self.binding)?;
        digest(&self.model_head)?;
        Ok(())
    }
    pub(super) fn require_context(&self, context: &Context) -> Result<(), Error> {
        let expected = Self::new(context, self.request_id, self.action)?;
        if self != &expected {
            return Err(Error::Binding("same full original positive Model Version pin"));
        }
        Ok(())
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Response {
    pub request: Request,
    pub result: Outcome,
}
#[derive(Deserialize, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum Outcome {
    Prepared { intent: String },
    Published { intent: String, publication: String, task: String, selection: String,
        bundle: String, run: String },
    Busy, ReadbackRequired, Uncertain, Unavailable, FinalUseDenied,
}
impl Outcome {
    pub(super) fn from_original(read: Readback) -> Self {
        match read.publication {
            None => Self::Prepared { intent: read.intent.to_string() },
            Some(publication) => Self::Published {
                intent: publication.intent.to_string(), publication: publication.publication.to_string(),
                task: publication.task.to_string(), selection: publication.selection.to_string(),
                bundle: publication.bundle.to_string(), run: publication.run.to_string(),
            },
        }
    }
    pub(super) fn decode(self, context: &Context) -> Result<Readback, Error> {
        context.authenticate(super::now()?, /*new_work*/ false)?;
        match self {
            Self::Prepared { intent } => Ok(Readback { intent: digest(&intent)?, publication: None }),
            Self::Published { intent, publication, task, selection, bundle, run } => {
                let coordinator = LearningIterationCoordinatorV1::from_snapshot(context.decision().clone())?;
                let expected = coordinator.candidate().ok_or(Error::Binding("actual changed Model"))?
                    .digest().map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
                let run = StableId::new(run).map_err(|_| Error::Binding("original C run"))?;
                if run == context.decision().request.source_run_id || digest(&bundle)? != expected {
                    return Err(Error::Binding("actual changed Model and distinct C"));
                }
                let intent = digest(&intent)?;
                Ok(Readback { intent, publication: Some(Publication {
                    intent, publication: digest(&publication)?, task: digest(&task)?,
                    selection: digest(&selection)?, bundle: expected, run,
                }) })
            }
            Self::Busy => Err(Error::Busy),
            Self::ReadbackRequired => Err(Error::ReadbackRequired),
            Self::Uncertain => Err(Error::CommitUncertain),
            Self::Unavailable => Err(Error::Unavailable),
            Self::FinalUseDenied => Err(Error::FinalUseDenied),
        }
    }
}
pub(super) fn digest(value: &str) -> Result<Digest32, Error> {
    let digest: Digest32 = value.parse().map_err(|_| Error::Binding("canonical Version digest"))?;
    if digest.is_zero() || digest.to_string() != value {
        return Err(Error::Binding("canonical Version digest"));
    }
    Ok(digest)
}
