//! Invocation and physical-input adapters borrow the Goal factory's resolver.
//! No latest-model lookup can silently replace an authenticated RunStart tuple.
use super::*;
use codex_hepta_agent_components::intelligence::CanonicalPortInputV1;
use codex_hepta_agent_components::learning_ledger::RunStartRecordV1;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::NeuronTickInputV1;

pub(in crate::initial_cpu_anchor) struct Provider {
    pub authority_file: PathBuf,
    pub verifier: IntelligenceAuthorityVerifierV1,
    pub resolver: Arc<dyn RegisteredCpuModelResolverV3>,
}
impl AgentdIntelligenceInvocationProviderV1 for Provider {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
        let read = || -> HostResult<_> {
            let cap = self.resolver.current(&id(identity.agent_id.as_str())?)?;
            if record.runtime_body_digest != cap.identity.body_digest
                || record.snapshot.model_tuple_digest != cap.plan.native.model_digest
            {
                return Err("RunStart cannot adopt a different current model/body".into());
            }
            cap.validate()?;
            let state = cap.admission.inactive_state(cap.identity.subject.clone())?;
            let provider = AgentdDurableCpuAbstainInvocationProviderV2::new(
                self.authority_file.clone(),
                self.verifier.clone(),
                cap.plan.native.clone(),
                cap.identity.configuration_digest,
                cap.identity.body_digest,
            )?
            .with_inactive_state(state);
            let invocation = provider.build(identity, record)?;
            self.resolver.resolve(
                &cap.identity,
                CpuNeuronModelUsePurposeV3::CurrentSelectedNewGoal,
            )?;
            Ok(invocation)
        };
        read().map_err(|error| {
            AgentdError::Invalid(format!("registered CPU invocation unavailable: {error}"))
        })
    }
}

pub(super) struct Tick {
    pub resolver: Arc<dyn RegisteredCpuModelResolverV3>,
}
impl AgentdNeuronTickProviderV2 for Tick {
    fn build_tick(
        &self,
        _: &AgentdIdentity,
        _: &RunStartRecordV1,
        _: &AgentdIntelligenceInvocationV1,
    ) -> Result<NeuronTickInputV1, AgentdError> {
        Err(AgentdError::Invalid(
            "registered physical input requires the late canonical stage".into(),
        ))
    }
    fn build_tick_for_stage(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        invocation: &AgentdIntelligenceInvocationV1,
        stage: &CanonicalPortInputV1,
        current: (Generation, Option<JournalAnchor>),
    ) -> Result<NeuronTickInputV1, AgentdError> {
        let read = || -> HostResult<_> {
            let cap = self.resolver.current(&id(identity.agent_id.as_str())?)?;
            if current.0 != cap.identity.generation
                || record.runtime_body_digest != cap.identity.body_digest
                || invocation.inputs.neural_config != cap.plan.native
                || invocation.request.snapshot.body_generation() != cap.identity.generation
            {
                return Err(
                    "physical stage cannot adopt a different registered model tuple".into(),
                );
            }
            cap.validate()?;
            let tick = cap
                .tick
                .build_tick_for_stage(identity, record, invocation, stage, current)?;
            self.resolver.resolve(
                &cap.identity,
                CpuNeuronModelUsePurposeV3::CurrentSelectedNewGoal,
            )?;
            Ok(tick)
        };
        read().map_err(|error| {
            AgentdError::Invalid(format!(
                "registered CPU physical input unavailable: {error}"
            ))
        })
    }
}
