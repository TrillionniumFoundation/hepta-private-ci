//! Preserve the original initial purpose and the distinct registered purpose.
use super::*;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronAdmissionError;
use codex_hepta_neuron::NeuronAdmissionGuard;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronTickInputV1;
#[derive(Clone)]
pub(in crate::initial_cpu_anchor) enum Admission {
    Initial(model_use_current::Admission),
    Registered(registered_admission::Admission),
}
impl Admission {
    pub(in crate::initial_cpu_anchor) fn for_scope(
        &self,
        plan: &crate::CpuNeuronGenerationPlanV1,
        identity: &codex_hepta_agentd::AgentdIdentity,
    ) -> HostResult<Self> {
        match self {
            Self::Initial(value) => Ok(Self::Initial(value.for_scope(plan, identity)?)),
            Self::Registered(value) => Ok(Self::Registered(value.for_scope(plan, identity)?)),
        }
    }
    pub(in crate::initial_cpu_anchor) fn inactive_state(
        &self,
        subject: StableId,
    ) -> HostResult<codex_hepta_agentd::ConservativeCpuStateV1> {
        match self {
            Self::Initial(value) => value.inactive_state(subject),
            Self::Registered(value) => value.inactive_state(subject),
        }
    }
}
impl NeuronAdmissionGuard for Admission {
    fn check_scope(
        &mut self,
        config: &NeuronRuntimeConfigV1,
        scope: JournalScope,
    ) -> Result<(), NeuronAdmissionError> {
        match self {
            Self::Initial(value) => value.check_scope(config, scope),
            Self::Registered(value) => value.check_scope(config, scope),
        }
    }
    fn check(
        &mut self,
        config: &NeuronRuntimeConfigV1,
        input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        match self {
            Self::Initial(value) => value.check(config, input),
            Self::Registered(value) => value.check(config, input),
        }
    }
}
