//! An ordinary Feature task under the existing actual CURRENT/FinalUse owners.
//! Only Ready publication owners construct this adapter. The original journal
//! remains exclusively held; no digest, callback, key or replacement grant can
//! stand in for its live selected-artifact and consumed-use checks.

use std::fs::File;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_neuron::CellGenerationCurrentV1;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_neuron::CellJournalPartitionV1;
use codex_hepta_neuron::CellOwnerJournalV1;
use codex_hepta_neuron::CellStepInputV1;
use codex_hepta_neuron::canonical_cell_step_request_digest_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::CircuitTaskSourceInputV1;
use crate::CircuitTaskSourcePublicationV1;
use crate::CircuitTaskSourceReadbackV1;
use crate::PublishedNeuronGenerationInitialV1;
use crate::PublishedNeuronGenerationUpdateV1;
use crate::neuron_generation_update_bootstrap::GenerationLearningReadbackV1;
use crate::neuron_generation_update_live::LiveGenerationCurrent;

#[path = "circuit_feature_current_control.rs"]
mod control;
#[path = "circuit_feature_current_learning.rs"]
mod learning;
#[path = "circuit_candidate_learning_read_capability.rs"]
mod candidate_learning_read;
pub use candidate_learning_read::OriginalCircuitCandidateLearningReadClientV1;
pub use candidate_learning_read::OriginalCircuitCandidateLearningReadContextV1;
pub use candidate_learning_read::OriginalCircuitCandidateLearningReadErrorV1;
pub use candidate_learning_read::OriginalCircuitCandidateLearningReadOwnerV1;
pub use candidate_learning_read::OriginalCircuitCandidateLearningReadbackV1;
pub(crate) use candidate_learning_read::OriginalCircuitCandidateCompletionReadinessClientV1;

#[path = "circuit_learning_read_capability.rs"]
mod learning_read;
#[path = "circuit_feature_current_owner.rs"]
mod owner;
#[path = "circuit_feature_current_recovery.rs"]
mod recovery;
#[path = "circuit_feature_current_retirement.rs"]
mod retirement;

#[path = "circuit_learning_retained_publication.rs"]
mod retained_publication;

#[path = "circuit_learning_model_publication.rs"]
mod model_publication;
pub use model_publication::OriginalCircuitModelPublicationContextV1;
pub use model_publication::OriginalCircuitModelPublicationErrorV1;
pub use model_publication::OriginalCircuitModelPublicationInputsV1;
pub use model_publication::OriginalCircuitModelPublicationPredecessorsV1;
pub use model_publication::OriginalCircuitModelPublicationRecoveryV1;
pub use model_publication::OriginalCircuitModelPublicationSelectionV1;
pub use model_publication::OriginalCircuitModelPublicationV1;
pub use model_publication::PreparedOriginalCircuitModelPublicationV1;
pub use model_publication::prepare_original_circuit_model_publication_v1;
pub use model_publication::recover_original_circuit_model_publication_v1;
pub use control::PublishedCircuitFeatureControlV1;
pub(crate) use learning_read::OriginalCircuitCompletionReadinessClientV1;
pub use learning_read::OriginalCircuitLearningReadClientV1;
pub use learning_read::OriginalCircuitLearningReadContextV1;
pub use learning_read::OriginalCircuitLearningReadErrorV1;
pub use learning_read::OriginalCircuitLearningReadOwnerV1;
pub use learning_read::OriginalCircuitLearningReadbackV1;
#[cfg(test)]
pub(crate) use learning_read::fixture as original_learning_read_fixture;
pub use owner::PublishedCircuitCellOwnerV1;
pub use recovery::CircuitFeaturePredecessorFilesV1;
pub(crate) use recovery::recover_predecessor;
pub use retained_publication::OriginalCircuitRetainedPublicationContextV1;
pub use retained_publication::OriginalCircuitRetainedPublicationErrorV1;
pub use retained_publication::OriginalCircuitRetainedPublicationInputsV1;
pub use retained_publication::OriginalCircuitRetainedPublicationRecoveryV1;
pub use retained_publication::OriginalCircuitRetainedPublicationSelectionV1;
pub use retained_publication::PreparedOriginalCircuitRetainedPublicationV1;
pub use retained_publication::prepare_original_circuit_retained_publication_v1;
pub use retained_publication::recover_original_circuit_retained_publication_v1;
pub use retained_publication::version::OriginalCircuitRetainedArtifactCheckpointV1;
pub use retained_publication::version::OriginalCircuitRetainedTaskInputsV1;
pub use retained_publication::version::OriginalCircuitRetainedVersionClientV1;
pub use retained_publication::version::OriginalCircuitRetainedVersionErrorV1;
pub use retained_publication::version::OriginalCircuitRetainedVersionHostV1;
pub use retained_publication::version::OriginalCircuitRetainedVersionPublicationV1;
pub use retained_publication::version::OriginalCircuitRetainedVersionReadbackV1;
pub use retained_publication::version::OriginalCircuitRetainedVersionRecoveryV1;

/// Pin this exact profile in the original target.task_digest BEFORE independent
/// selection/FinalUse publication. Existing arbitrary task grants do not match.
pub fn circuit_feature_task_digest_v1(
    definition: &CellDefinitionV1,
    source: &CircuitTaskSourceInputV1,
) -> Result<Digest32, AgentdError> {
    if source.scope.cell_id != definition.cell_id
        || source.scope.principal_digest.is_zero()
        || source.source_frontier.is_zero()
        || source.objective_digest.is_zero()
        || source.ndu_snapshot_digest.is_zero()
        || source.monotonic_micros == 0
        || source.deadline_micros <= source.monotonic_micros
        || !(1..=3_600_000).contains(&source.lease_duration_ms)
        || source.deadline_micros - source.monotonic_micros > source.lease_duration_ms * 1_000
        || source.observation.is_empty()
        || source.observation.len() > 32 * 1_024
        || source.candidates.len() != definition.candidates.len()
        || source
            .candidates
            .iter()
            .zip(&definition.candidates)
            .any(|(mask, candidate)| mask.candidate_id != candidate.candidate_id)
    {
        return Err(invalid("ordinary Feature task material differs"));
    }
    let input = source_input(
        source,
        StableId::new("published-feature-task").map_err(invalid)?,
    );
    let semantic = canonical_cell_step_request_digest_v1(definition, &input).map_err(invalid)?;
    Ok(Digest32::of_parts(&[
        b"hepta.agentd.published-circuit-feature-task.v1\0",
        semantic.as_array(),
        &source.lease_duration_ms.to_be_bytes(),
    ]))
}

enum Publication {
    Initial(PublishedNeuronGenerationInitialV1),
    Update {
        original: PublishedNeuronGenerationUpdateV1,
        previous: PublishedCircuitFeatureCompletionV1,
    },
}

impl Publication {
    fn target(&self) -> &CellGenerationOwnerBindingV1 {
        match self {
            Self::Initial(p) => p.target(),
            Self::Update { original, .. } => original.target(),
        }
    }
}

/// Erase only the witness-store type while retaining the actual original
/// journal. No external implementation or replacement authority is accepted.
trait OriginalVersion: Send {
    fn require_current(&self) -> Result<(), AgentdError>;
    fn is_drained(&self) -> Result<bool, AgentdError>;
    fn drain(&mut self) -> Result<(), AgentdError>;
    fn selection(
        &self,
        original: &PublishedNeuronGenerationUpdateV1,
        coordinator: &LearningIterationCoordinatorV1,
        previous_manifest: &CellBackendManifestV2,
    ) -> Result<LearningIterationObservationV1, AgentdError>;
}

impl<W: AnchorWitnessStore + Send> OriginalVersion for CellGenerationJournalV2<W> {
    fn require_current(&self) -> Result<(), AgentdError> {
        let observed = self.observe_generation().map_err(invalid)?;
        if observed.snapshot().revision != 0
            || observed.pending_request_digest().is_some()
            || observed.pending_output().is_some()
            || !observed.snapshot().prefix.is_empty()
            || observed.snapshot().stopped
        {
            return Err(invalid("published task already contains GenerationV2 work"));
        }
        self.require_current().map_err(invalid)
    }
    fn is_drained(&self) -> Result<bool, AgentdError> {
        self.is_drained().map_err(invalid)
    }
    fn drain(&mut self) -> Result<(), AgentdError> {
        self.drain().map_err(invalid)
    }
    fn selection(
        &self,
        original: &PublishedNeuronGenerationUpdateV1,
        coordinator: &LearningIterationCoordinatorV1,
        previous_manifest: &CellBackendManifestV2,
    ) -> Result<LearningIterationObservationV1, AgentdError> {
        let view = GenerationLearningReadbackV1 {
            journal: self,
            publication: original,
        };
        if coordinator.next_task_bundle() == Some(&coordinator.snapshot().request.selected_bundle) {
            view.read_selection(coordinator)
        } else {
            view.read_updated_selection(coordinator, previous_manifest)
        }
    }
}

struct PublishedTask {
    original: Mutex<Box<dyn OriginalVersion>>,
    current: Arc<LiveGenerationCurrent>,
    publication: Publication,
    manifest: CellBackendManifestV2,
    definition: CellDefinitionV1,
    source: CircuitTaskSourceInputV1,
}

/// A sealed shared view of one original published task; cloning retains the
/// same journal/authority owners, never another writer or synthesized scope.
#[derive(Clone)]
pub struct PublishedCircuitFeatureTaskV1(Arc<PublishedTask>);

/// Exact source/Cell completion observed under the original live CURRENT and
/// followed by its durable drain. This historical fact cannot authorize use or
/// prove current source availability; new reads still require the live owners.
#[derive(Clone)]
pub struct PublishedCircuitFeatureCompletionV1 {
    binding: CellGenerationOwnerBindingV1,
    manifest: CellBackendManifestV2,
    source: CircuitTaskSourcePublicationV1,
    receipt: codex_hepta_neuron::CellDecisionReceiptV1,
}

impl PublishedCircuitFeatureCompletionV1 {
    pub fn source_publication(&self) -> &CircuitTaskSourcePublicationV1 {
        &self.source
    }
}

impl PublishedCircuitFeatureTaskV1 {
    pub(crate) fn from_initial<W: AnchorWitnessStore + Send + 'static>(
        journal: CellGenerationJournalV2<W>,
        original: PublishedNeuronGenerationInitialV1,
        current: Arc<LiveGenerationCurrent>,
        definition: CellDefinitionV1,
        source: CircuitTaskSourceInputV1,
    ) -> Result<Self, AgentdError> {
        Self::from_parts(
            journal,
            Publication::Initial(original),
            current,
            definition,
            source,
        )
    }

    pub(crate) fn from_update<W: AnchorWitnessStore + Send + 'static>(
        journal: CellGenerationJournalV2<W>,
        original: PublishedNeuronGenerationUpdateV1,
        current: Arc<LiveGenerationCurrent>,
        definition: CellDefinitionV1,
        source: CircuitTaskSourceInputV1,
        previous: PublishedCircuitFeatureCompletionV1,
    ) -> Result<Self, AgentdError> {
        let old = previous.source.input();
        if original.previous() != &previous.binding
            || previous.manifest.digest().map_err(invalid)? != previous.binding.manifest_digest()
            || previous.manifest.bundle_digest != previous.source.bundle_digest().into_array()
            || previous.receipt.checkpoint_after != previous.source.checkpoint_digest()
            || old.scope.run_id == source.scope.run_id
            || old.observation == source.observation
        {
            return Err(invalid("original completed Feature predecessor differs"));
        }
        Self::from_parts(
            journal,
            Publication::Update { original, previous },
            current,
            definition,
            source,
        )
    }

    fn from_parts<W: AnchorWitnessStore + Send + 'static>(
        journal: CellGenerationJournalV2<W>,
        publication: Publication,
        current: Arc<LiveGenerationCurrent>,
        definition: CellDefinitionV1,
        source: CircuitTaskSourceInputV1,
    ) -> Result<Self, AgentdError> {
        let target = publication.target();
        let scope = target.scope();
        let manifest = journal.manifest().clone();
        if journal.owner_binding() != Some(target)
            || target.task_digest()
                != circuit_feature_task_digest_v1(&definition, &source)?.into_array()
            || target.source_frontier() != source.source_frontier.into_array()
            || scope.agent_id != source.scope.agent_id.as_str()
            || scope.cell_id != source.scope.cell_id.as_str()
            || scope.run_id != source.scope.run_id.as_str()
            || scope.principal_digest != source.scope.principal_digest.into_array()
            || manifest.profile != crate::CellQ24GenerationWorkerV1::PROFILE
            || manifest.bundle_digest != definition.bundle_digest.into_array()
            || manifest.state_schema != definition.state_schema_digest.into_array()
            || manifest.encoder != Some(definition.runtime.encoder_digest.into_array())
            || manifest.head != Some(definition.runtime.head_digest.into_array())
        {
            return Err(invalid(
                "ordinary Feature profile differs from original publication",
            ));
        }
        current.check_current(target).map_err(invalid)?;
        let result = Self(Arc::new(PublishedTask {
            original: Mutex::new(Box::new(journal)),
            current,
            publication,
            manifest,
            definition,
            source,
        }));
        result.require_current()?;
        Ok(result)
    }

    pub fn definition(&self) -> &CellDefinitionV1 {
        &self.0.definition
    }
    pub fn source(&self) -> &CircuitTaskSourceInputV1 {
        &self.0.source
    }

    pub fn require_bundle(&self, bundle: &CellCompatibilityBundleV1) -> Result<(), AgentdError> {
        self.require_current()?;
        crate::cell_composed_q24::validate_manifest(bundle, &self.0.manifest).map_err(invalid)?;
        if bundle.digest().map_err(invalid)? != self.definition().bundle_digest {
            return Err(invalid("ordinary Feature bundle differs"));
        }
        self.require_current()
    }

    pub fn open_cell<W: AnchorWitnessStore>(
        &self,
        file: File,
        witness: W,
        max_records: usize,
    ) -> Result<PublishedCircuitCellOwnerV1<W>, AgentdError> {
        self.require_current()?;
        if !(3..=16).contains(&max_records) {
            return Err(invalid("single Feature task record bound"));
        }
        let target = self.0.publication.target();
        let current: Arc<dyn CellGenerationCurrentV1> = self.0.current.clone();
        let journal = CellOwnerJournalV1::open_guarded(
            file,
            witness,
            vec![CellJournalPartitionV1 {
                scope: self.source().scope.clone(),
                definition: self.definition().clone(),
                source_frontier: self.source().source_frontier,
                writer_epoch: target.writer_epoch(),
            }],
            max_records,
            target.clone(),
            current,
        )
        .map_err(invalid)?;
        self.require_current()?;
        Ok(PublishedCircuitCellOwnerV1::new(journal, self.clone()))
    }

    fn require_current(&self) -> Result<(), AgentdError> {
        self.0
            .current
            .check_current(self.0.publication.target())
            .map_err(invalid)?;
        self.0.original.lock().map_err(invalid)?.require_current()?;
        self.0
            .current
            .check_current(self.0.publication.target())
            .map_err(invalid)
    }

    fn require_active(&self) -> Result<(), AgentdError> {
        self.require_current()?;
        if self.0.original.lock().map_err(invalid)?.is_drained()? {
            return Err(invalid("ordinary published Feature task is drained"));
        }
        self.require_current()
    }
}

fn source_input(source: &CircuitTaskSourceInputV1, operation_id: StableId) -> CellStepInputV1 {
    CellStepInputV1 {
        operation_id,
        scope: source.scope.clone(),
        source_frontier: source.source_frontier,
        objective_digest: source.objective_digest,
        ndu_snapshot_digest: source.ndu_snapshot_digest,
        monotonic_micros: source.monotonic_micros,
        deadline_micros: source.deadline_micros,
        observation: source.observation.clone(),
        candidates: source.candidates.clone(),
    }
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}

#[cfg(test)]
pub(crate) use learning_read::readiness_fixture as original_readiness_fixture;
