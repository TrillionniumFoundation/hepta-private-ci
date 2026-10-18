//! Cold-open a genuinely registered current model before loading one worker.
//! The directory selects sources; original CURRENT/E/S admission grants use.
use super::*;

#[derive(Clone)]
pub(in crate::initial_cpu_anchor) struct Bootstrap {
    pub(in crate::initial_cpu_anchor) plan: crate::CpuNeuronGenerationPlanV1,
    pub(in crate::initial_cpu_anchor) admission: Admission,
    pub(in crate::initial_cpu_anchor) installation: Source,
    pub(in crate::initial_cpu_anchor) weights: Source,
    pub(in crate::initial_cpu_anchor) tick_provider: Source,
}

pub(in crate::initial_cpu_anchor) fn read_bootstrap(
    source: &Source,
    identity: &AgentdIdentity,
    clock: Arc<dyn AuthorityClock>,
) -> HostResult<Option<Bootstrap>> {
    let bytes = source.read(32 * 1024)?;
    let descriptor: Descriptor = serde_json::from_slice(&bytes)?;
    if descriptor.schema != "hepta.cpu-neuron.protected-model-resolver.v3"
        || descriptor.subject != identity.agent_id.as_str()
        || !descriptor.registry_head.is_absolute()
    {
        return Err("registered bootstrap protected subject or source".into());
    }
    let head_bytes = read_root_review_input(&descriptor.registry_head, 64 * 1024)?;
    let registry: Registry = serde_json::from_slice(&head_bytes)?;
    let current = registry.current.typed()?;
    if current.subject.as_str() != identity.agent_id.as_str() {
        return Err("registered bootstrap CURRENT subject differs".into());
    }
    let entry =
        registry.registration(&current, CpuNeuronModelUsePurposeV3::CurrentSelectedNewGoal)?;
    let result = if current.generation.get() == 1 {
        None
    } else {
        let plan = codex_hepta_neuron::decode_neuron_generation_material_v2(
            &entry
                .installation
                .read(codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64)?,
        )?;
        require_material_identity(&plan, &current)?;
        let sources = entry
            .registered_model_use
            .as_ref()
            .ok_or("registered E/S sources")?;
        let weights = entry.weights.as_ref().ok_or("registered whole weights")?;
        if digest(&weights.digest)? != plan.runtime.weights_digest {
            return Err("registered weights differ from the full runtime".into());
        }
        let model = Source {
            path: plan.model_manifest.clone(),
            digest: plan.model_manifest_digest.to_string(),
        };
        let body = installed_plan::read_body(
            entry
                .compiled_body
                .as_ref()
                .ok_or("registered body closure")?,
            identity,
            &plan.runtime,
            entry
                .original_profile
                .as_ref()
                .ok_or("registered original profile")?,
            &model,
            weights,
        )?;
        if body != plan.body {
            return Err(
                "registered material differs from the original compiled body closure".into(),
            );
        }
        let admission = Admission::Registered(registered_admission::Admission::open(
            &sources.configuration,
            &sources.selection,
            &plan,
            identity,
            clock,
        )?);
        admission.inactive_state(current.subject.clone())?;
        Some(Bootstrap {
            plan,
            admission,
            installation: entry.installation.clone(),
            weights: weights.clone(),
            tick_provider: entry
                .tick_provider
                .as_ref()
                .ok_or("registered tick input")?
                .clone(),
        })
    };
    if source.read(32 * 1024)? != bytes
        || read_root_review_input(&descriptor.registry_head, 64 * 1024)? != head_bytes
    {
        return Err("registered bootstrap descriptor or CURRENT changed".into());
    }
    Ok(result)
}

pub(in crate::initial_cpu_anchor) fn require_material_identity(
    plan: &crate::CpuNeuronGenerationPlanV1,
    identity: &CpuNeuronModelIdentityV3,
) -> HostResult<()> {
    if plan.runtime.generation != identity.generation
        || plan.runtime.semantic_digest()? != identity.configuration_digest
        || plan.body.semantic_digest()? != identity.body_digest
    {
        return Err("registered complete material identity differs".into());
    }
    Ok(())
}
