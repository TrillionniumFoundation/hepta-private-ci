//! Original Model -> independently selected Artifact -> original FinalUse
//! publication -> sealed distinct C. No issuer, grant, key or registry is made.
//! The original Model and complete B/retention material bracket every effect.
//! An uncertain effect is recovered only by its existing original operation.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::AgentdGenerationSelectionFilesV1;
use crate::AgentdGenerationUpdateAuthoritiesV1;
use crate::AgentdGenerationUpdatePredecessorFilesV1;
use crate::AgentdGenerationUpdateRequestV1;
use crate::AgentdGenerationUpdateTargetV1;
use crate::AgentdSelectedGenerationV1;
use crate::CircuitTaskSourceInputV1;
use crate::NeuronGenerationCurrentOwnerV1;
use crate::OriginalCellEvaluationCommandErrorV1;
use crate::OriginalCellEvaluationModelMaterialClientV1;
use crate::OriginalCellQ24ModelCommandClientV1;
use crate::OriginalCellQ24ModelCommandErrorV1;
use crate::PreparedAgentdGenerationUpdateV1;
use crate::PublishedCircuitFeatureCompletionV1;
use crate::PublishedCircuitFeatureTaskV1;

#[path = "circuit_learning_model_binding.rs"]
mod binding;
#[path = "circuit_learning_model_context.rs"]
mod context;
#[path = "circuit_learning_model_recovery.rs"]
mod recovery;

pub use context::OriginalCircuitModelPublicationContextV1;
pub use recovery::OriginalCircuitModelPublicationRecoveryV1;
pub use recovery::recover_original_circuit_model_publication_v1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCircuitModelPublicationErrorV1 {
    #[error("original Model publication binding: {0}")]
    Binding(&'static str),
    #[error("original Model publication work deadline expired")]
    DeadlineExceeded,
    #[error("original Model publication clock regressed or is unavailable")]
    Clock,
    #[error("original Model publication was cancelled before its queued operation")]
    Cancelled,
    #[error("original Model publication may have effects; original operation readback only: {0}")]
    CommitUncertain(String),
    #[error("original Model readback: {0}")]
    Model(#[from] OriginalCellQ24ModelCommandErrorV1),
    #[error("original B/retention readback: {0}")]
    Evaluation(#[from] OriginalCellEvaluationCommandErrorV1),
    #[error("original version owner: {0}")]
    Owner(#[from] AgentdError),
    #[error("original iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original predecessor signatures: {0}")]
    Evidence(#[from] SignedEvidenceError),
}
type Error = OriginalCircuitModelPublicationErrorV1;

/// Original immutable Artifact files plus its independent original selection.
/// An E Qualified result is insufficient to construct this authority.
pub struct OriginalCircuitModelPublicationSelectionV1 {
    pub verifier: ArtifactSelectionVerifierV1,
    pub signed: SignedArtifactSelectionV1,
    pub files: AgentdGenerationSelectionFilesV1,
}

pub struct OriginalCircuitModelPublicationInputsV1<Old: AnchorWitnessStore, New: AnchorWitnessStore> {
    pub current: Arc<NeuronGenerationCurrentOwnerV1>,
    pub authorities: AgentdGenerationUpdateAuthoritiesV1,
    pub selection: OriginalCircuitModelPublicationSelectionV1,
    pub predecessor: AgentdGenerationUpdatePredecessorFilesV1<Old>,
    pub target: AgentdGenerationUpdateTargetV1<New>,
    pub definition: CellDefinitionV1,
    pub source: CircuitTaskSourceInputV1,
    pub completed: PublishedCircuitFeatureCompletionV1,
}

/// The original old/new locks and the two originally delivered read clients
/// remain in this non-Clone value until publication. Its intent is data only.
pub struct PreparedOriginalCircuitModelPublicationV1<Old: AnchorWitnessStore, New: AnchorWitnessStore> {
    context: OriginalCircuitModelPublicationContextV1,
    model: OriginalCellQ24ModelCommandClientV1,
    evaluator: OriginalCellEvaluationModelMaterialClientV1,
    prepared: PreparedAgentdGenerationUpdateV1<Old, New>,
    definition: CellDefinitionV1,
    source: CircuitTaskSourceInputV1,
    completed: PublishedCircuitFeatureCompletionV1,
}

/// Produced only after original publication or original-operation recovery and
/// final physical Model/E reads. This grants no Selector or ordinary execution.
pub struct OriginalCircuitModelPublicationV1 {
    context: OriginalCircuitModelPublicationContextV1,
    task: PublishedCircuitFeatureTaskV1,
}

impl OriginalCircuitModelPublicationV1 {
    pub fn into_original_task(
        self,
    ) -> (PublishedCircuitFeatureTaskV1, OriginalCircuitModelPublicationContextV1) {
        (self.task, self.context)
    }
}

pub async fn prepare_original_circuit_model_publication_v1<Old, New>(
    context: OriginalCircuitModelPublicationContextV1,
    model: OriginalCellQ24ModelCommandClientV1,
    evaluator: OriginalCellEvaluationModelMaterialClientV1,
    inputs: OriginalCircuitModelPublicationInputsV1<Old, New>,
) -> Result<PreparedOriginalCircuitModelPublicationV1<Old, New>, Error>
where
    Old: AnchorWitnessStore + Send + 'static,
    New: AnchorWitnessStore + Send + 'static,
{
    let started = now()?;
    let observation = evaluator.begin_model_read().await?;
    let original_expiry = context.authenticate_material(observation.material(), started, true)?;
    context.require_model_current(&model, true).await?;
    binding::require_inputs(&context, &inputs)?;
    let queued = QueuedPublicationFence::new();
    let cancelled = Arc::clone(&queued.cancelled);
    let (context, prepared, definition, source, completed) = tokio::task::spawn_blocking(move || {
        context.authenticate(started, true)?;
        require_not_cancelled(&cancelled)?;
        binding::require_inputs(&context, &inputs)?;
        let coordinator = context.authenticate(now()?, true)?;
        let operation = crate::learning_updated_task_operation_id_v1(&coordinator)?;
        let selected = load_original_selection(&inputs.authorities, inputs.selection)?;
        if selected.manifest() != &inputs.target.config.manifest {
            return Err(Error::Binding("selected Artifact differs from original candidate manifest"));
        }
        context.authenticate(started, true)?;
        require_predecessor_window(started, original_expiry)?;
        require_not_cancelled(&cancelled)?;
        let prepared = crate::prepare_agentd_generation_cold_drained_update_v1(
            inputs.current,
            inputs.authorities,
            inputs.predecessor,
            selected,
            inputs.target,
            AgentdGenerationUpdateRequestV1 { operation_id: operation.to_string() },
        ).map_err(uncertain)?;
        context.authenticate(started, true).map_err(uncertain)?;
        Ok::<_, Error>((context, prepared, inputs.definition, inputs.source, inputs.completed))
    }).await.map_err(uncertain)??;
    drop(queued);
    context.require_model_current(&model, true).await.map_err(uncertain)?;
    let material = observation.finish().await.map_err(uncertain)?;
    context.authenticate_material(&material, started, true).map_err(uncertain)?;
    Ok(PreparedOriginalCircuitModelPublicationV1 {
        context, model, evaluator, prepared, definition, source, completed,
    })
}

impl<Old: AnchorWitnessStore + Send + 'static, New: AnchorWitnessStore + Send + 'static>
    PreparedOriginalCircuitModelPublicationV1<Old, New>
{
    pub fn final_use_binding(&self) -> &FinalUseBinding {
        self.prepared.final_use_binding()
    }

    pub fn intent_digest(&self) -> Digest32 {
        self.prepared.intent_digest()
    }

    /// The original issuer must supply this exact already-authorized grant.
    /// No Root admission grant, E result or Model record is converted to it.
    pub async fn publish_original_model_task(
        self,
        signed: SignedFinalUseGrant,
    ) -> Result<OriginalCircuitModelPublicationV1, Error> {
        let Self { context, model, evaluator, prepared, definition, source, completed } = self;
        let started = now()?;
        let observation = evaluator.begin_model_read().await?;
        let original_expiry = context.authenticate_material(observation.material(), started, true)?;
        context.require_model_current(&model, true).await?;
        let queued = QueuedPublicationFence::new();
        let cancelled = Arc::clone(&queued.cancelled);
        let (context, task) = tokio::task::spawn_blocking(move || {
            context.authenticate(started, true)?;
            require_predecessor_window(started, original_expiry)?;
            require_not_cancelled(&cancelled)?;
            let ready = PreparedAgentdGenerationUpdateV1::publish(prepared, &signed)
                .map_err(uncertain)?;
            let task = ready.into_circuit_feature_task(definition, source, completed)
                .map_err(uncertain)?;
            binding::require_published(&context, &task, true).map_err(uncertain)?;
            Ok::<_, Error>((context, task))
        }).await.map_err(uncertain)??;
        drop(queued);
        // All version I/O is complete before these actual original reads.
        // No physical effect follows the final complete material authentication.
        context.require_model_current(&model, true).await.map_err(uncertain)?;
        let material = observation.finish().await.map_err(uncertain)?;
        context.authenticate_material(&material, started, true).map_err(uncertain)?;
        Ok(OriginalCircuitModelPublicationV1 { context, task })
    }
}

fn load_original_selection(
    authorities: &AgentdGenerationUpdateAuthoritiesV1,
    selection: OriginalCircuitModelPublicationSelectionV1,
) -> Result<AgentdSelectedGenerationV1, Error> {
    let artifacts = authorities.artifacts.lock()
        .map_err(|_| Error::Binding("original Artifact owner lock"))?;
    Ok(AgentdSelectedGenerationV1::load(
        &artifacts,
        selection.verifier,
        selection.signed,
        selection.files,
        authorities.now()?,
    )?)
}

struct QueuedPublicationFence {
    cancelled: Arc<AtomicBool>,
}
impl QueuedPublicationFence {
    fn new() -> Self {
        Self { cancelled: Arc::new(AtomicBool::new(false)) }
    }
}
impl Drop for QueuedPublicationFence {
    fn drop(&mut self) {
        self.cancelled.store(true, Ordering::Release);
    }
}
fn require_not_cancelled(cancelled: &AtomicBool) -> Result<(), Error> {
    if cancelled.load(Ordering::Acquire) {
        return Err(Error::Cancelled);
    }
    Ok(())
}

fn require_predecessor_window(started: u64, expiry: u64) -> Result<(), Error> {
    let current = now()?;
    if current < started {
        return Err(Error::Clock);
    }
    if current >= expiry {
        return Err(Error::DeadlineExceeded);
    }
    Ok(())
}

fn now() -> Result<u64, Error> {
    SystemTime::now().duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs()).map_err(|_| Error::Clock)
}
fn uncertain(error: impl std::fmt::Display) -> Error {
    Error::CommitUncertain(error.to_string())
}
