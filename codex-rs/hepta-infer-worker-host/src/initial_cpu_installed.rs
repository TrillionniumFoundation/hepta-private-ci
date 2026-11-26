//! Attach the admitted physical owner to ordinary Agentd, borrowing the model
//! owner's single native journal. Missing current inputs leave LLM service up.
use super::*;
use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::AgentdDurableCpuAbstainInvocationProviderV2;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdIdentity;
use codex_hepta_agentd::AgentdIntelligenceInvocationProviderV1;
use codex_hepta_agentd::AgentdIntelligenceProductRunnerV1;
use codex_hepta_agentd::AgentdNeuronRuntimeV2Config;
use codex_hepta_agentd::IntelligenceAuthorityVerifierV1;
use codex_hepta_contracts::SystemAuthorityClock;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use std::sync::Arc;
use std::time::Duration;

pub(crate) struct Composition {
    runtime: AgentdNeuronRuntimeV2Config,
    runner: Arc<AgentdIntelligenceProductRunnerV1>,
    provider: Arc<dyn AgentdIntelligenceInvocationProviderV1>,
    resolver: Option<Arc<dyn goal_factory::model_capability::RegisteredCpuModelResolverV3>>,
    original_generations: goal_factory::model_capability::CpuNeuronOriginalGenerationReaderV3,
}

impl Composition {
    pub(crate) fn prepare(
        source: &InstalledCpuSourceV1,
        identity: &AgentdIdentity,
        authority_config: &Path,
        control: Arc<tokio::sync::Mutex<DurableInferenceControl>>,
    ) -> HostResult<Self> {
        let clock = Arc::new(SystemAuthorityClock);
        let (installed, plan, mode, launch_digest) =
            installed_plan::load(source, identity, clock.clone())?;
        // Execution identity comes from the original protected Fleet launch,
        // and is independently checked against the real kernel peer by its owner.
        let execution = std::env::var("HEPTA_FLEET_EXECUTION_ID")?;
        let resources = Arc::new(
            crate::FleetWorkerResourcePortV2::open(
                authority_config,
                identity,
                execution,
                launch_digest,
            )
            .map_err(|error| error.to_string())?,
        );
        let goal_mode = installed.model_use_pointer.is_some();
        let mut inactive_admission = None;
        let tick_mode = if let Some(bootstrap) = &installed.registered_bootstrap {
            tick::GoalMode::ActualCompiledGoal {
                encoder_manifest_digest: bootstrap.plan.runtime.encoder_digest,
                tokenizer_digest: bootstrap.plan.runtime.tokenizer_digest,
            }
        } else if let Some(pointer) = installed.model_use_pointer.as_ref() {
            let admission = model_use_current::Admission::open(
                pointer.clone(),
                &plan,
                identity,
                clock.clone(),
            )?;
            let binding = admission.binding();
            let mode = tick::GoalMode::ActualCompiledGoal {
                encoder_manifest_digest: binding.encoder_manifest_digest,
                tokenizer_digest: binding.tokenizer_digest,
            };
            inactive_admission = Some(admission);
            mode
        } else {
            tick::GoalMode::FixedObjective
        };
        let tick = Arc::new(tick::TickProvider::open_mode(
            installed.registered_bootstrap.as_ref().map_or_else(
                || installed.tick_provider.clone(),
                |bootstrap| bootstrap.tick_provider.clone(),
            ),
            &plan,
            tick_mode,
        )?);
        let runtime_digest = plan.runtime.semantic_digest()?;
        let body_digest = plan.body.semantic_digest()?;
        let native = plan.native.clone();
        let verifier = IntelligenceAuthorityVerifierV1 {
            signer_id: installed.authority_signer_id.clone(),
            verifying_key: public(&installed.authority_verifying_key_hex)?,
        };
        // Validate composition before creating any first physical stores.
        let runner = Arc::new(AgentdIntelligenceProductRunnerV1::new(
            installed.authority_file.clone(),
            verifier.clone(),
        )?);
        let mut provider = AgentdDurableCpuAbstainInvocationProviderV2::new(
            installed.authority_file.clone(),
            verifier.clone(),
            native,
            runtime_digest,
            body_digest,
        )?;
        if let Some(admission) = inactive_admission {
            let subject = id(identity.agent_id.as_str())?;
            // Validate now, then borrow this same CURRENT reader on each Goal.
            admission.inactive_state(subject.clone())?;
            provider = provider.with_current_inactive_state(Arc::new(move || {
                admission.inactive_state(subject.clone()).map_err(|error| {
                    AgentdError::Invalid(format!("current inactive CPU state: {error}"))
                })
            }));
        }
        let mut provider: Arc<dyn AgentdIntelligenceInvocationProviderV1> = Arc::new(provider);
        let model_generation = plan.runtime.generation;
        let worker = crate::CpuNeuronControlConfigV2 {
            resources,
            model_generation,
            maximum_request_duration: Duration::from_millis(installed.maximum_request_duration_ms),
        };
        let mut installed_resolver = None;
        let mut original_generations =
            goal_factory::model_capability::CpuNeuronOriginalGenerationReaderV3::default();
        let runtime = if goal_mode {
            let (runtime, resolver, reader) = goal_factory::prepare(
                source, &installed, identity, plan, control, clock, worker, tick,
            )?;
            original_generations = reader;
            installed_resolver = resolver.clone();
            if let Some(resolver) = resolver {
                provider = Arc::new(goal_factory::model_adapters::Provider {
                    authority_file: installed.authority_file.clone(),
                    verifier,
                    resolver,
                });
            }
            runtime
        } else {
            let handle = open_current_cpu_neuron_v2(
                installed.current_pointer,
                plan,
                mode,
                control,
                clock,
                worker,
            )?;
            if handle.configuration_digest() != runtime_digest
                || handle.body_bundle_digest() != Some(body_digest)
            {
                return Err("actual CPU handle differs from verified composition".into());
            }
            AgentdNeuronRuntimeV2Config::new(handle, installed.control_state_path, tick)?
        };
        Ok(Self {
            runtime,
            runner,
            provider,
            resolver: installed_resolver,
            original_generations,
        })
    }

    pub(crate) fn model_resolver(
        &self,
    ) -> Option<Arc<dyn goal_factory::model_capability::RegisteredCpuModelResolverV3>> {
        self.resolver.clone()
    }

    pub(crate) fn original_generation_reader(
        &self,
    ) -> goal_factory::model_capability::CpuNeuronOriginalGenerationReaderV3 {
        self.original_generations.clone()
    }

    pub(crate) fn attach(self, config: AgentdConfig) -> Result<AgentdConfig, AgentdError> {
        config
            .with_neuron_runtime_v2(self.runtime)?
            .with_intelligence_product_runner(self.runner)?
            .with_intelligence_invocation_provider(self.provider)
    }
}
