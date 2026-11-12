//! One original live actor's A → scoped learning → C composition.
//! Ordinary tasks still enter only through authenticated ObjectiveStart.
//! Host data cannot set Ready, provide a completed receipt, revive a phase,
//! authorize another principal, or attest an operating-system restart.

use std::os::unix::net::UnixDatagram;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_automation::BoundedCircuitDefinitionV2;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::LearningArtifactPublishRequestV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;
use tokio::sync::mpsc;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdGenerationUpdateAuthoritiesV1;
use crate::AgentdGenerationUpdatePredecessorFilesV1;
use crate::AgentdGenerationUpdateTargetV1;
use crate::AgentdIdentity;
use crate::AgentdSelectedGenerationV1;
use crate::AgentdUnixFinalUseGrantProvider;
use crate::CellQ24DatasetTaskV1;
use crate::CellQ24LearningPreparationConfigV1;
use crate::CellQ24PreparedLearningV1;
use crate::CircuitCellRouteV1;
use crate::CircuitCellTimeV1;
use crate::CircuitQ24TaskFilesV1;
use crate::CircuitQ24TaskOpenModeV1;
use crate::CircuitQ24TaskProfileV1;
use crate::CircuitQ24TaskRuntimeV1;
use crate::CircuitTaskRuntimeBootstrapV1;
use crate::CircuitTaskSourceInputV1;
use crate::CircuitTaskSourceReadbackV1;
use crate::HostAuthorityLearningProfileV1;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalCellQ24LearningInputsV1;
use crate::OriginalCellQ24SelectionInputsV1;
use crate::OriginalCellQ24TaskDatasetFreezeInputsV1;
use crate::OriginalCellQ24TaskLedgerInputsV1;
use crate::OriginalCellQ24TaskLedgerProducerV1;
use crate::OriginalCellQ24TaskLedgerStatusV1;
use crate::OriginalQ24SuccessorExecutionInputsV1;
use crate::OriginalRootGenerationInitialV1;
use crate::OriginalRootInitialFeatureTargetV1;
use crate::PlasticityRuntimeBootstrapV1;
use crate::PreparedRootInitialFeatureV1;
use crate::PublishedCircuitCellOwnerV1;
use crate::PublishedCircuitFeatureTaskV1;
use crate::circuit_q24_task_channel_v1;
use crate::root_production_inputs::same_actor_phase::OriginalSameActorRootContext;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;

#[path = "same_actor_q24_phase_initial.rs"]
mod initial;
pub(crate) use initial::install_original_initial_task;

#[path = "same_actor_q24_phase_worker.rs"]
mod worker;
pub(crate) use worker::OriginalSameActorTaskWorker;

/// Exact ordinary task resources. Model, bundle, definition and input come
/// from the actual original Initial target and its published task below.
pub struct OriginalSameActorATaskInputsV1 {
    pub files: CircuitQ24TaskFilesV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
    pub fence: TaskFlowFence,
    pub circuit: BoundedCircuitDefinitionV2,
    pub routes: Vec<CircuitCellRouteV1>,
    pub worker_generation: u64,
    pub maximum_cell_records: usize,
    pub queue_capacity: usize,
    pub clock: Arc<dyn Fn() -> CircuitCellTimeV1 + Send + Sync>,
}

/// Supply only after original descriptor preflight. There are no default keys,
/// selections, outcomes, model files or application capabilities.
pub struct OriginalSameActorBusinessInputsV1 {
    pub artifacts: Arc<Mutex<LearningArtifactOwnerService>>,
    pub selected: AgentdSelectedGenerationV1,
    pub initial: OriginalRootInitialFeatureTargetV1,
    pub task: OriginalSameActorATaskInputsV1,
    pub ledger: OriginalCellQ24TaskLedgerInputsV1,
    pub authbus_trust_file: PathBuf,
    pub authbus_checkpoint_file: PathBuf,
    pub objective_profile_file: PathBuf,
    pub plasticity: PlasticityRuntimeBootstrapV1,
    pub host: OriginalSameActorPhaseHostV1,
}

pub struct OriginalSameActorCompletedAInputsV1 {
    pub outcome: AuthenticatedOutcomeV1,
    pub signed: SignedLearningEvidenceV1,
    pub preparation: CellQ24LearningPreparationConfigV1,
    pub history: Vec<CellQ24DatasetTaskV1>,
    pub freeze: OriginalCellQ24TaskDatasetFreezeInputsV1,
}

pub struct OriginalSameActorLearningInputsV1 {
    pub original: OriginalCellQ24LearningInputsV1,
    pub successor_queue_capacity: usize,
}

/// The original decision validates this choice. A failed evaluator cannot be
/// relabeled as Retain, and Retain cannot publish a candidate.
pub enum OriginalSameActorArtifactInputsV1 {
    PublishQualified(Box<LearningArtifactPublishRequestV1>),
    RetainOriginal,
}

/// The actual completion of A remains private to the controller. The host
/// cannot substitute a different predecessor token in this new entry.
pub struct OriginalSameActorCInputsV1 {
    pub predecessor: AgentdGenerationUpdatePredecessorFilesV1<FileAnchorWitnessStore>,
    pub target: AgentdGenerationUpdateTargetV1<FileAnchorWitnessStore>,
    pub definition: codex_hepta_neuron::CellDefinitionV1,
    pub source: CircuitTaskSourceInputV1,
    pub model: Arc<LoadedCellQ24ModelV1>,
    pub execution: OriginalQ24SuccessorExecutionInputsV1,
}

pub struct OriginalSameActorCOutcomeInputsV1 {
    pub outcome: AuthenticatedOutcomeV1,
    pub signed: SignedLearningEvidenceV1,
}

/// No variant submits a task, manufactures a RunStart, signs an Outcome or
/// bypasses the original Control ingress. Root notices only order a request;
/// every original Root owner independently validates its own state.
pub enum OriginalSameActorPhaseCommandV1 {
    InitialRootEnrolled,
    /// Data-only notification for the concrete deployment: externally supplied
    /// material is ready for Root's independent validation. This is no ACK.
    OriginalPreparedMaterialsReady,
    CompleteOriginalA(Box<OriginalSameActorCompletedAInputsV1>),
    Learning(Box<OriginalSameActorLearningInputsV1>),
    /// Independent B's actual Trainer/holdout/runner/evidence inputs, supplied
    /// only after OriginalTraining from this same aggregate and scope.
    Evaluation(Box<crate::OriginalCellQ24EvaluationInputsV1>),
    Artifact(OriginalSameActorArtifactInputsV1),
    Selection(Box<OriginalCellQ24SelectionInputsV1>),
    PublishOriginalC(Box<OriginalSameActorCInputsV1>),
    ObserveOriginalC(Box<OriginalSameActorCOutcomeInputsV1>),
}

/// These are observations, not Ready/admission capabilities or native test
/// results. The real ordinary ingress still checks its own readiness.
pub enum OriginalSameActorPhaseEventV1 {
    InputsOpened {
        identity: Box<AgentdIdentity>,
        phase: String,
    },
    OriginalAOwnersInstalled,
    OriginalAPrepared {
        prepared: Arc<CellQ24PreparedLearningV1>,
        profile: Box<HostAuthorityLearningProfileV1>,
    },
    /// Read-only original Training data and the same actual Trainer readback.
    /// B still must perform its own experiment and supply authenticated inputs;
    /// none of these observations is an Evaluation receipt or success result.
    OriginalTraining {
        snapshot: Box<LearningIterationSnapshotV1>,
        material: Box<crate::OriginalCellQ24TrainingMaterialV1>,
        readback: Box<crate::OriginalCellQ24TrainingReadbackV1>,
    },
    OriginalDecision(Box<LearningIterationSnapshotV1>),
    OriginalArtifactAvailable,
    OriginalSelectionObserved {
        selection: Digest32,
    },
    OriginalCOwnersInstalled,
    OriginalCOutcomeAccepted(Box<OriginalCellQ24TaskLedgerStatusV1>),
}

/// Bounded host coordination only. This object contains no Original Task,
/// source, outcome, issuer, Root session or publication authority.
pub struct OriginalSameActorPhaseHostV1 {
    commands: mpsc::Receiver<OriginalSameActorPhaseCommandV1>,
    events: mpsc::Sender<OriginalSameActorPhaseEventV1>,
    await_prepared_materials_before_retirement: bool,
}

pub fn original_same_actor_phase_host_channel_v1(
    capacity: usize,
) -> Result<
    (
        mpsc::Sender<OriginalSameActorPhaseCommandV1>,
        mpsc::Receiver<OriginalSameActorPhaseEventV1>,
        OriginalSameActorPhaseHostV1,
    ),
    AgentdError,
> {
    if !(1..=64).contains(&capacity) {
        return Err(AgentdError::Invalid(
            "original phase host capacity must be 1..64".into(),
        ));
    }
    let (send, commands) = mpsc::channel(capacity);
    let (events, receive) = mpsc::channel(capacity);
    Ok((
        send,
        receive,
        OriginalSameActorPhaseHostV1 {
            commands, events, await_prepared_materials_before_retirement: false,
        },
    ))
}

/// Only the actual file-backed coordinator uses this private timing mode.
/// The original public typed-host channel retains its immediate retirement.
pub(crate) fn original_same_actor_deployment_host_channel(
    capacity: usize,
) -> Result<
    (
        mpsc::Sender<OriginalSameActorPhaseCommandV1>,
        mpsc::Receiver<OriginalSameActorPhaseEventV1>,
        OriginalSameActorPhaseHostV1,
    ),
    AgentdError,
> {
    let (commands, events, mut host) = original_same_actor_phase_host_channel_v1(capacity)?;
    host.await_prepared_materials_before_retirement = true;
    Ok((commands, events, host))
}

impl OriginalSameActorPhaseHostV1 {
    /// Wait only BEFORE the first original retirement request exists. The
    /// unchanged request creates its own 500 ms budget after this returns.
    /// Cancellation remains inside A's actual owned loop/cleanup scope.
    async fn wait_original_deployment_materials(
        &mut self,
        context: &OriginalSameActorRootContext,
        prepared: &CellQ24PreparedLearningV1,
    ) -> Result<(), AgentdError> {
        if !self.await_prepared_materials_before_retirement {
            return Ok(());
        }
        // Consume the local notification obligation once, before any await.
        self.await_prepared_materials_before_retirement = false;
        let mut closing = CloseSameActorPhaseOnDrop::new(context.gate());
        let expiry = prepared.initial().request.envelope.expiry_unix_seconds;
        require_original_material_time(context, expiry)?;
        let expired = async {
            loop {
                if let Err(error) = require_original_material_time(context, expiry) {
                    return Err(error);
                }
                tokio::time::sleep(std::time::Duration::from_millis(5)).await;
            }
        };
        let ready = tokio::select! {
            received = self.receive_original(context) => received,
            result = expired => result,
        }?;
        if !matches!(ready, OriginalSameActorPhaseCommandV1::OriginalPreparedMaterialsReady) {
            return Err(phase_refused("original prepared-material notification is missing"));
        }
        require_original_material_time(context, expiry)?;
        closing.disarm();
        Ok(())
    }

    pub(crate) fn notify_original(
        &self,
        context: &OriginalSameActorRootContext,
        event: OriginalSameActorPhaseEventV1,
    ) -> Result<(), AgentdError> {
        let mut closing = CloseSameActorPhaseOnDrop::new(context.gate());
        OriginalSameActorRootContext::require_current(context)?;
        self.events
            .try_send(event)
            .map_err(|_| phase_refused("original phase host notification lost"))?;
        OriginalSameActorRootContext::require_current(context)?;
        closing.disarm();
        Ok(())
    }

    pub(crate) async fn receive_original(
        &mut self,
        context: &OriginalSameActorRootContext,
    ) -> Result<OriginalSameActorPhaseCommandV1, AgentdError> {
        let mut closing = CloseSameActorPhaseOnDrop::new(context.gate());
        OriginalSameActorRootContext::require_current(context)?;
        let received = tokio::select! {
            _ = context.gate().cancelled() => return Err(phase_refused("original phase is closed")),
            received = self.commands.recv() => received,
        }
        .ok_or_else(|| phase_refused("original phase host command stream closed"))?;
        OriginalSameActorRootContext::require_current(context)?;
        closing.disarm();
        Ok(received)
    }
}

struct OriginalSameActorAOwners {
    bootstrap: CircuitTaskRuntimeBootstrapV1,
    source: Arc<CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>>,
    cell: PublishedCircuitCellOwnerV1<FileAnchorWitnessStore>,
    ledger: Arc<OriginalCellQ24TaskLedgerProducerV1>,
    published: PublishedCircuitFeatureTaskV1,
}

fn require_original_material_time(
    context: &OriginalSameActorRootContext,
    expiry_unix_seconds: u64,
) -> Result<(), AgentdError> {
    OriginalSameActorRootContext::require_current(context)?;
    let now = context.clock().now_unix_ms().map_err(phase_owner_error)? / 1_000;
    if now >= expiry_unix_seconds {
        return Err(phase_refused("original prepared business deadline elapsed"));
    }
    OriginalSameActorRootContext::require_current(context)
}

fn phase_refused(message: &str) -> AgentdError {
    AgentdError::GenerationFenced(message.into())
}

fn phase_owner_error(error: impl std::error::Error + Send + Sync + 'static) -> AgentdError {
    // Preserve the actual owner error and uncertainty cause. No error is
    // changed into "not executed", a safe retry, or a NoUpdate result.
    AgentdError::Io(std::io::Error::other(error))
}
