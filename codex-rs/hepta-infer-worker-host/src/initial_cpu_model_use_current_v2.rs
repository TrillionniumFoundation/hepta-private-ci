//! Reinspect the independent model-use lease at each actual Goal operation.
//! This guard supplies model admission only; the original canonical stage and
//! final-use owners continue to authorize the Goal and its effects.
use super::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_neuron::JournalScope;
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
    configuration: Source,
    selection: Source,
}
struct CurrentUse {
    bytes: Vec<u8>,
    verified: VerifiedCpuModelUseV2,
    frontier: (usize, Digest32, u64),
}
impl CurrentUse {
    fn read(path: &Path) -> HostResult<Self> {
        let bytes = read_root_review_input(path, 32 * 1024)?;
        let pointer: Pointer = serde_json::from_slice(&bytes)?;
        if pointer.schema != "hepta.cpu-neuron.current-installed-model-use-pointer.v2" {
            return Err("current installed model-use pointer schema".into());
        }
        let verified = inspect_cpu_model_use_v2(
            &pointer.configuration.path,
            digest(&pointer.configuration.digest)?,
            &pointer.selection.path,
            digest(&pointer.selection.digest)?,
        )?;
        verified.revalidate_current()?;
        let frontier = verified.current_frontier()?;
        if read_root_review_input(path, 32 * 1024)? != bytes {
            return Err("model-use pointer changed during independent inspection".into());
        }
        Ok(Self {
            bytes,
            verified,
            frontier,
        })
    }
}

pub(super) fn read_installed_inputs(
    path: &Path,
    clock: Arc<dyn AuthorityClock>,
) -> HostResult<Inputs> {
    let before = clock.now_unix_ms()?;
    let current = CurrentUse::read(path)?;
    current.verified.revalidate_current()?;
    let after = clock.now_unix_ms()?;
    if after < before
        || after < current.verified.issued_at()
        || after >= current.verified.expires_at()
        || read_root_review_input(path, 32 * 1024)? != current.bytes
    {
        return Err("model-use clock or pointer changed during installed recovery".into());
    }
    Ok(current.verified.into_installed_inputs())
}

struct CurrentState {
    active: CurrentUse,
    last_now: u64,
}

#[derive(Clone)]
pub(super) struct Admission {
    pointer: PathBuf,
    current: Arc<Mutex<CurrentState>>,
    binding: codex_hepta_agent_components::intelligence_eval::OperationalModelLeaseBindingV2,
    runtime: NeuronRuntimeConfigV1,
    scope: JournalScope,
    clock: Arc<dyn AuthorityClock>,
}
impl Admission {
    pub(super) fn binding(
        &self,
    ) -> &codex_hepta_agent_components::intelligence_eval::OperationalModelLeaseBindingV2 {
        &self.binding
    }

    pub(super) fn open(
        pointer: PathBuf,
        plan: &crate::CpuNeuronGenerationPlanV1,
        identity: &codex_hepta_agentd::AgentdIdentity,
        clock: Arc<dyn AuthorityClock>,
    ) -> HostResult<Self> {
        let before = clock.now_unix_ms()?;
        let active = CurrentUse::read(&pointer)?;
        verify_plan(&active, plan, identity)?;
        let after = clock.now_unix_ms()?;
        if after < before
            || after < active.verified.issued_at()
            || after >= active.verified.expires_at()
        {
            return Err("actual owner clock is outside current model use".into());
        }
        Ok(Self {
            pointer,
            binding: active.verified.binding().clone(),
            current: Arc::new(Mutex::new(CurrentState {
                active,
                last_now: after,
            })),
            runtime: plan.runtime.clone(),
            scope: plan.scope,
            clock,
        })
    }

    pub(super) fn for_scope(
        &self,
        plan: &crate::CpuNeuronGenerationPlanV1,
        identity: &codex_hepta_agentd::AgentdIdentity,
    ) -> HostResult<Self> {
        // Share only the sealed physical material and its monotonic current-use
        // state. Each Goal retains its own exact scope and dispatch admission.
        let mut next = self.clone();
        next.scope = plan.scope;
        next.refresh()?;
        verify_plan(
            &next
                .current
                .lock()
                .map_err(|_| "model-use state poisoned")?
                .active,
            plan,
            identity,
        )?;
        Ok(next)
    }

    fn refresh(&mut self) -> HostResult<()> {
        let mut state = self
            .current
            .lock()
            .map_err(|_| "model-use state poisoned")?;
        let now = self.clock.now_unix_ms()?;
        if now < state.last_now {
            return Err("owned model-use clock rolled back".into());
        }
        let bytes = read_root_review_input(&self.pointer, 32 * 1024)?;
        if bytes != state.active.bytes {
            let fresh = CurrentUse::read(&self.pointer)?;
            let before = state.active.verified.installed_inputs();
            let after = fresh.verified.installed_inputs();
            if fresh.verified.binding() != &self.binding
                || fresh.verified.runtime_configuration() != &self.runtime
                || fresh.verified.runtime_body_digest()
                    != state.active.verified.runtime_body_digest()
                || after.storage_binding() != before.storage_binding()
                || after.profile.owner_root != before.profile.owner_root
                || after.profile.model.path != before.profile.model.path
                || fresh.verified.issued_at() < state.active.verified.issued_at()
                || fresh.verified.expires_at() < state.active.verified.expires_at()
                || !frontier_extends(state.active.frontier, fresh.frontier)
            {
                return Err(
                    "fresh model use changed the physical identity or rolled back its frontier"
                        .into(),
                );
            }
            state.active = fresh;
        }
        state.active.verified.revalidate_current()?;
        let after = self.clock.now_unix_ms()?;
        if after < now
            || after < state.active.verified.issued_at()
            || after >= state.active.verified.expires_at()
            || read_root_review_input(&self.pointer, 32 * 1024)? != state.active.bytes
        {
            return Err("model-use clock or pointer changed at use".into());
        }
        state.last_now = after;
        Ok(())
    }
}
fn verify_plan(
    active: &CurrentUse,
    plan: &crate::CpuNeuronGenerationPlanV1,
    identity: &codex_hepta_agentd::AgentdIdentity,
) -> HostResult<()> {
    let inputs = active.verified.installed_inputs();
    let declared = renewal::verify_first_installation(&inputs.profile)?;
    if active.verified.runtime_configuration() != &plan.runtime
        || active.verified.native_configuration() != &plan.native
        || active.verified.runtime_body_digest() != plan.body.semantic_digest()?
        || inputs.profile.model.path != plan.model_manifest
        || active.verified.binding().model_manifest_digest != plan.model_manifest_digest
        || declared.agent_id != identity.agent_id.as_str()
        || declared.workload_uid != rustix::process::geteuid().as_raw()
        || declared.workload_gid != rustix::process::getegid().as_raw()
        || NeuronTickInputV1::journal_scope_for_subject(
            &id(identity.agent_id.as_str())?,
            plan.scope.objective_digest,
        )? != plan.scope
    {
        return Err("current model use differs from the physical owner and compiled scope".into());
    }
    Ok(())
}
fn frontier_extends(before: (usize, Digest32, u64), after: (usize, Digest32, u64)) -> bool {
    after.0 >= before.0 && after.2 >= before.2 && (after.0 != before.0 || after.1 == before.1)
}
impl NeuronAdmissionGuard for Admission {
    fn check_scope(
        &mut self,
        runtime: &NeuronRuntimeConfigV1,
        scope: JournalScope,
    ) -> Result<(), NeuronAdmissionError> {
        if runtime != &self.runtime || scope != self.scope {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        self.refresh()
            .map_err(|_| NeuronAdmissionError::Unavailable)
    }
    fn check(
        &mut self,
        runtime: &NeuronRuntimeConfigV1,
        input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        self.check_scope(
            runtime,
            input
                .journal_scope()
                .map_err(|_| NeuronAdmissionError::BindingMismatch)?,
        )
    }
}

#[cfg(test)]
#[path = "initial_cpu_model_use_current_v2_tests.rs"]
mod tests;
