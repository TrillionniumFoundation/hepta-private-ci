//! Admission for the distinct registered-successor E/S purpose. The original
//! artifact owner still verifies all three payloads and selectors at use;
//! per-Goal scope remains independently enforced by the original controller.
use super::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronAdmissionError;
use codex_hepta_neuron::NeuronAdmissionGuard;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronTickInputV1;
use std::sync::Arc;
use std::sync::Mutex;

#[derive(Clone)]
pub(super) struct Admission {
    evidence: Arc<registered_model_use::VerifiedRegisteredCpuModelUseV3>,
    artifacts: Arc<Mutex<codex_hepta_agentd::AgentdNeuronArtifactAdmissionV1>>,
    runtime: NeuronRuntimeConfigV1,
    training_scope: JournalScope,
    scope: JournalScope,
    subject: StableId,
    clock: Arc<dyn AuthorityClock>,
    last_time: Arc<Mutex<u64>>,
}
impl Admission {
    pub(super) fn open(
        configuration: &Source,
        selection: &Source,
        plan: &crate::CpuNeuronGenerationPlanV1,
        identity: &codex_hepta_agentd::AgentdIdentity,
        clock: Arc<dyn AuthorityClock>,
    ) -> HostResult<Self> {
        let now = clock.now_unix_ms()?;
        let verified = registered_model_use::inspect_cpu_registered_model_use_v3(
            &configuration.path,
            digest(&configuration.digest)?,
            &selection.path,
            digest(&selection.digest)?,
        )?;
        if verified.workload_uid() != rustix::process::geteuid().as_raw()
            || verified.binding().subject != identity.agent_id.as_str()
            || !same_model(plan, verified.material())
            || now < verified.issued_at()
            || now >= verified.expires_at()
        {
            return Err(
                "registered model-use differs from actual workload and full material".into(),
            );
        }
        let artifacts = verified.original_artifact_admission(clock.clone())?;
        let result = Self {
            training_scope: verified.material().scope,
            runtime: plan.runtime.clone(),
            scope: plan.scope,
            subject: id(identity.agent_id.as_str())?,
            evidence: Arc::new(verified),
            artifacts: Arc::new(Mutex::new(artifacts)),
            clock,
            last_time: Arc::new(Mutex::new(now)),
        };
        result.revalidate()?;
        Ok(result)
    }
    pub(super) fn for_scope(
        &self,
        plan: &crate::CpuNeuronGenerationPlanV1,
        identity: &codex_hepta_agentd::AgentdIdentity,
    ) -> HostResult<Self> {
        if identity.agent_id.as_str() != self.subject.as_str()
            || !same_model(plan, self.evidence.material())
            || NeuronTickInputV1::journal_scope_for_subject(
                &self.subject,
                plan.scope.objective_digest,
            )? != plan.scope
        {
            return Err("registered model-use cannot replace actual Goal model/scope".into());
        }
        let mut next = self.clone();
        next.scope = plan.scope;
        next.revalidate()?;
        Ok(next)
    }
    pub(super) fn inactive_state(
        &self,
        subject: StableId,
    ) -> HostResult<codex_hepta_agentd::ConservativeCpuStateV1> {
        if subject != self.subject {
            return Err("registered workload subject differs".into());
        }
        self.revalidate()?;
        Ok(
            codex_hepta_agentd::ConservativeCpuStateV1::from_current_payloads(
                subject,
                [
                    digest(&self.evidence.binding().payload_digests[0])?,
                    digest(&self.evidence.binding().payload_digests[1])?,
                    digest(&self.evidence.binding().payload_digests[2])?,
                ],
            )?,
        )
    }
    fn revalidate(&self) -> HostResult<()> {
        let mut last = self
            .last_time
            .lock()
            .map_err(|_| "registered clock poisoned")?;
        let before = self.clock.now_unix_ms()?;
        if before < *last
            || before < self.evidence.issued_at()
            || before >= self.evidence.expires_at()
        {
            return Err("registered model-use clock closed".into());
        }
        self.evidence.revalidate_current()?;
        self.artifacts
            .lock()
            .map_err(|_| "registered current admission poisoned")?
            .check_scope(&self.runtime, self.training_scope)
            .map_err(|error| format!("original registered artifact admission: {error:?}"))?;
        let after = self.clock.now_unix_ms()?;
        if after < before || after >= self.evidence.expires_at() {
            return Err("registered model-use expired at actual use".into());
        }
        *last = after;
        Ok(())
    }
}
fn same_model(
    a: &crate::CpuNeuronGenerationPlanV1,
    b: &codex_hepta_neuron::NeuronGenerationMaterialV2,
) -> bool {
    a.native == b.native
        && a.runtime == b.runtime
        && a.body == b.body
        && a.model_manifest == b.model_manifest
        && a.model_manifest_digest == b.model_manifest_digest
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
        self.revalidate()
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
