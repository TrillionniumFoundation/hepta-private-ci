//! Real Fleet/config assembly with an explicit synthetic proposal fixture.
//! This tests the installed owner path, not trained-model accuracy or adoption.

use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_neuron::CellGenerationConfigV2;
use codex_hepta_neuron::CellGenerationControlPortV2;
use codex_hepta_neuron::CellGenerationDispositionV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationProposalV2;
use codex_hepta_neuron::CellGenerationRequestV2;
use codex_hepta_neuron::CellRuntimeSnapshotV2;
use codex_hepta_neuron::CellTaskCostIdentityV2;
use codex_hepta_neuron::CellTaskCostV2;
use tokio_util::sync::CancellationToken;

use super::super::support as host;
use crate::AgentdConfig;
use crate::AgentdGenerationUpdateRuntimeV1;
use crate::RuntimeTasks;
use crate::neuron_generation_service::spawn_neuron_generation_service;

pub(super) const OUTPUT: &[u8] = b"synthetic successor task";

#[derive(Clone, Default)]
pub(super) struct Control {
    pub(super) executions: Arc<AtomicUsize>,
    pub(super) reads: Arc<AtomicUsize>,
    result: Option<CellGenerationProposalV2>,
}

impl CellGenerationControlPortV2 for Control {
    fn execute_generation(
        &mut self,
        manifest: &CellBackendManifestV2,
        request: &CellGenerationRequestV2,
    ) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
        self.executions.fetch_add(1, Ordering::SeqCst);
        let proposal = CellGenerationProposalV2 {
            request_digest: request.digest()?,
            bundle_digest: manifest.bundle_digest,
            runtime_digest: manifest.runtime_digest,
            device_digest: manifest.device_digest,
            successor_state: request.input.clone(),
            output_delta: OUTPUT.to_vec(),
            disposition: CellGenerationDispositionV2::Stopped,
            // No fixture counter is presented as a measured physical cost.
            cost: CellTaskCostV2::new(CellTaskCostIdentityV2 {
                task_digest: request.task_digest,
                source_digest: manifest.source_digest,
            })
            .map_err(|_| CellGenerationErrorV2::InvalidBinding)?,
        };
        self.result = Some(proposal.clone());
        Ok(proposal)
    }

    fn read_generation(
        &mut self,
        request: &CellGenerationRequestV2,
    ) -> Result<Option<CellGenerationProposalV2>, CellGenerationErrorV2> {
        self.reads.fetch_add(1, Ordering::SeqCst);
        let digest = request.digest()?;
        Ok(self
            .result
            .as_ref()
            .filter(|result| result.request_digest == digest)
            .cloned())
    }

    fn cancel_generation(
        &mut self,
        _request: &CellGenerationRequestV2,
    ) -> Result<(), CellGenerationErrorV2> {
        Ok(())
    }
}

pub(super) fn request(
    config: &CellGenerationConfigV2,
    predecessor: CellRuntimeSnapshotV2,
) -> CellGenerationRequestV2 {
    CellGenerationRequestV2 {
        operation_id: "new-task-stop".into(),
        task_digest: config.task_digest,
        source_frontier: config.source_frontier,
        predecessor,
        input: vec![5, 6],
        admitted_at_micros: 10,
        deadline_micros: 10_000,
    }
}

pub(super) async fn next_config(
    fixture: &mut host::Fixture,
    running_generation: u64,
) -> anyhow::Result<AgentdConfig> {
    fixture.registry.compare_and_transition(
        &fixture.identity.agent_id,
        running_generation,
        AgentLifecycle::Draining,
    )?;
    fixture.state().refresh_generation()?;
    fixture.state().mark_draining()?;
    fixture.registry.compare_and_transition(
        &fixture.identity.agent_id,
        running_generation + 1,
        AgentLifecycle::Stopped,
    )?;
    fixture.registry.compare_and_transition(
        &fixture.identity.agent_id,
        running_generation + 2,
        AgentLifecycle::Starting,
    )?;
    fixture.identity.spawn_generation = running_generation + 3;
    let identity = &fixture.identity;
    let config = AgentdConfig::load(
        identity.fleet_root.clone(),
        identity.agent_id.clone(),
        identity.spawn_generation,
        identity.home_root.clone(),
        identity.run_root.clone(),
        identity.home_root.clone(),
        identity.workspace.clone(),
    )?;
    fixture.reopen_state().await;
    fixture.registry.compare_and_transition(
        &fixture.identity.agent_id,
        running_generation + 3,
        AgentLifecycle::Running,
    )?;
    fixture.state().refresh_generation()?;
    Ok(config)
}

pub(super) fn start(
    runtime: &mut AgentdGenerationUpdateRuntimeV1,
    fixture: &host::Fixture,
) -> anyhow::Result<(RuntimeTasks, CancellationToken)> {
    let bootstrap = runtime
        .config
        .take_neuron_generation_bootstrap()
        .ok_or_else(|| anyhow::anyhow!("updated normal config has no generation service"))?;
    let (mut tasks, cancellation) = host::host();
    spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        cancellation.clone(),
    )?;
    Ok((tasks, cancellation))
}
