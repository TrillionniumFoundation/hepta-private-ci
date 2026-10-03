//! Typed command retirement stays within the original bounded owner channel.
use super::*;

pub(super) enum Command {
    PreparePlasticityDataset(
        crate::PlasticityRuntimeHandleV1,
        AgentdSelfIterationHandleV1,
        crate::plasticity_runtime::parameter_dataset::ProtectedParameterDatasetV1,
        oneshot::Sender<
            Result<crate::plasticity_runtime::parameter_dataset::PreparedDataset, AgentdError>,
        >,
    ),
    PreparePlasticityInputFromContext(
        crate::PlasticityRuntimeHandleV1,
        AgentdSelfIterationHandleV1,
        crate::plasticity_runtime::parameter_preparation::ProtectedParameterPreparationV2,
        oneshot::Sender<
            Result<crate::plasticity_runtime::parameter_preparation::Prepared, AgentdError>,
        >,
    ),
    InspectParameterServingScope(
        Arc<crate::AgentdNeuronRuntimeV2Host>,
        AgentdSelfIterationRoundV1,
        oneshot::Sender<Result<crate::ParameterServingScopeV1, AgentdError>>,
    ),
    PrepareParameterCheckpoint(
        Arc<crate::AgentdNeuronRuntimeV2Host>,
        AgentdSelfIterationRoundV1,
        PathBuf,
        Digest32,
        oneshot::Sender<Result<crate::PreparedParameterCheckpointV1, AgentdError>>,
    ),
    RefreshPlasticityContext(
        crate::PlasticityRuntimeHandleV1,
        AgentdSelfIterationHandleV1,
        Option<AgentdSelfIterationRoundV1>,
        PathBuf,
        Digest32,
        oneshot::Sender<Result<(), AgentdError>>,
    ),
    InspectCurrentRound(
        oneshot::Sender<Result<Option<AgentdSelfIterationCurrentRoundV1>, AgentdError>>,
    ),
    InspectRound(
        StableId,
        Digest32,
        oneshot::Sender<Result<AgentdSelfIterationRoundStatusV1, AgentdError>>,
    ),
    Reserve(
        StableId,
        crate::CanonicalIterationEnvelopeV1,
        IterationEnvelopeV1,
        oneshot::Sender<Result<AgentdSelfIterationRoundV1, AgentdError>>,
    ),
    Begin(
        AgentdSelfIterationRoundV1,
        SelfIterationModelRequestV1,
        oneshot::Sender<Result<AgentdSelfIterationModelAdmissionV1, AgentdError>>,
    ),
    Complete(
        AgentdSelfIterationRoundV1,
        SelfIterationModelRequestV1,
        SelfIterationModelAssessmentV1,
        oneshot::Sender<Result<(), AgentdError>>,
    ),
    CompleteFailure(
        AgentdSelfIterationRoundV1,
        SelfIterationModelRequestV1,
        SelfIterationModelFailureV1,
        oneshot::Sender<Result<(), AgentdError>>,
    ),
    CompletePreparation(
        AgentdSelfIterationRoundV1,
        AgentdSelfIterationPreparationTerminalV1,
        oneshot::Sender<Result<(), AgentdError>>,
    ),
    BeginCandidateEffects(
        AgentdSelfIterationRoundV1,
        SelfIterationModelAssessmentV1,
        oneshot::Sender<Result<AgentdSelfIterationCandidateConstructionAdmissionV1, AgentdError>>,
    ),
    RejectProposal(
        AgentdSelfIterationRoundV1,
        SelfIterationModelAssessmentV1,
        AgentdSelfIterationProposalRejectionV1,
        oneshot::Sender<Result<(), AgentdError>>,
    ),
    Freeze(Box<AgentdSelfIterationCandidateV1>, Response),
    Evaluate(Digest32, Box<AgentdSignedEvaluationV1>, Response),
    Select(Digest32, SignedLearningEvidenceV1, Response),
    Observe(
        Digest32,
        AgentdSelfIterationCanaryVerdictV1,
        SignedLearningEvidenceV1,
        Response,
    ),
}

impl Command {
    pub(super) fn reject(self, error: AgentdError) {
        match self {
            Self::PreparePlasticityDataset(_, _, _, response) => {
                let _ = response.send(Err(error));
            }
            Self::Freeze(_, response)
            | Self::Evaluate(_, _, response)
            | Self::Select(_, _, response)
            | Self::Observe(_, _, _, response) => {
                let _ = response.send(Err(error));
            }
            Self::PreparePlasticityInputFromContext(_, _, _, response) => {
                let _ = response.send(Err(error));
            }
            Self::RefreshPlasticityContext(_, _, _, _, _, response) => {
                let _ = response.send(Err(error));
            }
            Self::InspectParameterServingScope(_, _, response) => {
                let _ = response.send(Err(error));
            }
            Self::PrepareParameterCheckpoint(_, _, _, _, response) => {
                let _ = response.send(Err(error));
            }
            Self::InspectRound(_, _, response) => {
                let _ = response.send(Err(error));
            }
            Self::InspectCurrentRound(response) => {
                let _ = response.send(Err(error));
            }
            Self::Reserve(_, _, _, response) => {
                let _ = response.send(Err(error));
            }
            Self::Begin(_, _, response) => {
                let _ = response.send(Err(error));
            }
            Self::Complete(_, _, _, response) | Self::CompleteFailure(_, _, _, response) => {
                let _ = response.send(Err(error));
            }
            Self::CompletePreparation(_, _, response) => {
                let _ = response.send(Err(error));
            }
            Self::BeginCandidateEffects(_, _, response) => {
                let _ = response.send(Err(error));
            }
            Self::RejectProposal(_, _, _, response) => {
                let _ = response.send(Err(error));
            }
        }
    }
}
