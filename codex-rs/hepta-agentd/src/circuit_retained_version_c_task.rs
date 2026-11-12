//! Concrete original C configuration, consumed only after actual publication.
//! The existing ordinary factory owns Source/Cell/control; no RunStart is made.
use std::sync::Arc;

use codex_hepta_automation::BoundedCircuitDefinitionV2;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;

use super::Error;
use super::OriginalCircuitRetainedVersionPublicationV1;
use super::OriginalCircuitRetainedVersionReadbackV1;
use super::context::OriginalVersionCut;
use super::super::context::PublicationAccess;
use crate::AgentdConfig;
use crate::AgentdIdentity;
use crate::CircuitCellRouteV1;
use crate::CircuitCellTimeV1;
use crate::CircuitQ24TaskFilesV1;
use crate::CircuitQ24TaskOpenModeV1;
use crate::CircuitQ24TaskProfileV1;
use crate::CircuitTaskSourceReadbackV1;
use crate::LoadedCellQ24ModelV1;
use crate::PublishedCircuitCellOwnerV1;
use crate::PublishedCircuitFeatureCompletionV1;
use crate::PublishedCircuitFeatureTaskV1;

/// These are the existing ordinary factory's actual host-owned parameters,
/// without the future published_task. The clock is the original ordinary
/// Circuit/Cell clock, not an authority callback or a way to manufacture T/S/C.
pub struct OriginalCircuitRetainedTaskInputsV1 {
    pub config: AgentdConfig,
    pub files: CircuitQ24TaskFilesV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
    pub fence: TaskFlowFence,
    pub circuit: BoundedCircuitDefinitionV2,
    pub routes: Vec<CircuitCellRouteV1>,
    pub model: Arc<LoadedCellQ24ModelV1>,
    pub worker_generation: u64,
    pub maximum_cell_records: usize,
    pub queue_capacity: usize,
    pub clock: Arc<dyn Fn() -> CircuitCellTimeV1 + Send + Sync>,
    pub original_a: CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>,
    pub original_a_identity: AgentdIdentity,
}

pub(super) struct RetainedVersionInstalledTaskV1 {
    pub(super) cell: PublishedCircuitCellOwnerV1<FileAnchorWitnessStore>,
    pub(super) source: Arc<CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>>,
    pub(super) identity: AgentdIdentity,
    pub(super) intent: Digest32,
}
impl OriginalCircuitRetainedTaskInputsV1 {
    pub(super) fn require_completed_a(
        &self,
        completed: &PublishedCircuitFeatureCompletionV1,
    ) -> Result<(), Error> {
        let expected = completed.source_publication();
        let run = &expected.input().scope.run_id;
        let before = self.original_a.read_run_publication(&self.original_a_identity, run)?;
        let c = self.config.identity();
        let a = &self.original_a_identity;
        if &before != expected || c.agent_id != a.agent_id
            || c.spawn_generation == 0
            || c.fleet_root == a.fleet_root && c.spawn_generation <= a.spawn_generation
            || c.fleet_root != a.fleet_root
                && (c.run_root == a.run_root || c.home_root == a.home_root)
            || self.original_a.read_run_publication(a, run)? != before
        {
            return Err(Error::Binding("actual completed A and a separate original C session"));
        }
        Ok(())
    }

    pub(super) fn install_original(
        self,
        task: PublishedCircuitFeatureTaskV1,
        cut: &OriginalVersionCut,
        intent: Digest32,
    ) -> Result<(RetainedVersionInstalledTaskV1, AgentdConfig), Error> {
        cut.require_fresh(super::now()?, PublicationAccess::NewWork)?;
        task.require_bundle(&cut.training.training.request.selected_bundle)?;
        let crate::circuit_feature_current::Publication::Update { previous, .. } = &task.0.publication else {
            return Err(Error::Binding("actual retained C predecessor"));
        };
        self.require_completed_a(previous)?;
        let original_a_publication = previous.source_publication().clone();
        let original_a = self.original_a;
        let original_a_identity = self.original_a_identity;
        let identity = self.config.identity().clone();
        // This is the existing product factory, not a prepared-data response.
        // It builds actual original Source and Cell owners and the ordinary
        // driver/bootstrap. Authenticated RunStart still has to arrive later.
        let actual = AgentdConfig::with_q24_circuit_task_profile(
            self.config,
            CircuitQ24TaskProfileV1 {
                files: self.files,
                source_mode: CircuitQ24TaskOpenModeV1::Create,
                published_task: task,
                fence: self.fence,
                circuit: self.circuit,
                routes: self.routes,
                bundle: cut.training.training.request.selected_bundle.clone(),
                model: self.model,
                worker_generation: self.worker_generation,
                maximum_cell_records: self.maximum_cell_records,
                queue_capacity: self.queue_capacity,
                clock: self.clock,
            },
        )?;
        let installed = RetainedVersionInstalledTaskV1 {
            cell: actual.cell, source: actual.source, identity, intent,
        };
        installed.observe(cut)?;
        if original_a.read_run_publication(
            &original_a_identity, &original_a_publication.input().scope.run_id,
        )? != original_a_publication {
            return Err(Error::Binding("original completed A changed during C factory"));
        }
        cut.require_fresh(super::now()?, PublicationAccess::NewWork)?;
        Ok((installed, actual.config))
    }
}
impl RetainedVersionInstalledTaskV1 {
    pub(super) fn observe(&self, cut: &OriginalVersionCut) -> Result<OriginalCircuitRetainedVersionReadbackV1, Error> {
        let coordinator = cut.training.authenticate(super::now()?, PublicationAccess::Readback)?;
        let task = &self.cell.task;
        task.require_current()?;
        CircuitTaskSourceReadbackV1::require_original_input(
            self.source.as_ref(), &self.identity, task.source(),
        )?;
        let selected = PublishedCircuitCellOwnerV1::read_learning_selection(&self.cell, &coordinator)?;
        let crate::circuit_feature_current::Publication::Update { original, .. } = &task.0.publication else {
            return Err(Error::Binding("actual original successor publication"));
        };
        let operation = crate::learning_retained_task_operation_id_v1(&coordinator)?;
        if original.operation_id() != operation.as_str()
            || original.intent_digest() != self.intent
            || original.completion() != crate::NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel
        {
            return Err(Error::Binding("same strict retained original Control operation"));
        }
        let LearningIterationObservationV1::Selection { candidate_bundle, selection_digest } = selected else {
            return Err(Error::Binding("original version owner Selection observation"));
        };
        let baseline = cut.training.training.request.selected_bundle.digest()
            .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
        if candidate_bundle != baseline || task.source().scope.run_id == cut.training.training.request.source_run_id {
            return Err(Error::Binding("actual retained bundle and distinct C run"));
        }
        let publication = original.publication_digest()?;
        let task_digest = crate::circuit_feature_task_digest_v1(task.definition(), task.source())?;
        CircuitTaskSourceReadbackV1::require_original_input(
            self.source.as_ref(), &self.identity, task.source(),
        )?;
        task.require_bundle(&cut.training.training.request.selected_bundle)?;
        let after = PublishedCircuitCellOwnerV1::read_learning_selection(&self.cell, &coordinator)?;
        if after != (LearningIterationObservationV1::Selection {
            candidate_bundle, selection_digest,
        }) {
            return Err(Error::Binding("original version selection changed"));
        }
        Ok(OriginalCircuitRetainedVersionReadbackV1 {
            intent: self.intent,
            publication: Some(OriginalCircuitRetainedVersionPublicationV1 {
                intent: self.intent, publication, task: task_digest,
                selection: selection_digest, bundle: baseline,
                run: task.source().scope.run_id.clone(),
            }),
        })
    }
}
