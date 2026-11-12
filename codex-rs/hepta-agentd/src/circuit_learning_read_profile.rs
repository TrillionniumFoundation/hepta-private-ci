//! Private typed dispatch. The public legacy configuration and its exact
//! mode, domain and signature checks remain the strict TNU-only wire profile.

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_types::Digest32;

use super::Error;
use super::OriginalCircuitEvaluatedLearningReadContextV1;
use super::OriginalCircuitLearningReadContextV1;
use super::OriginalCircuitLearningReadbackV1;
use super::wire;

const EVALUATED_OPERATION: &str = "runtime.learning.original-circuit.evaluated-current-read.v1";

pub(super) enum ReadProfile {
    TrainingNoUpdate(OriginalCircuitLearningReadContextV1),
    Evaluated(OriginalCircuitEvaluatedLearningReadContextV1),
}

impl ReadProfile {
    pub(super) fn legacy(&self) -> Result<&OriginalCircuitLearningReadContextV1, Error> {
        match self {
            Self::TrainingNoUpdate(context) => Ok(context),
            Self::Evaluated(_) => Err(Error::Binding("legacy TrainingNoUpdate read purpose")),
        }
    }

    pub(super) fn prefix(&self) -> &LearningIterationSnapshotV1 {
        match self {
            Self::TrainingNoUpdate(context) => &context.prefix,
            Self::Evaluated(context) => context.prefix(),
        }
    }

    pub(super) fn scope(&self) -> &FrozenLearningScopeV2 {
        match self {
            Self::TrainingNoUpdate(context) => &context.scope,
            Self::Evaluated(context) => context.scope(),
        }
    }

    pub(super) fn mode(&self) -> Result<wire::Mode, Error> {
        match self {
            Self::TrainingNoUpdate(context) => wire::mode(context),
            Self::Evaluated(context) => Ok(context.mode()),
        }
    }

    pub(super) fn binding(&self, at: u64) -> Result<Digest32, Error> {
        match self {
            Self::TrainingNoUpdate(context) => wire::context_binding(context, at),
            Self::Evaluated(context) => context.binding(at),
        }
    }

    pub(super) fn decision(&self) -> Result<LearningIterationCoordinatorV1, Error> {
        match self {
            Self::TrainingNoUpdate(context) => wire::decision(context),
            Self::Evaluated(context) => context.decision(),
        }
    }

    pub(super) fn selection(&self) -> Result<&LearningIterationObservationV1, Error> {
        if self.mode()? != wire::Mode::NextUse {
            return Err(Error::Binding("original Selection extension required"));
        }
        self.prefix()
            .receipts
            .last()
            .map(|receipt| &receipt.observation)
            .ok_or(Error::Binding("original Selection extension"))
    }

    pub(super) fn request(
        &self,
        binding: Digest32,
        request_id: u64,
    ) -> Result<wire::Request, Error> {
        match self {
            Self::TrainingNoUpdate(context) => wire::Request::new(context, binding, request_id),
            Self::Evaluated(context) => Ok(wire::Request {
                schema: 1,
                operation: EVALUATED_OPERATION.into(),
                request_id,
                binding: binding.to_string(),
                prefix_head: context.prefix().head_digest.to_string(),
                operation_id: context.prefix().request.operation_id.to_string(),
                mode: context.mode(),
            }),
        }
    }

    pub(super) fn require_request(
        &self,
        request: &wire::Request,
        binding: Digest32,
        request_id: u64,
    ) -> Result<(), Error> {
        if let Self::TrainingNoUpdate(context) = self {
            return request.require_context(context, binding, request_id);
        }
        let expected = self.request(binding, request_id)?;
        if request.schema != expected.schema
            || request.operation != expected.operation
            || request.request_id != expected.request_id
            || request.binding != expected.binding
            || request.prefix_head != expected.prefix_head
            || request.operation_id != expected.operation_id
            || request.mode != expected.mode
        {
            return Err(Error::Binding("original fixed evaluated read request"));
        }
        Ok(())
    }

    pub(super) fn decode(
        &self,
        read: wire::OriginalRead,
    ) -> Result<OriginalCircuitLearningReadbackV1, Error> {
        match self {
            Self::TrainingNoUpdate(context) => read.decode(context),
            Self::Evaluated(context) => read.decode_evaluated(context),
        }
    }
}
