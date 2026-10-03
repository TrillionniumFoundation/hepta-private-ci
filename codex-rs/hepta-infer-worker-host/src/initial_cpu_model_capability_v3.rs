//! Read-only resolution of the whole registered model capability. A registry
//! pointer selects material; original Root/E/S/CURRENT checks grant its use.
use super::*;
use serde::Deserialize;
#[path = "initial_cpu_current_material_projection_v3.rs"]
mod current_material;
#[path = "initial_cpu_model_admission_v3.rs"]
mod model_admission;
#[path = "initial_cpu_registered_admission_v3.rs"]
mod registered_admission;
pub(in crate::initial_cpu_anchor) use model_admission::Admission;
#[path = "initial_cpu_registered_bootstrap_v3.rs"]
mod registered_bootstrap;
pub(in crate::initial_cpu_anchor) use registered_bootstrap::Bootstrap;
pub(in crate::initial_cpu_anchor) use registered_bootstrap::read_bootstrap;
pub(in crate::initial_cpu_anchor) use registered_bootstrap::require_material_identity;

#[derive(Clone, Default)]
pub struct CpuNeuronOriginalGenerationReaderV3 {
    current: Arc<std::sync::Mutex<Option<crate::CpuNeuronGenerationCompositionReaderV2>>>,
}
impl CpuNeuronOriginalGenerationReaderV3 {
    /// Publication is owned by the installed Round driver. It changes only the
    /// bounded read view; it grants no model registration or execution authority.
    pub fn publish_round_reader(
        &self,
        reader: crate::CpuNeuronGenerationCompositionReaderV2,
    ) -> Result<(), AgentdError> {
        *self.current.lock().map_err(|_| {
            AgentdError::Protocol("current original physical reader poisoned".into())
        })? = Some(reader);
        Ok(())
    }
    fn resolve(
        &self,
        identity: &CpuNeuronModelIdentityV3,
    ) -> Result<Option<crate::CpuNeuronGenerationCompositionV2>, AgentdError> {
        let reader = self
            .current
            .try_lock()
            .map_err(|_| AgentdError::Overloaded { retry_after_ms: 25 })?
            .clone();
        reader
            .map(|reader| {
                reader.resolve(
                    identity.generation,
                    identity.configuration_digest,
                    identity.body_digest,
                )
            })
            .transpose()
            .map(Option::flatten)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CpuNeuronModelIdentityV3 {
    pub generation: Generation,
    pub configuration_digest: Digest32,
    pub body_digest: Digest32,
    pub subject: StableId,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CpuNeuronModelUsePurposeV3 {
    CurrentSelectedNewGoal,
    HistoricalRecovery,
}

/// Implemented by the installed protected descriptor reader. Callers provide
/// exact identity and purpose, never file paths, grants or replacement plans.
pub trait RegisteredCpuModelResolverV3: Send + Sync {
    fn current(&self, subject: &StableId) -> Result<Arc<CpuNeuronModelCapabilityV3>, AgentdError>;
    fn resolve(
        &self,
        identity: &CpuNeuronModelIdentityV3,
        purpose: CpuNeuronModelUsePurposeV3,
    ) -> Result<Arc<CpuNeuronModelCapabilityV3>, AgentdError>;
}

/// Sealed by the original verified installed reader, not deserializable from a
/// request. The physical control is the same Arc used by the Goal factory.
pub struct CpuNeuronModelCapabilityV3 {
    pub(super) identity: CpuNeuronModelIdentityV3,
    pub(super) installation: Source,
    pub(super) plan: crate::CpuNeuronGenerationPlanV1,
    pub(super) admission: Admission,
    pub(super) physical: crate::SharedCpuNeuronInferenceControlV3,
    pub(super) tick: Arc<tick::TickProvider>,
    pub(super) weights: Source,
}
impl CpuNeuronModelCapabilityV3 {
    pub fn identity(&self) -> &CpuNeuronModelIdentityV3 {
        &self.identity
    }
    pub fn plan(&self) -> &crate::CpuNeuronGenerationPlanV1 {
        &self.plan
    }
    pub(super) fn validate(&self) -> HostResult<()> {
        let manifest = Source {
            path: self.plan.model_manifest.clone(),
            digest: self.plan.model_manifest_digest.to_string(),
        };
        manifest.read(64 * 1024)?;
        if digest(&self.weights.digest)? != self.plan.runtime.weights_digest {
            return Err("whole registered weights differ from the original runtime".into());
        }
        self.weights.read(16 * 1024 * 1024)?;
        self.physical.validate_runtime(&self.plan.runtime)?;
        self.admission
            .inactive_state(self.identity.subject.clone())?;
        Ok(())
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Descriptor {
    schema: String,
    subject: String,
    registry_head: PathBuf,
}
#[derive(Clone, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
struct WireIdentity {
    generation: u64,
    configuration_digest: String,
    body_digest: String,
    subject: String,
}
impl WireIdentity {
    fn typed(&self) -> HostResult<CpuNeuronModelIdentityV3> {
        let configuration_digest = digest(&self.configuration_digest)?;
        let body_digest = digest(&self.body_digest)?;
        if configuration_digest.is_zero() || body_digest.is_zero() {
            return Err("registered model identity is absent".into());
        }
        Ok(CpuNeuronModelIdentityV3 {
            generation: Generation::new(self.generation)?,
            configuration_digest,
            body_digest,
            subject: id(&self.subject)?,
        })
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Registration {
    identity: WireIdentity,
    installation: Source,
    operational_reader: String,
    #[serde(default)]
    registered_model_use: Option<RegisteredSources>,
    #[serde(default)]
    tick_provider: Option<Source>,
    #[serde(default)]
    weights: Option<Source>,
    #[serde(default)]
    compiled_body: Option<Source>,
    #[serde(default)]
    original_profile: Option<Source>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RegisteredSources {
    configuration: Source,
    selection: Source,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Registry {
    schema: String,
    current: WireIdentity,
    registrations: Vec<Registration>,
}
impl Registry {
    fn registration(
        &self,
        identity: &CpuNeuronModelIdentityV3,
        purpose: CpuNeuronModelUsePurposeV3,
    ) -> HostResult<&Registration> {
        if self.schema != "hepta.cpu-neuron.registered-model-head.v3"
            || self.registrations.is_empty()
            || self.registrations.len() > 64
            || (purpose == CpuNeuronModelUsePurposeV3::CurrentSelectedNewGoal
                && self.current.typed()? != *identity)
        {
            return Err("registered model head or current purpose differs".into());
        }
        let mut matched = None;
        let mut identities = Vec::new();
        for entry in &self.registrations {
            let key = entry.identity.typed()?;
            if identities.contains(&key) || key.subject != identity.subject {
                return Err("registered model identities are ambiguous".into());
            }
            if key == *identity {
                matched = Some(entry);
            }
            identities.push(key);
        }
        let entry = matched.ok_or("exact model has no original Root registration")?;
        match (identity.generation.get(), entry.operational_reader.as_str()) {
            (1, "original-installed-model-use.v2")
                if entry.registered_model_use.is_none()
                    && entry.tick_provider.is_none()
                    && entry.weights.is_none()
                    && entry.compiled_body.is_none()
                    && entry.original_profile.is_none() => {}
            (2.., "original-registered-model-use.v3")
                if entry.registered_model_use.is_some()
                    && entry.tick_provider.is_some()
                    && entry.weights.is_some()
                    && entry.compiled_body.is_some()
                    && entry.original_profile.is_some() => {}
            _ => {
                return Err(
                    "model generation requires its exact original operational purpose".into(),
                );
            }
        }
        Ok(entry)
    }
}

pub(super) struct ProtectedReader {
    descriptor: Source,
    descriptor_bytes: Vec<u8>,
    registry_head: PathBuf,
    identity: AgentdIdentity,
    clock: Arc<dyn AuthorityClock>,
    baseline: Arc<CpuNeuronModelCapabilityV3>,
    original_generations: CpuNeuronOriginalGenerationReaderV3,
}
impl ProtectedReader {
    pub(super) fn open(
        descriptor: Source,
        identity: AgentdIdentity,
        clock: Arc<dyn AuthorityClock>,
        baseline: CpuNeuronModelCapabilityV3,
        original_generations: CpuNeuronOriginalGenerationReaderV3,
    ) -> HostResult<Self> {
        let bytes = descriptor.read(32 * 1024)?;
        let parsed: Descriptor = serde_json::from_slice(&bytes)?;
        if parsed.schema != "hepta.cpu-neuron.protected-model-resolver.v3"
            || parsed.subject != identity.agent_id.as_str()
            || !parsed.registry_head.is_absolute()
        {
            return Err("installed registered-model descriptor identity".into());
        }
        let reader = Self {
            descriptor,
            descriptor_bytes: bytes,
            registry_head: parsed.registry_head,
            identity,
            clock,
            baseline: Arc::new(baseline),
            original_generations,
        };
        reader.current(&reader.baseline.identity.subject)?;
        Ok(reader)
    }
    fn read(&self) -> HostResult<(Vec<u8>, Registry)> {
        if self.descriptor.read(32 * 1024)? != self.descriptor_bytes {
            return Err("protected model resolver descriptor changed".into());
        }
        let bytes = read_root_review_input(&self.registry_head, 64 * 1024)?;
        let registry = serde_json::from_slice(&bytes)?;
        Ok((bytes, registry))
    }
    fn resolve_registered(
        &self,
        registry_bytes: &[u8],
        registry: &Registry,
        identity: &CpuNeuronModelIdentityV3,
        purpose: CpuNeuronModelUsePurposeV3,
    ) -> HostResult<Arc<CpuNeuronModelCapabilityV3>> {
        let registered = registry.registration(identity, purpose)?;
        let capability = if identity.generation.get() == 1 {
            if identity != &self.baseline.identity
                || registered.installation != self.baseline.installation
            {
                return Err(
                    "registered initial material has no authenticated physical capability".into(),
                );
            }
            let (_, fresh, _, _) = installed_plan::load(
                &InstalledCpuSourceV1 {
                    path: registered.installation.path.clone(),
                    digest: registered.installation.digest.clone(),
                },
                &self.identity,
                self.clock.clone(),
            )?;
            if !same_plan(&fresh, &self.baseline.plan) {
                return Err("registered initial complete generation plan changed".into());
            }
            self.baseline.clone()
        } else {
            let material_bytes = registered
                .installation
                .read(codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64)?;
            let plan = codex_hepta_neuron::decode_neuron_generation_material_v2(&material_bytes)?;
            require_material_identity(&plan, identity)?;
            let physical = if identity == &self.baseline.identity {
                if registered.installation != self.baseline.installation
                    || !same_plan(&self.baseline.plan, &plan)
                {
                    return Err("registered cold-opened complete material changed".into());
                }
                self.baseline.physical.clone()
            } else {
                let original = self
                    .original_generations
                    .resolve(identity)?
                    .ok_or("registered successor original physical composition unavailable")?;
                if !same_plan(original.plan(), &plan) {
                    return Err(
                        "registered successor does not match all original stores/contexts".into(),
                    );
                }
                original.physical_shared()
            };
            let sources = registered
                .registered_model_use
                .as_ref()
                .ok_or("successor original E/S model-use sources")?;
            let admission = registered_admission::Admission::open(
                &sources.configuration,
                &sources.selection,
                &plan,
                &self.identity,
                self.clock.clone(),
            )?;
            let tick_source = registered
                .tick_provider
                .as_ref()
                .ok_or("successor physical input")?;
            physical.validate_runtime(&plan.runtime)?;
            let tick = Arc::new(tick::TickProvider::open_mode(
                tick_source.clone(),
                &plan,
                tick::GoalMode::ActualCompiledGoal {
                    encoder_manifest_digest: plan.runtime.encoder_digest,
                    tokenizer_digest: plan.runtime.tokenizer_digest,
                },
            )?);
            Arc::new(CpuNeuronModelCapabilityV3 {
                identity: identity.clone(),
                installation: registered.installation.clone(),
                plan,
                admission: Admission::Registered(admission),
                physical,
                tick,
                weights: registered
                    .weights
                    .as_ref()
                    .ok_or("successor weights source")?
                    .clone(),
            })
        };
        capability.validate()?;
        if purpose == CpuNeuronModelUsePurposeV3::HistoricalRecovery {
            mode(
                [
                    &capability.plan.generation_store,
                    &capability.plan.runtime_index,
                    &capability.plan.witness,
                ],
                StoreRequirement::Existing,
            )?;
        }
        if self.descriptor.read(32 * 1024)? != self.descriptor_bytes
            || read_root_review_input(&self.registry_head, 64 * 1024)? != registry_bytes
        {
            return Err("registered model source or head changed at use".into());
        }
        Ok(capability)
    }
}
impl RegisteredCpuModelResolverV3 for ProtectedReader {
    fn current(&self, subject: &StableId) -> Result<Arc<CpuNeuronModelCapabilityV3>, AgentdError> {
        let read = || -> HostResult<_> {
            let (bytes, registry) = self.read()?;
            let current = registry.current.typed()?;
            if &current.subject != subject {
                return Err("current model subject differs".into());
            }
            self.resolve_registered(
                &bytes,
                &registry,
                &current,
                CpuNeuronModelUsePurposeV3::CurrentSelectedNewGoal,
            )
        };
        read().map_err(unavailable)
    }
    fn resolve(
        &self,
        identity: &CpuNeuronModelIdentityV3,
        purpose: CpuNeuronModelUsePurposeV3,
    ) -> Result<Arc<CpuNeuronModelCapabilityV3>, AgentdError> {
        let read = || -> HostResult<_> {
            let (bytes, registry) = self.read()?;
            self.resolve_registered(&bytes, &registry, identity, purpose)
        };
        read().map_err(unavailable)
    }
}
fn same_plan(a: &crate::CpuNeuronGenerationPlanV1, b: &crate::CpuNeuronGenerationPlanV1) -> bool {
    a.model_manifest == b.model_manifest
        && a.model_manifest_digest == b.model_manifest_digest
        && a.generation_store == b.generation_store
        && a.runtime_index == b.runtime_index
        && a.witness == b.witness
        && a.native == b.native
        && a.scope == b.scope
        && a.runtime == b.runtime
        && a.body == b.body
        && a.store_context == b.store_context
        && a.index_context == b.index_context
        && a.witness_context == b.witness_context
}
fn unavailable(error: Box<dyn std::error::Error>) -> AgentdError {
    AgentdError::Invalid(format!("registered CPU model unavailable: {error}"))
}

#[cfg(test)]
#[path = "initial_cpu_model_capability_v3_tests.rs"]
mod tests;
