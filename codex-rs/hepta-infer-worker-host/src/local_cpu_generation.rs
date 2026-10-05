//! Construct one actual durable generation behind its independently selected
//! artifact gate. Parameters are owned by installer/compiler composition; model
//! text and request bytes do not construct the admission capability.
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdNeuronArtifactAdmissionV1;
use codex_hepta_agentd::AgentdNeuronHandleV2;
use codex_hepta_agentd::AgentdNeuronOwnerV2;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_neuron::FileNeuronWitnessStoreV2;
use codex_hepta_neuron::NeuronRuntimeV2;

use crate::CpuNeuronControlConfigV1;
use crate::CpuNeuronInferenceControlV1;
use crate::SharedCpuNeuronInferenceControlV3;

#[path = "local_cpu_generation_composition_v2.rs"]
mod composition;
pub use composition::CpuNeuronGenerationCompositionReaderV2;
pub use composition::CpuNeuronGenerationCompositionV2;

pub enum CpuNeuronGenerationOpenModeV1 {
    Create,
    Recover,
}

pub use codex_hepta_neuron::NeuronGenerationMaterialV2 as CpuNeuronGenerationPlanV1;

/// Bootstrap a new Agent from admitted generation-one artifacts and empty
/// physical stores. No selected predecessor or checkpoint is manufactured.
pub fn bootstrap_installed_cpu_neuron_v1(
    plan: CpuNeuronGenerationPlanV1,
    control: Arc<Mutex<DurableInferenceControl>>,
    clock: Arc<dyn AuthorityClock>,
    worker: CpuNeuronControlConfigV1,
    mut admission: AgentdNeuronArtifactAdmissionV1,
) -> Result<AgentdNeuronHandleV2, AgentdError> {
    admission
        .validate_initial_generation(&plan.runtime)
        .map_err(|error| {
            AgentdError::Invalid(format!("initial Neuron artifact admission: {error:?}"))
        })?;
    open_installed_cpu_neuron_generation_v1(
        plan,
        CpuNeuronGenerationOpenModeV1::Create,
        control,
        clock,
        worker,
        admission,
    )
}

pub fn open_installed_cpu_neuron_generation_v1(
    plan: CpuNeuronGenerationPlanV1,
    mode: CpuNeuronGenerationOpenModeV1,
    control: Arc<Mutex<DurableInferenceControl>>,
    clock: Arc<dyn AuthorityClock>,
    worker: CpuNeuronControlConfigV1,
    admission: AgentdNeuronArtifactAdmissionV1,
) -> Result<AgentdNeuronHandleV2, AgentdError> {
    open_guarded_cpu_neuron_generation(plan, mode, control, clock, worker, admission)
}

pub(crate) fn open_guarded_cpu_neuron_generation<G>(
    plan: CpuNeuronGenerationPlanV1,
    mode: CpuNeuronGenerationOpenModeV1,
    control: Arc<Mutex<DurableInferenceControl>>,
    clock: Arc<dyn AuthorityClock>,
    worker: CpuNeuronControlConfigV1,
    admission: G,
) -> Result<AgentdNeuronHandleV2, AgentdError>
where
    G: codex_hepta_neuron::NeuronAdmissionGuard + Send + 'static,
{
    for path in [
        &plan.model_manifest,
        &plan.generation_store,
        &plan.runtime_index,
        &plan.witness,
    ] {
        if !path.is_absolute() || path.file_name().is_none() {
            return Err(AgentdError::Invalid(
                "installed Neuron paths must be absolute files".into(),
            ));
        }
    }
    if plan.generation_store == plan.runtime_index
        || plan.generation_store == plan.witness
        || plan.runtime_index == plan.witness
        || worker.generation != plan.runtime.generation.get()
    {
        return Err(AgentdError::Invalid(
            "installed Neuron owner identity".into(),
        ));
    }
    let physical = CpuNeuronInferenceControlV1::open_shared(
        control,
        clock,
        &plan.model_manifest,
        plan.model_manifest_digest,
        worker,
    )
    .map_err(|error| AgentdError::Invalid(format!("installed CPU model: {error}")))?;
    physical.validate_runtime(&plan.runtime).map_err(|error| {
        AgentdError::Invalid(format!("installed Neuron runtime tuple changed: {error}"))
    })?;
    finish_generation(plan, mode, physical, admission)
}

#[cfg(target_os = "linux")]
pub(crate) fn open_guarded_cpu_neuron_generation_v2<G>(
    plan: CpuNeuronGenerationPlanV1,
    mode: CpuNeuronGenerationOpenModeV1,
    control: Arc<tokio::sync::Mutex<DurableInferenceControl>>,
    clock: Arc<dyn AuthorityClock>,
    worker: crate::CpuNeuronControlConfigV2,
    admission: G,
) -> Result<AgentdNeuronHandleV2, AgentdError>
where
    G: codex_hepta_neuron::NeuronAdmissionGuard + Send + 'static,
{
    Ok(
        compose_guarded_cpu_neuron_generation_v2(plan, mode, control, clock, worker, admission)?
            .into_handle(),
    )
}

#[cfg(target_os = "linux")]
pub(crate) fn compose_guarded_cpu_neuron_generation_v2<G>(
    plan: CpuNeuronGenerationPlanV1,
    mode: CpuNeuronGenerationOpenModeV1,
    control: Arc<tokio::sync::Mutex<DurableInferenceControl>>,
    clock: Arc<dyn AuthorityClock>,
    worker: crate::CpuNeuronControlConfigV2,
    admission: G,
) -> Result<CpuNeuronGenerationCompositionV2, AgentdError>
where
    G: codex_hepta_neuron::NeuronAdmissionGuard + Send + 'static,
{
    for path in [
        &plan.model_manifest,
        &plan.generation_store,
        &plan.runtime_index,
        &plan.witness,
    ] {
        if !path.is_absolute() || path.file_name().is_none() {
            return Err(AgentdError::Invalid(
                "installed Neuron paths must be absolute files".into(),
            ));
        }
    }
    if plan.generation_store == plan.runtime_index
        || plan.generation_store == plan.witness
        || plan.runtime_index == plan.witness
        || worker.model_generation != plan.runtime.generation
    {
        return Err(AgentdError::Invalid(
            "installed Neuron V2 model identity".into(),
        ));
    }
    let physical = CpuNeuronInferenceControlV1::open_shared_v2(
        control,
        clock,
        &plan.model_manifest,
        plan.model_manifest_digest,
        worker,
    )
    .map_err(|error| AgentdError::Invalid(format!("installed V2 CPU model: {error}")))?;
    physical.validate_runtime(&plan.runtime).map_err(|error| {
        AgentdError::Invalid(format!("installed Neuron runtime tuple changed: {error}"))
    })?;
    let physical = SharedCpuNeuronInferenceControlV3::new(physical);
    let handle = finish_generation(plan.clone(), mode, physical.clone(), admission)?;
    Ok(CpuNeuronGenerationCompositionV2::new(
        plan, handle, physical,
    ))
}

/// Open a new or recovered Goal scope around the same loaded CPU worker. The
/// scope's own admission guard and durable headers still bind its actual Goal.
pub fn open_shared_cpu_neuron_goal_scope_v3<G>(
    plan: CpuNeuronGenerationPlanV1,
    mode: CpuNeuronGenerationOpenModeV1,
    physical: SharedCpuNeuronInferenceControlV3,
    admission: G,
) -> Result<AgentdNeuronHandleV2, AgentdError>
where
    G: codex_hepta_neuron::NeuronAdmissionGuard + Send + 'static,
{
    for path in [
        &plan.model_manifest,
        &plan.generation_store,
        &plan.runtime_index,
        &plan.witness,
    ] {
        if !path.is_absolute() || path.file_name().is_none() {
            return Err(AgentdError::Invalid(
                "installed Neuron paths must be absolute files".into(),
            ));
        }
    }
    if plan.generation_store == plan.runtime_index
        || plan.generation_store == plan.witness
        || plan.runtime_index == plan.witness
    {
        return Err(AgentdError::Invalid(
            "installed Neuron Goal scope storage identity".into(),
        ));
    }
    physical.validate_runtime(&plan.runtime).map_err(|error| {
        AgentdError::Invalid(format!(
            "installed shared CPU runtime tuple changed: {error}"
        ))
    })?;
    finish_generation(plan, mode, physical, admission)
}

fn finish_generation<G, P>(
    plan: CpuNeuronGenerationPlanV1,
    mode: CpuNeuronGenerationOpenModeV1,
    physical: P,
    admission: G,
) -> Result<AgentdNeuronHandleV2, AgentdError>
where
    G: codex_hepta_neuron::NeuronAdmissionGuard + Send + 'static,
    P: codex_hepta_neuron::DurableNeuronInferenceControlPort + Send + 'static,
{
    let witness = match mode {
        CpuNeuronGenerationOpenModeV1::Create => {
            FileNeuronWitnessStoreV2::create(&plan.witness, plan.witness_context)
        }
        CpuNeuronGenerationOpenModeV1::Recover => {
            FileNeuronWitnessStoreV2::open_existing(&plan.witness, plan.witness_context)
        }
    }
    .map_err(|error| AgentdError::Protocol(format!("installed Neuron witness: {error}")))?;
    let runtime = match mode {
        CpuNeuronGenerationOpenModeV1::Create => NeuronRuntimeV2::bootstrap(
            &plan.generation_store,
            &plan.runtime_index,
            plan.native,
            plan.scope,
            plan.runtime,
            plan.body,
            plan.store_context,
            plan.index_context,
            witness,
        ),
        CpuNeuronGenerationOpenModeV1::Recover => NeuronRuntimeV2::recover(
            &plan.generation_store,
            &plan.runtime_index,
            plan.native,
            plan.scope,
            plan.runtime,
            plan.body,
            plan.store_context,
            plan.index_context,
            witness,
        ),
    }
    .map_err(|error| {
        AgentdError::Protocol(format!("installed durable Neuron generation: {error}"))
    })?;
    AgentdNeuronOwnerV2::new(runtime, physical)
        .into_shared(admission)
        .map_err(|error| AgentdError::Protocol(format!("installed Neuron admission gate: {error}")))
}
