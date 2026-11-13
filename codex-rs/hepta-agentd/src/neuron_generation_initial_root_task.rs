//! Consume a Ready original into the existing ordinary task factory, retaining
//! exactly the task, Cell and Source that factory installed for final drain.

use std::sync::Arc;

use codex_hepta_automation::BoundedCircuitDefinitionV2;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellDefinitionV1;

use super::InitialPhase;
use super::OriginalInitialOperation;
use super::OriginalRootInitialGenerationCustodyV1;
use super::invalid;
use super::require_root;
use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::CircuitCellRouteV1;
use crate::CircuitCellTimeV1;
use crate::CircuitQ24TaskFilesV1;
use crate::CircuitQ24TaskOpenModeV1;
use crate::CircuitQ24TaskProfileV1;
use crate::CircuitTaskSourceInputV1;
use crate::CircuitTaskSourceReadbackV1;
use crate::LoadedCellQ24ModelV1;
use crate::PublishedCircuitCellOwnerV1;
use crate::PublishedCircuitFeatureCompletionV1;
use crate::PublishedCircuitFeatureTaskV1;
use crate::neuron_generation_current::NeuronGenerationInitialReadbackV1;

/// Original host inputs for the ordinary factory. There is deliberately no
/// caller-supplied PublishedTask: the retained Ready value supplies that task.
pub struct OriginalRootCircuitTaskInputsV1<SW, CW> {
    pub definition: CellDefinitionV1,
    pub source: CircuitTaskSourceInputV1,
    pub files: CircuitQ24TaskFilesV1<SW, CW>,
    pub source_mode: CircuitQ24TaskOpenModeV1,
    pub fence: TaskFlowFence,
    pub circuit: BoundedCircuitDefinitionV2,
    pub routes: Vec<CircuitCellRouteV1>,
    pub bundle: CellCompatibilityBundleV1,
    pub model: Arc<LoadedCellQ24ModelV1>,
    pub worker_generation: u64,
    pub maximum_cell_records: usize,
    pub queue_capacity: usize,
    pub clock: Arc<dyn Fn() -> CircuitCellTimeV1 + Send + Sync>,
}

/// The normal daemon configuration and its non-Clone Root retirement custody.
/// Returning this value is not evidence of RunStart, task execution or drain.
pub struct OriginalRootCircuitTaskRuntimeV1<SW: AnchorWitnessStore, CW: AnchorWitnessStore> {
    pub config: AgentdConfig,
    pub custody: OriginalRootCircuitTaskCustodyV1<SW, CW>,
}

/// Keeps the concrete Current and the same actual task/Cell/Source identities.
/// It exposes neither a journal writer nor an alternative task configuration.
pub struct OriginalRootCircuitTaskCustodyV1<SW: AnchorWitnessStore, CW: AnchorWitnessStore> {
    operation: OriginalInitialOperation,
    task: PublishedCircuitFeatureTaskV1,
    cell: PublishedCircuitCellOwnerV1<CW>,
    source: Arc<CircuitTaskSourceReadbackV1<SW>>,
    identity: AgentdIdentity,
}

impl<SW: AnchorWitnessStore, CW: AnchorWitnessStore> OriginalRootCircuitTaskCustodyV1<SW, CW> {
    pub fn read_original_operation(
        &self,
    ) -> Result<NeuronGenerationInitialReadbackV1, AgentdError> {
        self.operation.read_original()
    }

    /// Use only the original same-Arc retirement path. An error can occur after
    /// durable drain and is not NotApplied. No runtime or fresh owner is restored
    /// here; the returned opaque completion is historical evidence, not authority.
    pub fn drain_completed_task(&self) -> Result<PublishedCircuitFeatureCompletionV1, AgentdError> {
        require_root()?;
        self.task
            .drain_completed_task(&self.cell, self.source.as_ref(), &self.identity)
    }
}

/// Installation may already have created/recovered Source or opened Cell files.
/// Retain the original error and only this operation's protected readback. There
/// is no automatic Create retry, new path, new operation or recovered Ready here.
pub struct OriginalRootInitialInstallationErrorV1 {
    operation: OriginalInitialOperation,
    error: AgentdError,
}

impl OriginalRootInitialInstallationErrorV1 {
    pub fn original_error(&self) -> &AgentdError {
        &self.error
    }

    pub fn read_original_operation(
        &self,
    ) -> Result<NeuronGenerationInitialReadbackV1, AgentdError> {
        self.operation.read_original()
    }
}

impl std::fmt::Debug for OriginalRootInitialInstallationErrorV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("OriginalRootInitialInstallationErrorV1")
            .field("error", &self.error)
            .finish_non_exhaustive()
    }
}

impl std::fmt::Display for OriginalRootInitialInstallationErrorV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        std::fmt::Display::fmt(&self.error, f)
    }
}

impl std::error::Error for OriginalRootInitialInstallationErrorV1 {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        Some(&self.error)
    }
}

impl<W: AnchorWitnessStore + Send + 'static> OriginalRootInitialGenerationCustodyV1<W> {
    /// Consume the original Ready value and call the unchanged ordinary factory.
    /// This method does not run the daemon or synthesize an ingress request.
    pub fn into_q24_task<SW, CW>(
        self,
        config: AgentdConfig,
        inputs: OriginalRootCircuitTaskInputsV1<SW, CW>,
    ) -> Result<OriginalRootCircuitTaskRuntimeV1<SW, CW>, OriginalRootInitialInstallationErrorV1>
    where
        SW: AnchorWitnessStore + Send + 'static,
        CW: AnchorWitnessStore + Send + 'static,
    {
        let Self { operation, phase } = self;
        let installed = (|| {
            require_root()?;
            let InitialPhase::Ready(ready) = phase else {
                return Err(invalid("original initial publication is not ready"));
            };
            let task = (*ready).into_circuit_feature_task(inputs.definition, inputs.source)?;
            let retirement = task.clone();
            let identity = config.identity().clone();
            let profile = CircuitQ24TaskProfileV1 {
                files: inputs.files,
                source_mode: inputs.source_mode,
                published_task: task,
                fence: inputs.fence,
                circuit: inputs.circuit,
                routes: inputs.routes,
                bundle: inputs.bundle,
                model: inputs.model,
                worker_generation: inputs.worker_generation,
                maximum_cell_records: inputs.maximum_cell_records,
                queue_capacity: inputs.queue_capacity,
                clock: inputs.clock,
            };
            let runtime = config.with_q24_circuit_task_profile(profile)?;
            Ok((runtime, retirement, identity))
        })();
        match installed {
            Ok((runtime, task, identity)) => Ok(OriginalRootCircuitTaskRuntimeV1 {
                config: runtime.config,
                custody: OriginalRootCircuitTaskCustodyV1 {
                    operation,
                    task,
                    cell: runtime.cell,
                    source: runtime.source,
                    identity,
                },
            }),
            Err(error) => Err(OriginalRootInitialInstallationErrorV1 { operation, error }),
        }
    }
}

#[path = "neuron_generation_initial_material_source.rs"]
mod original_material_source;

#[path = "neuron_generation_initial_prefreeze_source.rs"]
mod original_prefreeze_source;

#[path = "neuron_generation_initial_root_task_channel.rs"]
mod original_channel;
