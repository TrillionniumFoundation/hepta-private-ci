//! Reload fresh independently signed current inputs without replacing the
//! durable generation owner, its journal, witness or physical model.
use super::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_neuron::NeuronAdmissionError;
use codex_hepta_neuron::NeuronAdmissionGuard;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronTickInputV1;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Pointer {
    schema: String,
    deployment: Source,
    selections: Source,
}

struct CurrentInputs {
    bytes: Vec<u8>,
    pointer: Pointer,
    inputs: Inputs,
    admission: codex_hepta_agentd::AgentdNeuronArtifactAdmissionV1,
    record_count: usize,
    head: Digest32,
}

impl CurrentInputs {
    fn read(path: &Path, clock: Arc<dyn AuthorityClock>) -> HostResult<Self> {
        let bytes = read_root_review_input(path, 32 * 1024)?;
        let pointer: Pointer = serde_json::from_slice(&bytes)?;
        if pointer.schema != "hepta.cpu-neuron.current-operational-pointer.v1" {
            return Err("current operational pointer schema".into());
        }
        let inputs = Inputs::read(
            &pointer.deployment.path,
            digest(&pointer.deployment.digest)?,
        )?;
        let admission = selection::admission(&inputs, &pointer.selections, clock)?;
        let current = inputs.current()?.current_registry_view(now_ms()?)?;
        if read_root_review_input(path, 32 * 1024)? != bytes {
            return Err("current operational pointer changed during admission".into());
        }
        Ok(Self {
            bytes,
            pointer,
            inputs,
            admission,
            record_count: current.receipt().records,
            head: current.receipt().head_digest,
        })
    }
}

struct CurrentAdmission {
    pointer: PathBuf,
    clock: Arc<dyn AuthorityClock>,
    active: CurrentInputs,
    storage_binding: Digest32,
    model_source: PathBuf,
    owner_root: PathBuf,
    last_now: u64,
}

impl CurrentAdmission {
    fn refresh(&mut self, runtime: &NeuronRuntimeConfigV1) -> HostResult<()> {
        let now = self.clock.now_unix_ms()?;
        if now < self.last_now {
            return Err("owned authority clock rolled back".into());
        }
        let bytes = read_root_review_input(&self.pointer, 32 * 1024)?;
        if bytes != self.active.bytes {
            let fresh = CurrentInputs::read(&self.pointer, self.clock.clone())?;
            if fresh.inputs.runtime != *runtime
                || fresh.inputs.storage_binding() != self.storage_binding
                || fresh.inputs.profile.model.path != self.model_source
                || fresh.inputs.profile.owner_root != self.owner_root
                || fresh.record_count < self.active.record_count
                || (fresh.record_count == self.active.record_count
                    && fresh.head != self.active.head)
                || fresh.inputs.profile.frozen_at_ms < self.active.inputs.profile.frozen_at_ms
            {
                return Err(
                    "renewed inputs changed original owner, generation or retained frontier".into(),
                );
            }
            self.active = fresh;
        }
        self.active.inputs.revalidate()?;
        self.active.pointer.selections.read(16 * 1024)?;
        let after = self.clock.now_unix_ms()?;
        if after < now || read_root_review_input(&self.pointer, 32 * 1024)? != self.active.bytes {
            return Err("clock or current operational pointer changed during admission".into());
        }
        self.last_now = after;
        Ok(())
    }
}

impl NeuronAdmissionGuard for CurrentAdmission {
    fn check(
        &mut self,
        runtime: &NeuronRuntimeConfigV1,
        input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        self.refresh(runtime)
            .map_err(|_| NeuronAdmissionError::Unavailable)?;
        self.active.admission.check(runtime, input)
    }
}

/// Installed composition supplies the Root pointer location and real physical
/// plan. Pointer bytes provide no authority; full E/S/CURRENT gates are checked
/// again at every guarded operation, including result reuse and final delivery.
pub fn open_current_cpu_neuron(
    pointer: PathBuf,
    plan: crate::CpuNeuronGenerationPlanV1,
    mode: crate::CpuNeuronGenerationOpenModeV1,
    control: Arc<Mutex<codex_hepta_infer_core::durable_control::DurableInferenceControl>>,
    clock: Arc<dyn AuthorityClock>,
    worker: crate::CpuNeuronControlConfigV1,
) -> HostResult<codex_hepta_agentd::AgentdNeuronHandleV2> {
    let guard = current_plan_admission(pointer, &plan, clock.clone(), &worker.worker_id)?;
    Ok(
        crate::local_cpu_generation::open_guarded_cpu_neuron_generation(
            plan, mode, control, clock, worker, guard,
        )?,
    )
}

/// Installed V2 borrows the model owner's sole journal and asks the original
/// Fleet resource authority on every operation, independently of model gen1.
pub fn open_current_cpu_neuron_v2(
    pointer: PathBuf,
    plan: crate::CpuNeuronGenerationPlanV1,
    mode: crate::CpuNeuronGenerationOpenModeV1,
    control: Arc<
        tokio::sync::Mutex<codex_hepta_infer_core::durable_control::DurableInferenceControl>,
    >,
    clock: Arc<dyn AuthorityClock>,
    worker: crate::CpuNeuronControlConfigV2,
) -> HostResult<codex_hepta_agentd::AgentdNeuronHandleV2> {
    let guard = current_plan_admission(
        pointer,
        &plan,
        clock.clone(),
        &worker.resources.binding().context.principal_id,
    )?;
    Ok(
        crate::local_cpu_generation::open_guarded_cpu_neuron_generation_v2(
            plan, mode, control, clock, worker, guard,
        )?,
    )
}

fn current_plan_admission(
    pointer: PathBuf,
    plan: &crate::CpuNeuronGenerationPlanV1,
    clock: Arc<dyn AuthorityClock>,
    worker_id: &str,
) -> HostResult<CurrentAdmission> {
    let active = CurrentInputs::read(&pointer, clock.clone())?;
    if active.inputs.runtime != plan.runtime
        || active.inputs.native != plan.native
        || active.inputs.profile.model.path != plan.model_manifest
        || active.inputs.evidence.model_manifest_digest() != plan.model_manifest_digest
        || active.inputs.evidence.objective_digest() != plan.scope.objective_digest
    {
        return Err("current installed CPU plan differs from independently frozen profile".into());
    }
    if active.inputs.profile.first_physical_installation.is_some() {
        let declared = renewal::verify_first_installation(&active.inputs.profile)?;
        if plan.generation_store != declared.generation_store
            || plan.runtime_index != declared.runtime_index
            || plan.witness != declared.witness
            || worker_id != declared.agent_id
            || rustix::process::geteuid().as_raw() != declared.workload_uid
            || rustix::process::getegid().as_raw() != declared.workload_gid
        {
            return Err(
                "actual first physical Owner differs from Root installation statement".into(),
            );
        }
    }
    Ok(CurrentAdmission {
        pointer,
        storage_binding: active.inputs.storage_binding(),
        model_source: active.inputs.profile.model.path.clone(),
        owner_root: active.inputs.profile.owner_root.clone(),
        last_now: clock.now_unix_ms()?,
        clock: clock.clone(),
        active,
    })
}

pub(super) fn describe_current_operational(path: &Path, pin: Digest32) -> HostResult<Value> {
    let pointer = Source {
        path: path.to_owned(),
        digest: pin.to_string(),
    };
    pointer.read(32 * 1024)?;
    let clock = Arc::new(codex_hepta_contracts::SystemAuthorityClock);
    let current = CurrentInputs::read(path, clock)?;
    pointer.read(32 * 1024)?;
    Ok(serde_json::json!({
        "schema": "hepta.cpu-neuron.verified-current-installation-inputs.v1",
        "runtime_config_digest": current.inputs.runtime.semantic_digest()?.to_string(),
        "execution_profile_digest": current.inputs.runtime.execution_profile_digest_v1()?.to_string(),
        "native_config_digest": current.inputs.native.digest()?.to_string(),
        "original_storage_binding_digest": current.inputs.storage_binding().to_string(),
        "model_manifest": current.inputs.profile.model,
        "weights": current.inputs.profile.weights,
        "normalization_digest": current.inputs.runtime.normalization_digest.to_string(),
        "objective_digest": current.inputs.evidence.objective_digest().to_string(),
        "generation": current.inputs.runtime.generation.get(),
        "registry_head": current.head.to_string(),
        "registry_record_count": current.record_count,
        "independent_evidence_digest": current.inputs.evidence.authentication_digest().to_string(),
        "expires_at_ms": current.inputs.evidence.expires_at().min(current.inputs.profile.expires_at_ms),
        "primary_superiority": false,
        "production_activation": false,
        "actual_neuron_tick": false,
    }))
}

/// The installed factory reads the same verified input set before constructing
/// its physical plan. Pointer bytes alone never supply admission authority.
pub(super) fn read_installed_inputs(
    pointer: &Path,
    clock: Arc<dyn AuthorityClock>,
) -> HostResult<Inputs> {
    Ok(CurrentInputs::read(pointer, clock)?.inputs)
}
