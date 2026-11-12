//! Original TrainingNoUpdate -> retained version -> distinct ordinary C task.
//!
//! The original host supplies Artifact CURRENT, an independent signed artifact
//! selection, both journal files/witnesses, Control CURRENT and FinalUse custody.
//! No grant is issued here. Candidate updates, Model publication and execution
//! of C are outside this profile. Resident admission grants are not accepted.
//! Preparation retains the original old/new locks. A dropped or failed effect
//! has only original-operation readback; it is never retried as fresh work.

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
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCellQ24TrainingCommandErrorV1;
use crate::PreparedAgentdGenerationUpdateV1;
use crate::PublishedCircuitFeatureCompletionV1;
use crate::PublishedCircuitFeatureTaskV1;

#[path = "circuit_learning_retained_binding.rs"]
mod binding;
#[path = "circuit_learning_retained_context.rs"]
mod context;
#[path = "circuit_learning_retained_recovery.rs"]
mod recovery;
pub use context::OriginalCircuitRetainedPublicationContextV1;
use context::PublicationAccess;
pub use recovery::OriginalCircuitRetainedPublicationRecoveryV1;
pub use recovery::recover_original_circuit_retained_publication_v1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCircuitRetainedPublicationErrorV1 {
    #[error("original retained publication binding: {0}")]
    Binding(&'static str),
    #[error("original retained publication work deadline expired")]
    DeadlineExceeded,
    #[error("original retained publication clock regressed or is unavailable")]
    Clock,
    #[error("retained publication was cancelled before its queued operation")]
    Cancelled,
    #[error("retained publication may have effects; original operation readback only: {0}")]
    CommitUncertain(String),
    #[error("original Trainer readback: {0}")]
    Training(#[from] OriginalCellQ24TrainingCommandErrorV1),
    #[error("original version owner: {0}")]
    Owner(#[from] AgentdError),
    #[error("original iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original Training signature: {0}")]
    Evidence(#[from] SignedEvidenceError),
}

/// Actual independently supplied selection and immutable files. A digest or
/// cached unsigned selection cannot replace these inputs.
pub struct OriginalCircuitRetainedPublicationSelectionV1 {
    pub verifier: ArtifactSelectionVerifierV1,
    pub signed: SignedArtifactSelectionV1,
    pub files: AgentdGenerationSelectionFilesV1,
}

pub struct OriginalCircuitRetainedPublicationInputsV1<Old: AnchorWitnessStore, New: AnchorWitnessStore> {
    pub current: Arc<NeuronGenerationCurrentOwnerV1>,
    pub authorities: AgentdGenerationUpdateAuthoritiesV1,
    pub selection: OriginalCircuitRetainedPublicationSelectionV1,
    pub predecessor: AgentdGenerationUpdatePredecessorFilesV1<Old>,
    pub target: AgentdGenerationUpdateTargetV1<New>,
    pub definition: CellDefinitionV1,
    pub source: CircuitTaskSourceInputV1,
    pub completed: PublishedCircuitFeatureCompletionV1,
}

/// Non-Clone custody of the exact preparation. The host retains intent_digest
/// before requesting the separate original FinalUse signature. Neither getter
/// grants publication or starts C; no old grant is replaced or renewed.
pub struct PreparedOriginalCircuitRetainedPublicationV1<Old: AnchorWitnessStore, New: AnchorWitnessStore> {
    context: OriginalCircuitRetainedPublicationContextV1,
    trainer: OriginalCellQ24TrainingCommandClientV1,
    prepared: PreparedAgentdGenerationUpdateV1<Old, New>,
    definition: CellDefinitionV1,
    source: CircuitTaskSourceInputV1,
    completed: PublishedCircuitFeatureCompletionV1,
}

/// Consume original capabilities only after an actual current Trainer read.
/// A host must reconcile a lost preparation ACK using its retained Control
/// intent; another prepare call cannot repair or overwrite nonempty targets.
pub async fn prepare_original_circuit_retained_publication_v1<Old, New>(
    context: OriginalCircuitRetainedPublicationContextV1,
    trainer: OriginalCellQ24TrainingCommandClientV1,
    inputs: OriginalCircuitRetainedPublicationInputsV1<Old, New>,
) -> Result<PreparedOriginalCircuitRetainedPublicationV1<Old, New>, OriginalCircuitRetainedPublicationErrorV1>
where
    Old: AnchorWitnessStore + Send + 'static,
    New: AnchorWitnessStore + Send + 'static,
{
    context.require_training_current(&trainer, PublicationAccess::NewWork).await?;
    binding::require_inputs(&context, &inputs)?;
    let queued = QueuedPublicationFence::new();
    let cancelled = Arc::clone(&queued.cancelled);
    let (context, prepared, definition, source, completed) = tokio::task::spawn_blocking(move || {
        let started = now()?;
        context.authenticate(started, PublicationAccess::NewWork)?;
        require_not_cancelled(&cancelled)?;
        binding::require_inputs(&context, &inputs)?;
        let coordinator = context.authenticate(now()?, PublicationAccess::NewWork)?;
        let operation = crate::learning_retained_task_operation_id_v1(&coordinator)?;
        let selected = load_original_selection(&inputs.authorities, inputs.selection)?;
        if selected.manifest() != &inputs.target.config.manifest {
            return Err(OriginalCircuitRetainedPublicationErrorV1::Binding(
                "selected original artifact differs from retained manifest",
            ));
        }
        let before = now()?;
        if before < started {
            return Err(OriginalCircuitRetainedPublicationErrorV1::Clock);
        }
        context.authenticate(before, PublicationAccess::NewWork)?;
        require_not_cancelled(&cancelled)?;
        let prepared = crate::prepare_agentd_generation_cold_same_model_task_v1(
            inputs.current,
            inputs.authorities,
            inputs.predecessor,
            selected,
            inputs.target,
            AgentdGenerationUpdateRequestV1 { operation_id: operation.to_string() },
        ).map_err(uncertain)?;
        let after = now().map_err(uncertain)?;
        if after < before {
            return Err(uncertain(OriginalCircuitRetainedPublicationErrorV1::Clock));
        }
        context.authenticate(after, PublicationAccess::NewWork).map_err(uncertain)?;
        Ok::<_, OriginalCircuitRetainedPublicationErrorV1>((
            context, prepared, inputs.definition, inputs.source, inputs.completed,
        ))
    }).await.map_err(uncertain)??;
    drop(queued);
    context.require_training_current(&trainer, PublicationAccess::NewWork).await.map_err(uncertain)?;
    Ok(PreparedOriginalCircuitRetainedPublicationV1 {
        context, trainer, prepared, definition, source, completed,
    })
}

impl<Old: AnchorWitnessStore + Send + 'static, New: AnchorWitnessStore + Send + 'static>
    PreparedOriginalCircuitRetainedPublicationV1<Old, New>
{
    pub fn final_use_binding(&self) -> &FinalUseBinding {
        self.prepared.final_use_binding()
    }

    pub fn intent_digest(&self) -> Digest32 {
        self.prepared.intent_digest()
    }

    /// Only the separately supplied exact original FinalUse grant may publish.
    /// A cancelled queued closure sends no local publication. Once the owner
    /// call began, loss/cancellation remains uncertain even if C was installed.
    pub async fn publish_original_retained_task(
        self,
        signed: SignedFinalUseGrant,
    ) -> Result<PublishedCircuitFeatureTaskV1, OriginalCircuitRetainedPublicationErrorV1> {
        self.context.require_training_current(&self.trainer, PublicationAccess::NewWork).await?;
        let queued = QueuedPublicationFence::new();
        let cancelled = Arc::clone(&queued.cancelled);
        let Self { context, trainer, prepared, definition, source, completed } = self;
        let (context, task) = tokio::task::spawn_blocking(move || {
            let started = now()?;
            context.authenticate(started, PublicationAccess::NewWork)?;
            require_not_cancelled(&cancelled)?;
            let ready = PreparedAgentdGenerationUpdateV1::publish(prepared, &signed).map_err(uncertain)?;
            let task = ready.into_circuit_feature_task(definition, source, completed).map_err(uncertain)?;
            binding::require_published(&context, &task, PublicationAccess::NewWork).map_err(uncertain)?;
            if now().map_err(uncertain)? < started {
                return Err(uncertain(OriginalCircuitRetainedPublicationErrorV1::Clock));
            }
            Ok::<_, OriginalCircuitRetainedPublicationErrorV1>((context, task))
        }).await.map_err(uncertain)??;
        drop(queued);
        context.require_training_current(&trainer, PublicationAccess::NewWork).await.map_err(uncertain)?;
        tokio::task::spawn_blocking(move || {
            binding::require_published(&context, &task, PublicationAccess::NewWork).map_err(uncertain)?;
            Ok::<_, OriginalCircuitRetainedPublicationErrorV1>(task)
        }).await.map_err(uncertain)?
    }
}

fn load_original_selection(
    authorities: &AgentdGenerationUpdateAuthoritiesV1,
    selection: OriginalCircuitRetainedPublicationSelectionV1,
) -> Result<AgentdSelectedGenerationV1, OriginalCircuitRetainedPublicationErrorV1> {
    let artifacts = authorities.artifacts.lock()
        .map_err(|_| OriginalCircuitRetainedPublicationErrorV1::Binding("original artifact owner lock"))?;
    Ok(AgentdSelectedGenerationV1::load(
        &artifacts, selection.verifier, selection.signed, selection.files, authorities.now()?,
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
fn require_not_cancelled(cancelled: &AtomicBool) -> Result<(), OriginalCircuitRetainedPublicationErrorV1> {
    if cancelled.load(Ordering::Acquire) {
        return Err(OriginalCircuitRetainedPublicationErrorV1::Cancelled);
    }
    Ok(())
}

fn now() -> Result<u64, OriginalCircuitRetainedPublicationErrorV1> {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|time| time.as_secs())
        .map_err(|_| OriginalCircuitRetainedPublicationErrorV1::Clock)
}
fn uncertain(error: impl std::fmt::Display) -> OriginalCircuitRetainedPublicationErrorV1 {
    OriginalCircuitRetainedPublicationErrorV1::CommitUncertain(error.to_string())
}
