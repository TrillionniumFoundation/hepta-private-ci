//! The installed callback opens Goal journals around the original physical CPU
//! and native-control owners. The sole Agentd controller publishes each switch.
use super::*;
use codex_hepta_agentd::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_neuron::NeuronTickInputV1;
use std::os::unix::fs::MetadataExt;
use std::path::PathBuf;
use std::sync::Arc;

#[path = "initial_cpu_model_adapters_v3.rs"]
pub(super) mod model_adapters;
#[path = "initial_cpu_model_capability_v3.rs"]
pub(super) mod model_capability;
use model_capability::CpuNeuronModelIdentityV3;
use model_capability::CpuNeuronModelUsePurposeV3;
use model_capability::RegisteredCpuModelResolverV3;

struct Factory {
    descriptor: Source,
    descriptor_bytes: Vec<u8>,
    identity: AgentdIdentity,
    plan: crate::CpuNeuronGenerationPlanV1,
    admission: model_capability::Admission,
    physical: crate::SharedCpuNeuronInferenceControlV3,
    resolver: Option<Arc<dyn RegisteredCpuModelResolverV3>>,
}
#[derive(Clone, Copy)]
pub(super) enum StoreRequirement {
    NewOrExisting,
    Existing,
}

impl Factory {
    fn verify_descriptor(&self) -> HostResult<()> {
        if self.descriptor.read(32 * 1024)? != self.descriptor_bytes {
            return Err("installed Goal factory descriptor changed".into());
        }
        Ok(())
    }
    fn open(
        &self,
        scope: &AgentdNeuronGoalScopeV3,
        requirement: StoreRequirement,
        purpose: CpuNeuronModelUsePurposeV3,
    ) -> HostResult<AgentdNeuronHandleV2> {
        self.verify_descriptor()?;
        let capability = self
            .resolver
            .as_ref()
            .map(|resolver| -> HostResult<_> {
                Ok(resolver.resolve(&model_identity(scope, &self.identity)?, purpose)?)
            })
            .transpose()?;
        let original = capability.as_ref().map_or(&self.plan, |cap| &cap.plan);
        let plan = scope_plan(original, &self.identity, scope)?;
        let original_admission = capability
            .as_ref()
            .map_or(&self.admission, |cap| &cap.admission);
        let admission = original_admission.for_scope(&plan, &self.identity)?;
        let mode = mode(
            [&plan.generation_store, &plan.runtime_index, &plan.witness],
            requirement,
        )?;
        let handle = crate::open_shared_cpu_neuron_goal_scope_v3(
            plan,
            mode,
            capability
                .as_ref()
                .map_or_else(|| self.physical.clone(), |cap| cap.physical.clone()),
            admission,
        )?;
        if AgentdNeuronGoalScopeV3::capture(scope.ordinal, &handle)? != *scope {
            return Err("recovered physical Goal header differs from the sole controller".into());
        }
        self.verify_descriptor()?;
        Ok(handle)
    }
}
impl AgentdNeuronGoalScopeFactoryV3 for Factory {
    fn open_goal_scope(
        &self,
        identity: &AgentdIdentity,
        record: &codex_hepta_agent_components::learning_ledger::RunStartRecordV1,
        invocation: &AgentdIntelligenceInvocationV1,
        stage: &codex_hepta_agent_components::intelligence::CanonicalPortInputV1,
        expected: &AgentdNeuronGoalScopeV3,
    ) -> Result<AgentdNeuronHandleV2, AgentdError> {
        let run = || -> HostResult<AgentdNeuronHandleV2> {
            let capability = self
                .resolver
                .as_ref()
                .map(|resolver| -> HostResult<_> {
                    Ok(resolver.resolve(
                        &model_identity(expected, &self.identity)?,
                        CpuNeuronModelUsePurposeV3::CurrentSelectedNewGoal,
                    )?)
                })
                .transpose()?;
            let original = capability.as_ref().map_or(&self.plan, |cap| &cap.plan);
            // The sole Agentd host validates the durable invocation before
            // calling this installed factory and still owns the final CAS.
            if identity.agent_id != self.identity.agent_id
                || identity.spawn_generation != self.identity.spawn_generation
                || identity.home_root != self.identity.home_root
                || stage.run_id != record.snapshot.run_id
                || stage.snapshot_digest != invocation.request.snapshot.digest()
                || stage.predecessor_digest.is_zero()
                || record.runtime_body_digest != original.body.semantic_digest()?
                || invocation.request.snapshot.body_generation() != original.runtime.generation
            {
                return Err("actual compiled Goal differs from the original physical owner".into());
            }
            // Verify the complete expected identity before constructing files.
            scope_plan(original, &self.identity, expected)?;
            let mut next = expected.clone();
            next.ordinal = next.ordinal.checked_add(1).ok_or("Goal ordinal overflow")?;
            next.identity.objective_digest = stage.objective_digest;
            self.open(
                &next,
                StoreRequirement::NewOrExisting,
                CpuNeuronModelUsePurposeV3::CurrentSelectedNewGoal,
            )
        };
        run().map_err(|error| {
            AgentdError::Invalid(format!("installed Goal scope unavailable: {error}"))
        })
    }
}

fn model_identity(
    scope: &AgentdNeuronGoalScopeV3,
    identity: &AgentdIdentity,
) -> HostResult<CpuNeuronModelIdentityV3> {
    Ok(CpuNeuronModelIdentityV3 {
        generation: Generation::new(scope.identity.model_generation)?,
        configuration_digest: scope.identity.runtime_configuration_digest,
        body_digest: scope.identity.body_bundle_digest,
        subject: id(identity.agent_id.as_str())?,
    })
}

fn scope_plan(
    original: &crate::CpuNeuronGenerationPlanV1,
    identity: &AgentdIdentity,
    scope: &AgentdNeuronGoalScopeV3,
) -> HostResult<crate::CpuNeuronGenerationPlanV1> {
    let mut plan = original.clone();
    let actual_scope = NeuronTickInputV1::journal_scope_for_subject(
        &id(identity.agent_id.as_str())?,
        scope.identity.objective_digest,
    )?;
    if scope.ordinal == 0
        || scope.identity.model_generation != plan.runtime.generation.get()
        || scope.identity.subject_scope_digest != actual_scope.scope_digest
        || scope.identity.runtime_configuration_digest != plan.runtime.semantic_digest()?
        || scope.identity.body_bundle_digest != plan.body.semantic_digest()?
    {
        return Err("Goal topology changed the immutable physical model/body/subject".into());
    }
    plan.scope = actual_scope;
    plan.store_context.scope = actual_scope;
    plan.index_context.scope = actual_scope;
    plan.witness_context.scope = actual_scope;
    if scope.ordinal > 1 {
        for path in [
            &mut plan.generation_store,
            &mut plan.runtime_index,
            &mut plan.witness,
        ] {
            let mut value = path.as_os_str().to_os_string();
            value.push(format!(".goal-{}", scope.ordinal));
            *path = PathBuf::from(value);
            if !path.starts_with(&identity.home_root) {
                return Err("Goal store escaped the original private home".into());
            }
            crate::evolving_agentd::private_parent(path)?;
        }
    }
    Ok(plan)
}
pub(super) fn mode(
    paths: [&Path; 3],
    requirement: StoreRequirement,
) -> HostResult<crate::CpuNeuronGenerationOpenModeV1> {
    let mut present = 0;
    for path in paths {
        match std::fs::symlink_metadata(path) {
            Ok(meta)
                if meta.is_file()
                    && !meta.file_type().is_symlink()
                    && meta.uid() == rustix::process::geteuid().as_raw()
                    && meta.nlink() == 1
                    && meta.mode() & 0o077 == 0 =>
            {
                present += 1
            }
            Ok(_) => return Err("Goal store is not an original private regular file".into()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => (),
            Err(error) => return Err(error.into()),
        }
    }
    match present {
        0 if matches!(requirement, StoreRequirement::NewOrExisting) => {
            Ok(crate::CpuNeuronGenerationOpenModeV1::Create)
        }
        3 => Ok(crate::CpuNeuronGenerationOpenModeV1::Recover),
        _ => Err("missing Goal stores require original owner reconciliation".into()),
    }
}

pub(super) fn prepare(
    source: &InstalledCpuSourceV1,
    installed: &installed_plan::Installed,
    identity: &AgentdIdentity,
    plan: crate::CpuNeuronGenerationPlanV1,
    control: Arc<
        tokio::sync::Mutex<codex_hepta_infer_core::durable_control::DurableInferenceControl>,
    >,
    clock: Arc<dyn AuthorityClock>,
    worker: crate::CpuNeuronControlConfigV2,
    tick: Arc<tick::TickProvider>,
) -> HostResult<(
    AgentdNeuronRuntimeV2Config,
    Option<Arc<dyn RegisteredCpuModelResolverV3>>,
    model_capability::CpuNeuronOriginalGenerationReaderV3,
)> {
    let pointer = installed
        .model_use_pointer
        .clone()
        .ok_or("installed model-use pointer")?;
    let descriptor = Source {
        path: source.path.clone(),
        digest: source.digest.clone(),
    };
    let descriptor_bytes = descriptor.read(32 * 1024)?;
    let fresh = || -> HostResult<AgentdNeuronGoalScopeV3> {
        Ok(AgentdNeuronGoalScopeV3 {
            ordinal: 1,
            identity: AgentdNeuronScopeIdentityV3 {
                model_generation: plan.runtime.generation.get(),
                subject_scope_digest: plan.scope.scope_digest,
                objective_digest: plan.scope.objective_digest,
                runtime_configuration_digest: plan.runtime.semantic_digest()?,
                body_bundle_digest: plan.body.semantic_digest()?,
            },
        })
    };
    let (active_scope, retained, requirement) =
        match std::fs::symlink_metadata(&installed.control_state_path) {
            Ok(meta) if meta.is_file() && !meta.file_type().is_symlink() => {
                let state =
                    read_agentd_neuron_live_goal_scope_state_v3(&installed.control_state_path)?;
                let mut retained = state.retained_scopes;
                let active = if let Some(target) = state.reload_target_scope {
                    // The original controller resolves its persisted Reloading
                    // intent only after authenticating both exact native headers.
                    retained.push(state.active_scope);
                    target
                } else {
                    state.active_scope
                };
                (active, retained, StoreRequirement::Existing)
            }
            Ok(_) => return Err("Goal control state is not an original regular file".into()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                (fresh()?, Vec::new(), StoreRequirement::NewOrExisting)
            }
            Err(error) => return Err(error.into()),
        };
    // The existing model owner already opened control. Only one physical model
    // is loaded, then shared by active and bounded retained Goal handles.
    let physical = crate::CpuNeuronInferenceControlV1::open_shared_v2(
        control,
        clock.clone(),
        &plan.model_manifest,
        plan.model_manifest_digest,
        worker,
    )?;
    let admission = match &installed.registered_bootstrap {
        Some(bootstrap) => bootstrap.admission.clone(),
        None => model_capability::Admission::Initial(model_use_current::Admission::open(
            pointer,
            &plan,
            identity,
            clock.clone(),
        )?),
    };
    let physical = crate::SharedCpuNeuronInferenceControlV3::new(physical);
    let original_generations = model_capability::CpuNeuronOriginalGenerationReaderV3::default();
    let resolver: Option<Arc<dyn RegisteredCpuModelResolverV3>> = match &installed.model_registry {
        Some(registry) => {
            let (weights, installation) = match &installed.registered_bootstrap {
                Some(bootstrap) => (bootstrap.weights.clone(), bootstrap.installation.clone()),
                None => {
                    let verified = model_use_current::inspect_current(
                        installed
                            .model_use_pointer
                            .as_ref()
                            .ok_or("registered model-use pointer")?,
                    )?;
                    (
                        verified.installed_inputs().profile.weights.clone(),
                        Source {
                            path: source.path.clone(),
                            digest: source.digest.clone(),
                        },
                    )
                }
            };
            Some(Arc::new(model_capability::ProtectedReader::open(
                registry.clone(),
                identity.clone(),
                clock,
                model_capability::CpuNeuronModelCapabilityV3 {
                    identity: model_identity(&fresh()?, identity)?,
                    installation,
                    plan: plan.clone(),
                    admission: admission.clone(),
                    physical: physical.clone(),
                    tick: tick.clone(),
                    weights,
                },
                original_generations.clone(),
            )?) as Arc<dyn RegisteredCpuModelResolverV3>)
        }
        None => None,
    };
    let runtime_tick: Arc<dyn AgentdNeuronTickProviderV2> = match &resolver {
        Some(resolver) => Arc::new(model_adapters::Tick {
            resolver: resolver.clone(),
        }),
        None => tick,
    };
    let factory = Arc::new(Factory {
        descriptor,
        descriptor_bytes,
        identity: identity.clone(),
        plan,
        admission,
        physical,
        resolver: resolver.clone(),
    });
    let purpose = match requirement {
        StoreRequirement::NewOrExisting => CpuNeuronModelUsePurposeV3::CurrentSelectedNewGoal,
        StoreRequirement::Existing => CpuNeuronModelUsePurposeV3::HistoricalRecovery,
    };
    let active = factory.open(&active_scope, requirement, purpose)?;
    let mut runtime = AgentdNeuronRuntimeV2Config::new(
        active,
        installed.control_state_path.clone(),
        runtime_tick,
    )?
    .with_goal_scope_factory_v3(active_scope, factory.clone())?;
    for scope in retained {
        let handle = factory.open(
            &scope,
            StoreRequirement::Existing,
            CpuNeuronModelUsePurposeV3::HistoricalRecovery,
        )?;
        runtime = runtime.with_retained_goal_scope_v3(scope, handle)?;
    }
    factory.verify_descriptor()?;
    Ok((runtime, resolver, original_generations))
}

#[cfg(test)]
#[path = "initial_cpu_goal_factory_v3_tests.rs"]
mod tests;
