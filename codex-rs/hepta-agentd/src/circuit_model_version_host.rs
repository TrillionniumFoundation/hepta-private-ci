//! One positive Version host consumes original publication and C custody.
//! Mutable Version state is released before all Model and Root issuer I/O.
//! Failed or cancelled effects retain only metadata for actual readonly recovery.
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU8;
use std::time::Duration;
use std::time::Instant;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tokio::runtime::Handle;
use tokio::sync::Notify;
use tokio::sync::Semaphore;
use super::Error;
use super::Origin;
use super::OriginalCircuitModelTaskInputsV1;
use super::task::ModelVersionInstalledTaskV1;
use crate::AgentdConfig;
use crate::AgentdIdentity;
use crate::AgentdUnixFinalUseGrantProvider;
use crate::CircuitTaskSourceReadbackV1;
use crate::NeuronGenerationCurrentOwnerV1;
use crate::OriginalCellQ24ModelCommandClientV1;
use crate::OriginalCircuitModelPublicationContextV1 as Context;
use crate::OriginalCircuitModelPublicationInputsV1;
use crate::OriginalCircuitModelPublicationPredecessorsV1 as Predecessors;
use crate::OriginalRootModelVersionIssuerV1;
use crate::PublishedCircuitCellOwnerV1;

#[path = "circuit_model_version_artifact.rs"]
mod artifact;
#[path = "circuit_model_version_effect.rs"]
mod effect;
#[path = "circuit_model_version_state.rs"]
mod current;
#[path = "circuit_model_version_service.rs"]
mod service;

type Inputs = OriginalCircuitModelPublicationInputsV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;

/// Exact identity of an already committed original Artifact transaction.
pub struct OriginalCircuitModelArtifactCheckpointV1 {
    pub operation_id: StableId,
    pub intent_digest: Digest32,
}
pub struct OriginalCircuitModelVersionRecoveryV1 {
    pub context: Context,
    pub intent_digest: Digest32,
    pub cell: PublishedCircuitCellOwnerV1<FileAnchorWitnessStore>,
    pub source: Arc<CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>>,
    pub identity: AgentdIdentity,
    pub current: Arc<NeuronGenerationCurrentOwnerV1>,
    pub artifacts: Arc<Mutex<LearningArtifactOwnerService>>,
    pub artifact_checkpoint: OriginalCircuitModelArtifactCheckpointV1,
    pub artifact_selection: SignedArtifactSelectionV1,
    pub artifact_verifier: ArtifactSelectionVerifierV1,
}
struct ModelVersionArtifactOwner {
    owner: Arc<Mutex<LearningArtifactOwnerService>>,
    checkpoint: OriginalCircuitModelArtifactCheckpointV1,
    selection: SignedArtifactSelectionV1,
    verifier: ArtifactSelectionVerifierV1,
    withdrawal_scope: Digest32,
    withdrawal_head: Digest32,
}
struct Awaiting {
    inputs: Box<Inputs>,
    task: OriginalCircuitModelTaskInputsV1,
    issuer: OriginalRootModelVersionIssuerV1,
}
struct State {
    awaiting: Option<Awaiting>,
    // Pins do not assert CURRENT. Every read uses a new actual Model operation.
    context: Option<Arc<Context>>,
    intent: Option<Digest32>,
    installed: Option<ModelVersionInstalledTaskV1>,
    config: Option<AgentdConfig>,
}
pub struct OriginalCircuitModelVersionHostV1 {
    predecessors: Predecessors,
    initial_binding: Digest32,
    model: OriginalCellQ24ModelCommandClientV1,
    control: Arc<NeuronGenerationCurrentOwnerV1>,
    artifacts: ModelVersionArtifactOwner,
    origin: Origin,
    state: Mutex<State>,
    requested: AtomicBool,
    runtime_started: AtomicBool,
    outcome: AtomicU8,
    end: Instant,
    runtime: Handle,
    connections: Arc<Semaphore>,
    installed: Notify,
}
impl OriginalCircuitModelVersionHostV1 {
    /// Consume actual native host capabilities. The Model client and issuer
    /// already retain their original peer/pidfd/deadline; no socket is opened.
    /// Actual Model matching happens before the first preparation effect.
    pub fn from_original_owners(
        predecessors: Predecessors,
        model: OriginalCellQ24ModelCommandClientV1,
        inputs: Inputs,
        task: OriginalCircuitModelTaskInputsV1,
        checkpoint: OriginalCircuitModelArtifactCheckpointV1,
        issuer: AgentdUnixFinalUseGrantProvider,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let (initial_binding, _) = predecessors.material.require_original_command_initial()?;
        task.require_completed_a(&inputs.completed)?;
        let artifacts = ModelVersionArtifactOwner::new(
            Arc::clone(&inputs.authorities.artifacts), checkpoint,
            inputs.selection.signed.clone(), inputs.selection.verifier.clone(),
        )?;
        let control = Arc::clone(&inputs.current);
        let issuer = issuer.into_original_model_version_issuer()?;
        Self::new(predecessors, initial_binding, model, control, artifacts, Origin::Fresh,
            State { awaiting: Some(Awaiting { inputs: Box::new(inputs), task, issuer }),
                context: None, intent: None, installed: None, config: None }, lifetime)
    }

    /// Actual already-held C owners only. No prepared files, issuer, creation
    /// flag or factory replay is available to this permanent readback profile.
    pub fn recover_from_original_owners(
        predecessors: Predecessors,
        model: OriginalCellQ24ModelCommandClientV1,
        original: OriginalCircuitModelVersionRecoveryV1,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        if original.intent_digest.is_zero() { return Err(Error::Binding("original Version intent")); }
        let (initial_binding, _) = predecessors.material.require_original_command_initial()?;
        let artifacts = ModelVersionArtifactOwner::new(
            original.artifacts, original.artifact_checkpoint,
            original.artifact_selection, original.artifact_verifier,
        )?;
        let installed = ModelVersionInstalledTaskV1 {
            cell: original.cell, source: original.source, identity: original.identity,
            intent: original.intent_digest,
        };
        installed.observe(&original.context)?;
        Self::new(predecessors, initial_binding, model, original.current, artifacts,
            Origin::Recovered, State { awaiting: None, context: Some(Arc::new(original.context)),
                intent: Some(original.intent_digest), installed: Some(installed), config: None }, lifetime)
    }

    fn new(
        predecessors: Predecessors, initial_binding: Digest32,
        model: OriginalCellQ24ModelCommandClientV1, control: Arc<NeuronGenerationCurrentOwnerV1>,
        artifacts: ModelVersionArtifactOwner, origin: Origin, state: State, lifetime: Duration,
    ) -> Result<Self, Error> {
        if lifetime.is_zero() || lifetime > Duration::from_secs(300) {
            return Err(Error::Binding("original positive Version lifetime"));
        }
        Ok(Self {
            predecessors, initial_binding, model, control, artifacts, origin, state: Mutex::new(state),
            requested: AtomicBool::new(origin == Origin::Recovered),
            runtime_started: AtomicBool::new(origin == Origin::Recovered),
            outcome: AtomicU8::new(if origin == Origin::Recovered { 4 } else { 0 }),
            end: Instant::now().checked_add(lifetime).ok_or(Error::Clock)?,
            runtime: Handle::try_current().map_err(|_| Error::Unavailable)?,
            connections: Arc::new(Semaphore::new(4)), installed: Notify::new(),
        })
    }
    fn require_lifetime(&self) -> Result<(), Error> {
        if Instant::now() >= self.end { return Err(Error::Unavailable); }
        Ok(())
    }
    fn original_predecessors(&self) -> Predecessors {
        Predecessors {
            material: self.predecessors.material.clone(),
            registration: self.predecessors.registration.clone(),
            dataset: self.predecessors.dataset.clone(),
            training: self.predecessors.training.clone(),
            evaluation: self.predecessors.evaluation.clone(),
        }
    }
}
