//! Reopen the same files and original admission; no new fixture signature or
//! source publication is produced by these recovery helpers.

use std::fs::File;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use crate::AgentdConfig;
use crate::CircuitCellRegistryV1;
use crate::CircuitFeaturePredecessorFilesV1;
use crate::CircuitQ24TaskFilesV1;
use crate::CircuitQ24TaskOpenModeV1;
use crate::CircuitQ24TaskProfileV1;
use crate::CircuitTaskSourceInputV1;
use crate::DurableCircuitTaskSourceV1;
use crate::LoadedCellQ24ModelV1;
use crate::PublishedCircuitFeatureTaskV1;

use super::*;

pub(super) fn file(identity: &AgentdIdentity, name: &str) -> anyhow::Result<File> {
    Ok(OpenOptions::new().read(true).write(true).open(identity.home_root.join(name))?)
}

fn witness(identity: &AgentdIdentity, source: &CircuitTaskSourceInputV1, name: &str, label: &str) -> anyhow::Result<FileAnchorWitnessStore> {
    Ok(FileAnchorWitnessStore::open(file(identity, name)?, JournalScope {
        scope_digest: cell::d(label), objective_digest: source.objective_digest,
    }, Generation::new(1)?, /*max_records*/ 64)?)
}

fn registry(definition: &CellDefinitionV1) -> anyhow::Result<CircuitCellRegistryV1> {
    let (mut circuit, mut bindings) = super::super::super::configuration();
    bindings[0].cell = definition.clone();
    circuit.parameter_bundle_digest = Sha256Digest::parse(definition.bundle_digest.to_string())
        .map_err(anyhow::Error::msg)?;
    circuit.route_policy_digest = crate::circuit_cell_route_policy_digest_v1(&bindings)?;
    circuit.limits.work_budget = 20_000_000;
    circuit.limits.max_elapsed_ms = 60_000;
    circuit.programs[0].nodes[0].kind = CircuitNodeKindV2::Decide { max_work: 10_000_000 };
    Ok(CircuitCellRegistryV1::new(circuit, bindings)?)
}

pub(super) fn fence(identity: &AgentdIdentity) -> anyhow::Result<TaskFlowFence> {
    Ok(TaskFlowFence::new(identity.agent_id.clone(), "ordinary-q24-owner", /*owner_epoch*/ 1,
        identity.spawn_generation + 1, "ordinary-q24-fence")?)
}

pub(super) fn original_source(identity: &AgentdIdentity, definition: &CellDefinitionV1, source: &CircuitTaskSourceInputV1)
    -> anyhow::Result<DurableCircuitTaskSourceV1<FileAnchorWitnessStore>> {
    Ok(DurableCircuitTaskSourceV1::recover(file(identity, "q24-source.journal")?,
        witness(identity, source, "q24-source.witness", "original-source-owner")?, identity,
        &fence(identity)?, &registry(definition)?, vec![source.clone()])?)
}

pub(super) fn predecessor(identity: &AgentdIdentity, definition: &CellDefinitionV1, source: &CircuitTaskSourceInputV1,
    manifest: &CellBackendManifestV2) -> anyhow::Result<CircuitFeaturePredecessorFilesV1<FileAnchorWitnessStore>> {
    Ok(CircuitFeaturePredecessorFilesV1 { file: file(identity, "q24-cell.journal")?,
        witness: witness(identity, source, "q24-cell.witness", "original-cell-owner")?,
        definition: definition.clone(), source: source.clone(), manifest: manifest.clone(), maximum_records: 16 })
}

pub(super) struct Reopened {
    pub runtime: RuntimeFixture,
    pub request: AuthBusObjectiveIngress,
    pub source: Arc<crate::CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>>,
    pub cell: crate::PublishedCircuitCellOwnerV1<FileAnchorWitnessStore>,
    cancellation: CancellationToken,
    worker: Option<tokio::task::JoinHandle<Result<(), crate::AgentdError>>>,
}
impl Reopened {
    pub async fn stop(&mut self) -> anyhow::Result<()> {
        self.cancellation.cancel();
        if let Some(worker) = self.worker.take() { timeout(Duration::from_secs(5), worker).await???; }
        Ok(())
    }
}
impl Drop for Reopened { fn drop(&mut self) { self.cancellation.cancel(); } }

pub(super) async fn reopen(identity: AgentdIdentity, directory: tempfile::TempDir, request: AuthBusObjectiveIngress, config: AgentdConfig,
    published_task: PublishedCircuitFeatureTaskV1, model: Arc<LoadedCellQ24ModelV1>, bundle: CellCompatibilityBundleV1)
    -> anyhow::Result<Reopened> {
    let registry = FleetRegistry::open_existing(HeptaFleetRoot::parse(identity.fleet_root.clone())?)?;
    let state = Arc::new(AgentdState::new(identity.clone(), registry.clone(), EVENT_CAPACITY)?);
    let runtime = RuntimeFixture { identity, state, registry, _temp: directory };
    attach_runtime_prerequisites(&runtime).await;
    runtime.state.refresh_generation()?;
    runtime.state.mark_app_server_ready()?;
    let identity = &runtime.identity;
    let ingress = crate::authbus_ingress::TextIngress::open(identity, identity.home_root.join("circuit-trust.json"),
        identity.run_root.join("circuit-checkpoint.json")).await?;
    assert!(runtime.state.authbus.set(Arc::new(ingress)).is_ok());
    let host = crate::objective_runtime::ObjectiveRuntimeHost::open(identity, &identity.home_root.join("circuit-profile.json"))?;
    assert!(runtime.state.objective_runtime.set(Arc::new(host)).is_ok());
    let source = published_task.source().clone();
    let circuit = self::registry(published_task.definition())?;
    let (_, bindings) = super::super::super::configuration();
    let cell_deadline = source.deadline_micros;
    let profile = CircuitQ24TaskProfileV1 {
        files: CircuitQ24TaskFilesV1 {
            source_journal: file(identity, "q24-source.journal")?, source_witness: witness(identity, &source, "q24-source.witness", "original-source-owner")?,
            cell_journal: file(identity, "q24-cell.journal")?, cell_witness: witness(identity, &source, "q24-cell.witness", "original-cell-owner")?,
            inference_control: DurableInferenceControl::open(identity.home_root.join("q24-control.journal"), /*capacity*/ 4)?,
        },
        source_mode: CircuitQ24TaskOpenModeV1::Recover, published_task,
        fence: fence(identity)?, circuit: circuit.definition().clone(), routes: bindings[0].routes.clone(),
        bundle, model, worker_generation: 1, maximum_cell_records: 16, queue_capacity: 4,
        // Advancing past the original Cell deadline must still read completed
        // work; it cannot authorize a new dispatch or recalculate its costs.
        clock: Arc::new(move || crate::CircuitCellTimeV1 {
            circuit_millis: crate::authbus_ingress::now_ms().expect("wall clock"), cell_micros: cell_deadline + 1,
        }),
    };
    // The original validated configuration contains no handed-off bootstrap or
    // owner. This same-generation mechanism test must not reload Starting-only
    // config on an already Running Fleet or invent a lifecycle transition.
    let mut installed = config.with_q24_circuit_task_profile(profile)?;
    let (bootstrap, invocation) = installed.config.take_circuit_task_bootstrap()?.expect("recovered ordinary profile");
    runtime.state.attach_automation_store(AutomationStore::open(&identity.layout).await?)?;
    assert!(runtime.state.circuit_task.set(bootstrap.handle()).is_ok());
    assert!(runtime.state.circuit_task_invocation.set(invocation).is_ok());
    let cancellation = CancellationToken::new();
    let worker = tokio::spawn(bootstrap.run(Arc::clone(&runtime.state), cancellation.clone()));
    Ok(Reopened { runtime, request, source: installed.source, cell: installed.cell, cancellation, worker: Some(worker) })
}
