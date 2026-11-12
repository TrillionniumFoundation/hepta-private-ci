//! A separate fixed Version purpose. No observation, grant or task is uploaded.
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::Error;
use super::OriginalCircuitRetainedVersionPublicationV1;
use super::OriginalCircuitRetainedVersionReadbackV1;
use super::context::OriginalVersionCut;

pub(super) const OPERATION: &str = "runtime.learning.original-retained-version.command.v1";

#[derive(Clone, Copy, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Action {
    Prepare,
    Readback,
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    pub schema: u8,
    pub purpose: String,
    pub request_id: u64,
    pub initial_binding: String,
    pub binding: String,
    pub operation_id: String,
    pub training_head: String,
    pub action: Action,
}
impl Request {
    pub(super) fn new(cut: &OriginalVersionCut, request_id: u64, action: Action) -> Self {
        Self {
            schema: 1,
            purpose: cut.purpose().operation().into(),
            request_id,
            initial_binding: cut.initial_binding.to_string(),
            binding: cut.binding.to_string(),
            operation_id: cut.training.training.request.operation_id.to_string(),
            training_head: cut.training.training.head_digest.to_string(),
            action,
        }
    }
    pub(super) fn require_cut(
        &self,
        cut: &OriginalVersionCut,
        request_id: u64,
    ) -> Result<(), Error> {
        if self != &Self::new(cut, request_id, self.action) || !(1..=128).contains(&request_id) {
            return Err(Error::Binding("exact original retained Version request"));
        }
        Ok(())
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Response {
    pub request: Request,
    pub result: OriginalResult,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum OriginalResult {
    Prepared {
        intent: String,
    },
    Installed {
        intent: String,
        publication: String,
        task: String,
        selection: String,
        bundle: String,
        run: String,
    },
    Busy,
    ReadbackRequired,
    FinalUseDenied,
    Uncertain,
    Unavailable,
}
impl OriginalResult {
    pub(super) fn from_original(value: OriginalCircuitRetainedVersionReadbackV1) -> Self {
        match value.publication {
            None => Self::Prepared {
                intent: value.intent.to_string(),
            },
            Some(p) => Self::Installed {
                intent: p.intent.to_string(),
                publication: p.publication.to_string(),
                task: p.task.to_string(),
                selection: p.selection.to_string(),
                bundle: p.bundle.to_string(),
                run: p.run.to_string(),
            },
        }
    }
    pub(super) fn decode(
        self,
        cut: &OriginalVersionCut,
    ) -> Result<OriginalCircuitRetainedVersionReadbackV1, Error> {
        match self {
            Self::Prepared { intent } => Ok(OriginalCircuitRetainedVersionReadbackV1 {
                intent: digest(&intent)?,
                publication: None,
            }),
            Self::Installed {
                intent,
                publication,
                task,
                selection,
                bundle,
                run,
            } => {
                let baseline = cut
                    .training
                    .training
                    .request
                    .selected_bundle
                    .digest()
                    .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
                let run =
                    StableId::new(run).map_err(|_| Error::Binding("original distinct C run"))?;
                if digest(&bundle)? != baseline
                    || run == cut.training.training.request.source_run_id
                {
                    return Err(Error::Binding(
                        "same retained bundle and distinct original C",
                    ));
                }
                let intent = digest(&intent)?;
                Ok(OriginalCircuitRetainedVersionReadbackV1 {
                    intent,
                    publication: Some(OriginalCircuitRetainedVersionPublicationV1 {
                        intent,
                        publication: digest(&publication)?,
                        task: digest(&task)?,
                        selection: digest(&selection)?,
                        bundle: baseline,
                        run,
                    }),
                })
            }
            Self::Busy => Err(Error::Busy),
            Self::ReadbackRequired => Err(Error::ReadbackRequired),
            Self::FinalUseDenied => Err(Error::FinalUseDenied),
            Self::Uncertain => Err(Error::CommitUncertain),
            Self::Unavailable => Err(Error::Unavailable),
        }
    }
}
pub(super) fn digest(text: &str) -> Result<Digest32, Error> {
    let value: Digest32 = text
        .parse()
        .map_err(|_| Error::Binding("original Version digest"))?;
    if value.is_zero() || value.to_string() != text {
        return Err(Error::Binding("canonical original Version digest"));
    }
    Ok(value)
}
