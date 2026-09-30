//! Construct one actual durable generation behind its independently selected
//! artifact gate. Parameters are owned by installer/compiler composition; model
//! text and request bytes do not construct the admission capability.
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdNeuronArtifactAdmissionV1;
use codex_hepta_agentd::AgentdNeuronHandleV2;
use codex_hepta_agentd::AgentdNeuronOwnerV2;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_neuron::FileNeuronWitnessStoreV2;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronBodyBundleIdentityV1;
use codex_hepta_neuron::NeuronGenerationStoreContextV2;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronRuntimeIndexContextV2;
use codex_hepta_neuron::NeuronRuntimeV2;
use codex_hepta_neuron::NeuronWitnessContextV2;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_types::Digest32;

use crate::CpuNeuronControlConfigV1;
use crate::CpuNeuronInferenceControlV1;

pub enum CpuNeuronGenerationOpenModeV1 {
    Create,
    Recover,
}

pub struct CpuNeuronGenerationPlanV1 {
    pub model_manifest: PathBuf,
    pub model_manifest_digest: Digest32,
    pub generation_store: PathBuf,
    pub runtime_index: PathBuf,
    pub witness: PathBuf,
    pub native: SparseConfig,
    pub scope: JournalScope,
    pub runtime: NeuronRuntimeConfigV1,
    pub body: NeuronBodyBundleIdentityV1,
    pub store_context: NeuronGenerationStoreContextV2,
    pub index_context: NeuronRuntimeIndexContextV2,
    pub witness_context: NeuronWitnessContextV2,
}

pub fn open_installed_cpu_neuron_generation_v1(
    plan: CpuNeuronGenerationPlanV1,
    mode: CpuNeuronGenerationOpenModeV1,
    control: Arc<Mutex<DurableInferenceControl>>,
    clock: Arc<dyn AuthorityClock>,
    worker: CpuNeuronControlConfigV1,
    admission: AgentdNeuronArtifactAdmissionV1,
) -> Result<AgentdNeuronHandleV2, AgentdError> {
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
    let manifest = physical.manifest();
    for (actual, expected) in [
        (&manifest.model_digest, plan.runtime.model_manifest_digest),
        (&manifest.weights_digest, plan.runtime.weights_digest),
        (&manifest.tokenizer_digest, plan.runtime.tokenizer_digest),
        (
            &manifest.preprocessor_digest,
            plan.runtime.preprocessor_digest,
        ),
        (
            &manifest.quantization_digest,
            plan.runtime.quantization_digest,
        ),
        (&manifest.runtime_digest, plan.runtime.runtime_digest),
        (&manifest.device_digest, plan.runtime.device_digest),
    ] {
        if actual != &expected.to_string() {
            return Err(AgentdError::Invalid(
                "installed Neuron runtime tuple changed".into(),
            ));
        }
    }
    if manifest.model_id != plan.runtime.model_id.as_str() {
        return Err(AgentdError::Invalid(
            "installed Neuron model ID changed".into(),
        ));
    }
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
