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

pub(super) struct Admission {
    pointer: PathBuf,
    active: CurrentUse,
    runtime: NeuronRuntimeConfigV1,
    scope: JournalScope,
    clock: Arc<dyn AuthorityClock>,
    last_now: u64,
}
impl Admission {
    pub(super) fn binding(
        &self,
    ) -> &codex_hepta_agent_components::intelligence_eval::OperationalModelLeaseBindingV2 {
        self.active.verified.binding()
    }

    pub(super) fn open(
        pointer: PathBuf,
        plan: &crate::CpuNeuronGenerationPlanV1,
        identity: &codex_hepta_agentd::AgentdIdentity,
        clock: Arc<dyn AuthorityClock>,
    ) -> HostResult<Self> {
        let before = clock.now_unix_ms()?;
        let active = CurrentUse::read(&pointer)?;
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
            return Err(
                "current model use differs from the physical owner and compiled scope".into(),
            );
        }
        let after = clock.now_unix_ms()?;
        if after < before
            || after < active.verified.issued_at()
            || after >= active.verified.expires_at()
        {
            return Err("actual owner clock is outside current model use".into());
        }
        Ok(Self {
            pointer,
            active,
            runtime: plan.runtime.clone(),
            scope: plan.scope,
            last_now: after,
            clock,
        })
    }

    fn refresh(&mut self) -> HostResult<()> {
        let now = self.clock.now_unix_ms()?;
        if now < self.last_now {
            return Err("owned model-use clock rolled back".into());
        }
        let bytes = read_root_review_input(&self.pointer, 32 * 1024)?;
        if bytes != self.active.bytes {
            let fresh = CurrentUse::read(&self.pointer)?;
            let before = self.active.verified.installed_inputs();
            let after = fresh.verified.installed_inputs();
            if fresh.verified.binding() != self.active.verified.binding()
                || fresh.verified.runtime_configuration() != &self.runtime
                || fresh.verified.runtime_body_digest()
                    != self.active.verified.runtime_body_digest()
                || after.storage_binding() != before.storage_binding()
                || after.profile.owner_root != before.profile.owner_root
                || after.profile.model.path != before.profile.model.path
                || fresh.verified.issued_at() < self.active.verified.issued_at()
                || fresh.verified.expires_at() < self.active.verified.expires_at()
                || !frontier_extends(self.active.frontier, fresh.frontier)
            {
                return Err(
                    "fresh model use changed the physical identity or rolled back its frontier"
                        .into(),
                );
            }
            self.active = fresh;
        }
        self.active.verified.revalidate_current()?;
        let after = self.clock.now_unix_ms()?;
        if after < now
            || after < self.active.verified.issued_at()
            || after >= self.active.verified.expires_at()
            || read_root_review_input(&self.pointer, 32 * 1024)? != self.active.bytes
        {
            return Err("model-use clock or pointer changed at use".into());
        }
        self.last_now = after;
        Ok(())
    }
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
