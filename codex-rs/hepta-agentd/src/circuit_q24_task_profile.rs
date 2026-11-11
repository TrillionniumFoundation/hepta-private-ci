//! Ordinary signed-task assembly for one originally published Q24 task/run.
//! Every file, witness, model, route and CURRENT capability comes from the
//! original host. This module creates no issuer, grant, selection or input.
//! A different session/task uses a separately published original task binding.

use std::fs::File;
use std::sync::Arc;

use codex_hepta_automation::BoundedCircuitDefinitionV2;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::DurableInferenceControl;

use crate::AgentdCircuitCellOwnerV1;
use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::CellQ24FeatureWorkerV1;
use crate::CircuitCellBindingV1;
use crate::CircuitCellRegistryV1;
use crate::CircuitCellRouteV1;
use crate::CircuitCellTimeV1;
use crate::CircuitTaskRuntimeBootstrapV1;
use crate::CircuitTaskSourceReadbackV1;
use crate::DurableCircuitTaskSourceV1;
use crate::LoadedCellQ24ModelV1;
use crate::PublishedCircuitCellOwnerV1;
use crate::PublishedCircuitFeatureTaskV1;
use crate::circuit_task_channel_v1;

#[path = "circuit_q24_successor_execution.rs"]
pub(crate) mod successor;

#[cfg(target_os = "linux")]
#[path = "circuit_q24_task_ledger_install.rs"]
mod learning;
#[cfg(target_os = "linux")]
pub use learning::AgentdQ24LearningTaskRuntimeV1;

/// Source lifecycle is explicit. Recovery never replaces an acknowledged
/// history with a fresh source or recreates an unresolved request.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CircuitQ24TaskOpenModeV1 {
    Create,
    Recover,
}

pub struct CircuitQ24TaskFilesV1<SourceWitness, CellWitness> {
    pub source_journal: File,
    pub source_witness: SourceWitness,
    pub cell_journal: File,
    pub cell_witness: CellWitness,
    pub inference_control: DurableInferenceControl,
}

/// One frozen root Cell and its exact host-supplied routes. The mandatory
/// sealed publication supplies the original source and Cell definition; a
/// caller cannot insert a different run or substitute a model identity here.
pub struct CircuitQ24TaskProfileV1<SourceWitness, CellWitness> {
    pub files: CircuitQ24TaskFilesV1<SourceWitness, CellWitness>,
    pub source_mode: CircuitQ24TaskOpenModeV1,
    pub published_task: PublishedCircuitFeatureTaskV1,
    pub fence: TaskFlowFence,
    pub circuit: BoundedCircuitDefinitionV2,
    pub routes: Vec<CircuitCellRouteV1>,
    pub bundle: CellCompatibilityBundleV1,
    pub model: Arc<LoadedCellQ24ModelV1>,
    pub worker_generation: u64,
    pub maximum_cell_records: usize,
    pub queue_capacity: usize,
    /// Both channels sample this same host clock. The Cell epoch must survive
    /// reopen; the ordinary channel independently rechecks authenticated wall time.
    pub clock: Arc<dyn Fn() -> CircuitCellTimeV1 + Send + Sync>,
}

pub struct CircuitQ24TaskRuntimeV1<SW: AnchorWitnessStore, CW: AnchorWitnessStore> {
    pub(crate) bootstrap: CircuitTaskRuntimeBootstrapV1,
    invocation: Arc<DurableCircuitTaskSourceV1<SW>>,
    source: Arc<CircuitTaskSourceReadbackV1<SW>>,
    cell: PublishedCircuitCellOwnerV1<CW>,
}

pub struct AgentdQ24CircuitTaskRuntimeV1<SW: AnchorWitnessStore, CW: AnchorWitnessStore> {
    pub config: AgentdConfig,
    pub source: Arc<CircuitTaskSourceReadbackV1<SW>>,
    pub cell: PublishedCircuitCellOwnerV1<CW>,
}

impl<SW: AnchorWitnessStore + Send + 'static, CW: AnchorWitnessStore + Send + 'static>
    CircuitQ24TaskRuntimeV1<SW, CW>
{
    /// Retain the original source owner for learning/readback. Publication still
    /// requires the original private CircuitTaskReceipt from the ordinary driver.
    pub fn source(&self) -> Arc<CircuitTaskSourceReadbackV1<SW>> {
        Arc::clone(&self.source)
    }

    pub fn cell(&self) -> PublishedCircuitCellOwnerV1<CW> {
        self.cell.clone()
    }

    pub fn install(self, config: AgentdConfig) -> Result<AgentdConfig, AgentdError> {
        config.with_circuit_task_bootstrap(self.bootstrap, self.invocation)
    }
}

/// Assembles the actual ordinary Circuit driver. The resulting bootstrap can
/// only receive an authenticated retained RunStart through its existing ingress;
/// no public method submits raw tasks or manufactures completed task receipts.
pub fn circuit_q24_task_channel_v1<SW, CW>(
    identity: &AgentdIdentity,
    profile: CircuitQ24TaskProfileV1<SW, CW>,
) -> Result<CircuitQ24TaskRuntimeV1<SW, CW>, AgentdError>
where
    SW: AnchorWitnessStore + Send + 'static,
    CW: AnchorWitnessStore + Send + 'static,
{
    if profile.fence.owner_agent_id != identity.agent_id
        || identity.spawn_generation == 0
        || identity.spawn_generation.checked_add(1) != Some(profile.fence.generation)
        || profile.worker_generation == 0
        || !(1..=64).contains(&profile.queue_capacity)
        || !(3..=16).contains(&profile.maximum_cell_records)
    {
        return Err(AgentdError::Invalid(
            "Q24 task profile has an invalid original owner or capacity".into(),
        ));
    }
    let published: &PublishedCircuitFeatureTaskV1 = &profile.published_task;
    published.require_bundle(&profile.bundle)?;
    let definition = published.definition().clone();
    let source_input = published.source().clone();
    let program = profile
        .circuit
        .programs
        .iter()
        .find(|program| program.program_id == profile.circuit.entry_program)
        .ok_or_else(|| {
            AgentdError::Invalid("Q24 task circuit has no original root program".into())
        })?;
    let binding = CircuitCellBindingV1 {
        program_id: program.program_id.clone(),
        node_id: program.entry_node.clone(),
        cell: definition.clone(),
        routes: profile.routes,
    };
    let registry = CircuitCellRegistryV1::new(profile.circuit, vec![binding])
        .map_err(|error| AgentdError::Invalid(error.to_string()))?;
    let worker = CellQ24FeatureWorkerV1::new(profile.model, &profile.bundle, &definition)
        .map_err(|error| AgentdError::Invalid(error.to_string()))?;
    let encoder = worker.input_encoder();
    let source = match profile.source_mode {
        CircuitQ24TaskOpenModeV1::Create => DurableCircuitTaskSourceV1::create(
            profile.files.source_journal,
            profile.files.source_witness,
            identity,
            &profile.fence,
            &registry,
            vec![source_input],
        ),
        CircuitQ24TaskOpenModeV1::Recover => DurableCircuitTaskSourceV1::recover(
            profile.files.source_journal,
            profile.files.source_witness,
            identity,
            &profile.fence,
            &registry,
            vec![source_input],
        ),
    }
    .map_err(|error| AgentdError::Invalid(error.to_string()))?;
    let cell: PublishedCircuitCellOwnerV1<CW> = published.open_cell(
        profile.files.cell_journal,
        profile.files.cell_witness,
        profile.maximum_cell_records,
    )?;
    let inference_clock = Arc::clone(&profile.clock);
    let control = published
        .control(
            profile.files.inference_control,
            profile.worker_generation,
            worker,
            Arc::new(move || inference_clock().cell_micros),
        )
        .map_err(|error| AgentdError::GenerationFenced(error.to_string()))?;
    let cells = AgentdCircuitCellOwnerV1::new(registry, cell.writer(), control, encoder);
    let (_, bootstrap) = circuit_task_channel_v1(
        identity,
        profile.fence,
        cells,
        source.clone(),
        move || (profile.clock)(),
        profile.queue_capacity,
    )?;
    let readback = Arc::new(source.readback());
    Ok(CircuitQ24TaskRuntimeV1 {
        bootstrap,
        invocation: Arc::new(source),
        source: readback,
        cell,
    })
}
