//! Attach the admitted physical owner to ordinary Agentd, borrowing the model
//! owner's single native journal. Missing current inputs leave LLM service up.
use super::*;
use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::AgentdDurableCpuAbstainInvocationProviderV2;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdIdentity;
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
    provider: Arc<AgentdDurableCpuAbstainInvocationProviderV2>,
}

impl Composition {
    pub(crate) fn prepare(
        source: &InstalledCpuSourceV1,
        identity: &AgentdIdentity,
        authority_config: &Path,
        control: Arc<tokio::sync::Mutex<DurableInferenceControl>>,
    ) -> HostResult<Self> {
        let clock = Arc::new(SystemAuthorityClock);
        let (installed, plan, mode) = installed_plan::load(source, identity, clock.clone())?;
        // Execution identity comes from the original protected Fleet launch,
        // and is independently checked against the real kernel peer by its owner.
        let execution = std::env::var("HEPTA_FLEET_EXECUTION_ID")?;
        let resources = Arc::new(
            crate::FleetWorkerResourcePortV2::open(
                authority_config,
                identity,
                execution,
                digest(&installed.fleet_manifest_digest)?,
            )
            .map_err(|error| error.to_string())?,
        );
        let goal_mode = installed.model_use_pointer.is_some();
        let tick = Arc::new(tick::TickProvider::open_mode(
            installed.tick_provider.clone(),
            &plan,
            if goal_mode {
                tick::GoalMode::ActualCompiledGoal
            } else {
                tick::GoalMode::FixedObjective
            },
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
        let provider = Arc::new(AgentdDurableCpuAbstainInvocationProviderV2::new(
            installed.authority_file.clone(),
            verifier,
            native,
            runtime_digest,
            body_digest,
        )?);
        let model_generation = plan.runtime.generation;
        let worker = crate::CpuNeuronControlConfigV2 {
            resources,
            model_generation,
            maximum_request_duration: Duration::from_millis(installed.maximum_request_duration_ms),
        };
        let runtime = if goal_mode {
            goal_factory::prepare(
                source, &installed, identity, plan, control, clock, worker, tick,
            )?
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
        })
    }

    pub(crate) fn attach(self, config: AgentdConfig) -> Result<AgentdConfig, AgentdError> {
        config
            .with_neuron_runtime_v2(self.runtime)?
            .with_intelligence_product_runner(self.runner)?
            .with_intelligence_invocation_provider(self.provider)
    }
}
