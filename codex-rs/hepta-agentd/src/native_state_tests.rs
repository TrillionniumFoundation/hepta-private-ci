//! Native control-boundary tests using the real Fleet registry, coordinator,
//! and readiness store. No provider, runtime process, or effect grant is faked.

use std::fs;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;

use anyhow::Context;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_memory::ProductionDispatchRequest;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

use super::native::NativeEntryGate;
use super::*;
use crate::ContextAttachment;
use crate::RunPhase;
use crate::RunSnapshot;

struct Fixture {
    state: Arc<AgentdState>,
    registry: FleetRegistry,
    _temp: tempfile::TempDir,
}

fn fixture() -> anyhow::Result<Fixture> {
    let temp = tempfile::tempdir().context("temporary owner")?;
    let root = temp.path().canonicalize().context("canonical root")?;
    #[cfg(unix)]
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).context("private root")?;
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).context("fleet root")?;
    let registry = FleetRegistry::initialize(fleet_root.clone()).context("real registry")?;
    let workspace = root.join("workspace");
    fs::create_dir(&workspace).context("workspace")?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").context("agent id")?;
    let manifest = AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet_root).context("workspace binding")?,
        ResourceBudget::local_default(),
    )
    .context("manifest")?;
    let record = registry.register(manifest).context("register owner")?;
    registry
        .compare_and_transition(&agent_id, /*expected_generation*/ 0, AgentLifecycle::Starting)
        .context("starting generation")?;
    let identity = AgentdIdentity {
        agent_id,
        layout: record.layout.clone(),
        spawn_generation: 1,
        fleet_root: fleet_path,
        workspace,
        resources: record.manifest.resources,
        home_root: record.layout.home_root().to_path_buf(),
        run_root: record.layout.run_root().to_path_buf(),
        control_socket: record.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: record.layout.app_server_socket().to_path_buf(),
    };
    let state = Arc::new(
        AgentdState::new(identity, registry.clone(), /*event_capacity*/ 16).context("real Agentd state")?,
    );
    registry
        .compare_and_transition(&state.identity.agent_id, /*expected_generation*/ 1, AgentLifecycle::Running)
        .context("running generation")?;
    state.refresh_generation().context("refresh running owner")?;
    Ok(Fixture { state, registry, _temp: temp })
}

async fn attach_store(state: &AgentdState) -> anyhow::Result<()> {
    let store = CognitiveStore::open(&state.identity.layout).await.context("real cognitive store")?;
    state.attach_cognitive_store(Arc::new(store)).context("attach original store")?;
    state.mark_runtime_prerequisites_ready().context("freeze readiness prerequisites")?;
    Ok(())
}

fn attached_run(state: &AgentdState, run_id: &str, deadline_ms: u64) -> anyhow::Result<RunReceipt> {
    let generation = state.current_generation().context("current fleet generation")?;
    let snapshot = RunSnapshot {
        run_id: run_id.to_owned(),
        request_digest: "1".repeat(64),
        objective_digest: "2".repeat(64),
        body_digest: "3".repeat(64),
        artifact_set_digest: "4".repeat(64),
        authority_epoch: 7,
        generation,
        fence_digest: objective_run_fence(&state.identity, generation),
        deadline_ms,
    };
    // Use the actual coordinator. A deterministic past admission time permits
    // testing that the native physical-entry path independently checks expiry.
    let mut runs = state.runs.lock().map_err(poisoned_state).context("original coordinator")?;
    let admitted = runs.start_run(/*now_ms*/ 1, snapshot.clone()).map_err(run_error).context("original admission")?;
    runs.attach_context(/*now_ms*/ 1, admitted.revision, ContextAttachment {
        run_id: snapshot.run_id,
        request_digest: snapshot.request_digest,
        objective_digest: snapshot.objective_digest,
        body_digest: snapshot.body_digest,
        artifact_set_digest: snapshot.artifact_set_digest,
        authority_epoch: snapshot.authority_epoch,
        generation: snapshot.generation,
        fence_digest: snapshot.fence_digest,
        deadline_ms: snapshot.deadline_ms,
        context_digest: "5".repeat(64),
        compilation_receipt_digest: "6".repeat(64),
    }).map_err(run_error).context("original context attachment")
}

#[tokio::test]
async fn native_dispatch_requires_real_store_and_running_port_readiness() {
    let fixture = fixture().expect("real owner fixture");
    let state = &fixture.state;
    let original = attached_run(state, "run.native.readiness", u64::MAX - 1).expect("original context attachment");
    assert!(state.dispatch_native_run(&original).is_err());
    state.mark_runtime_prerequisites_ready().expect("no store cannot establish readiness");
    assert!(state.dispatch_native_run(&original).is_err());
    attach_store(state).await.expect("attach original readiness store");
    assert!(state.dispatch_native_run(&original).is_err(), "store alone is insufficient");
    assert_eq!(state.native_run_receipt(&original.run_id).expect("original remains"), original);
    state.mark_app_server_ready().expect("actual host port readiness");
    let _active = state.dispatch_native_run(&original).expect("all original prerequisites ready");
    assert_eq!(
        state.require_native_effect(&original.run_id).expect("current effect gate"),
        state.native_run_receipt(&original.run_id).expect("same original coordinator receipt")
    );
}

#[tokio::test]
async fn exact_context_receipt_dispatches_once_and_active_guard_tracks_the_turn() {
    let fixture = fixture().expect("real owner fixture");
    let state = &fixture.state;
    attach_store(state).await.expect("attach original readiness store");
    state.mark_app_server_ready().expect("port ready");
    let original = attached_run(state, "run.native.once", u64::MAX - 1).expect("original context attachment");
    let mut substituted = original.clone();
    substituted.compilation_receipt_digest = Some("7".repeat(64));
    assert!(state.dispatch_native_run(&substituted).is_err());
    assert_eq!(state.native_run_receipt(&original.run_id).expect("unchanged"), original);
    let active = state.dispatch_native_run(&original).expect("consume exact handoff");
    assert!(state.dispatch_native_run(&original).is_err(), "old handoff cannot redispatch");
    let dispatched = state.require_native_effect(&original.run_id).expect("live dispatch");
    assert_eq!((dispatched.phase, dispatched.revision), (RunPhase::Dispatched, original.revision + 1));
    assert_eq!(state.drain_snapshot(/*automation_blockers*/ 0).expect("active snapshot").running_turns, 1);
    drop(active);
    assert_eq!(state.drain_snapshot(/*automation_blockers*/ 0).expect("guard released").running_turns, 0);
    assert_eq!(state.unresolved_run_count().expect("original not implicitly settled"), 1);
}

#[tokio::test]
async fn control_cancellation_blocks_native_entry_but_preserves_original_observation() {
    let fixture = fixture().expect("real owner fixture");
    let state = &fixture.state;
    attach_store(state).await.expect("attach original readiness store");
    state.mark_app_server_ready().expect("port ready");
    let original = attached_run(state, "run.native.cancel", u64::MAX - 1).expect("original context attachment");
    let active = state.dispatch_native_run(&original).expect("original dispatch");
    let dispatched = state.native_run_receipt(&original.run_id).expect("dispatched");
    state.response(/*request_id*/ 1, /*spawn_generation*/ 1, crate::AgentdMethod::RunCancel {
        run_id: original.run_id.clone(),
        expected_revision: dispatched.revision,
        reason: "user_cancel".to_owned(),
    }).await.expect("cancel through the existing control owner");
    assert!(state.require_native_effect(&original.run_id).is_err());
    let cancelling = state.native_run_receipt(&original.run_id).expect("original retained");
    assert_eq!((cancelling.phase, cancelling.cancel_reason.as_deref()), (RunPhase::Cancelling, Some("user_cancel")));
    let recovery = state.track_native_recovery(&original.run_id).expect("observe unresolved original");
    let unknown = state.observe_native_run(&original.run_id, RunPhase::Indeterminate).expect("ack is not terminal");
    assert!(!unknown.terminal_observed);
    assert!(state.dispatch_native_run(&unknown).is_err());
    assert!(state.require_native_effect(&original.run_id).is_err());
    // A real original effect may complete after cancellation; observation is
    // allowed, while this test never fabricates a fresh dispatch permission.
    let terminal = state.observe_native_run(&original.run_id, RunPhase::Succeeded).expect("original terminal observation");
    assert!(terminal.terminal_observed);
    assert!(state.track_native_recovery(&original.run_id).is_err());
    drop(recovery);
    drop(active);
    assert_eq!(state.unresolved_run_count().expect("original reconciled"), 0);
}

#[tokio::test]
async fn fleet_drain_keeps_native_turn_and_unknown_operation_as_separate_blockers() {
    let fixture = fixture().expect("real owner fixture");
    let state = &fixture.state;
    attach_store(state).await.expect("attach original readiness store");
    state.mark_app_server_ready().expect("port ready");
    let original = attached_run(state, "run.native.drain", u64::MAX - 1).expect("original context attachment");
    let active = state.dispatch_native_run(&original).expect("original dispatch");
    fixture.registry.compare_and_transition(&state.identity.agent_id, /*expected_generation*/ 2, AgentLifecycle::Draining)
        .expect("supervisor begins drain");
    state.mark_draining().expect("local ingress closes");
    assert!(state.require_native_effect(&original.run_id).is_err());
    let snapshot = state.drain_snapshot(/*automation_blockers*/ 0).expect("draining snapshot");
    assert_eq!((snapshot.admission_closed, snapshot.running_turns, snapshot.drained), (true, 1, false));
    drop(active);
    let snapshot = state.drain_snapshot(/*automation_blockers*/ 0).expect("observer task left");
    assert_eq!((snapshot.running_turns, snapshot.drained), (0, false));
    assert_eq!(state.unresolved_run_count().expect("unknown original still blocks"), 1);
    let recovery = state.track_native_recovery(&original.run_id).expect("read-only original recovery");
    state.observe_native_run(&original.run_id, RunPhase::Cancelled).expect("original terminal cancel observed");
    assert_eq!(state.drain_snapshot(/*automation_blockers*/ 0).expect("recovery still active").running_turns, 1);
    drop(recovery);
    assert_eq!(state.unresolved_run_count().expect("terminal reconciled"), 0);
    // App Server drainage has its own real worker acknowledgement; no test
    // mutates its flag to manufacture a globally drained host.
}

#[tokio::test]
async fn replaced_fleet_generation_fences_old_entry_without_losing_unknown_run() {
    let fixture = fixture().expect("real owner fixture");
    let state = &fixture.state;
    attach_store(state).await.expect("attach original readiness store");
    state.mark_app_server_ready().expect("port ready");
    let original = attached_run(state, "run.native.replaced", u64::MAX - 1).expect("original context attachment");
    let active = state.dispatch_native_run(&original).expect("original dispatch");
    fixture.registry.compare_and_transition(&state.identity.agent_id, /*expected_generation*/ 2, AgentLifecycle::Draining)
        .expect("supervisor drain");
    fixture.registry.compare_and_transition(&state.identity.agent_id, /*expected_generation*/ 3, AgentLifecycle::Stopped)
        .expect("supervisor replacement boundary");
    assert!(state.require_native_effect(&original.run_id).is_err());
    assert!(state.is_fenced().expect("old owner remains fenced"));
    let retained = state.native_run_receipt(&original.run_id).expect("unknown original retained");
    assert_eq!((retained.generation, retained.phase, retained.terminal_observed), (original.generation, RunPhase::Indeterminate, false));
    assert!(state.dispatch_native_run(&retained).is_err());
    let observation = state.track_native_recovery(&original.run_id).expect("recovery is not a new grant");
    state.observe_native_run(&original.run_id, RunPhase::Succeeded).expect("late original observation");
    assert!(state.require_native_effect(&original.run_id).is_err());
    drop(observation);
    drop(active);
}

#[tokio::test]
async fn expired_original_context_cannot_be_dispatched_and_does_not_gain_an_active_guard() {
    let fixture = fixture().expect("real owner fixture");
    let state = &fixture.state;
    attach_store(state).await.expect("attach original readiness store");
    state.mark_app_server_ready().expect("port ready");
    let original = attached_run(state, "run.native.expired", /*deadline_ms*/ 2).expect("original context attachment");
    assert!(state.dispatch_native_run(&original).is_err());
    assert!(state.require_native_effect(&original.run_id).is_err());
    assert_eq!(state.native_run_receipt(&original.run_id).expect("original retained"), original);
    assert_eq!(state.drain_snapshot(/*automation_blockers*/ 0).expect("no active task").running_turns, 0);
}

#[tokio::test]
async fn final_gate_checks_the_live_original_run_and_policy_without_minting_authority() {
    let fixture = fixture().expect("real owner fixture");
    let state = &fixture.state;
    attach_store(state).await.expect("attach original readiness store");
    state.mark_app_server_ready().expect("port ready");
    let original = attached_run(state, "run.native.gate", u64::MAX - 1).expect("original context attachment");
    let _active = state.dispatch_native_run(&original).expect("original dispatch");
    let dispatched_revision = state.native_run_receipt(&original.run_id).expect("original dispatched receipt").revision;
    let gate = NativeEntryGate { state: Arc::downgrade(state), policy_generation: 7 };
    let mut request = ProductionDispatchRequest {
        schema_version: codex_hepta_memory::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
        namespace: codex_hepta_memory::PRODUCTION_DURABLE_WRITER_NAMESPACE.to_owned(),
        lease_id: "lease-original".to_owned(),
        occurrence_key: "operation-original".to_owned(),
        topic: "native-gate-test".to_owned(),
        payload_json: "{}".to_owned(),
        payload_sha256: Sha256Digest::for_bytes(b"{}"),
        idempotency_key: "operation-original".to_owned(),
        operation_scope_sha256: Sha256Digest::for_bytes(b"scope"),
        operation_subject_id: state.identity().agent_id.as_str().to_owned(),
        operation_destination_id: "destination-original".to_owned(),
        operation_semantic_sha256: Sha256Digest::for_bytes(b"semantic"),
        operation_policy_generation: 8,
        expected_predecessor_sha256: None,
        operation_digest: Sha256Digest::for_bytes(b"original"),
    };
    let mut entries = 0;
    assert!(gate.enter_original(&request, &original.run_id, original.generation, dispatched_revision, &mut || {
        entries += 1;
        Ok(())
    }).is_err(), "stale policy cannot enter a live run");
    assert_eq!(entries, 0);
    request.operation_policy_generation = 7;
    drop(gate.enter_original(&request, &original.run_id, original.generation, dispatched_revision, &mut || {
        // The actual final-use callback must linearize while both original
        // lifecycle and run-cancellation owners are locked, not after a check.
        assert!(state.runtime.try_lock().is_err());
        assert!(state.runs.try_lock().is_err());
        entries += 1;
        Ok(())
    }).expect("host currentness only, not a FinalUse grant"));
    assert_eq!(entries, 1);
    state.mark_draining().expect("original owner closes admission");
    assert!(gate.enter_original(&request, &original.run_id, original.generation, dispatched_revision, &mut || {
        entries += 1;
        Ok(())
    }).is_err(), "live closure is reread at actual entry");
    assert_eq!(entries, 1, "entry after cancellation cannot consume a final-use token");
    assert_eq!(state.unresolved_run_count().expect("denial did not invent terminal evidence"), 1);
}

// Test-only access to the actual coordinator lock for reducer contract tests.
// This uses the original sealed preparation and writer proof, never edits a
// RunRecord, and is not compiled into the Agentd production API.
pub(crate) fn resume_original_prepared_for_test(
    state: &AgentdState,
    restored: &crate::intelligence_product::RestoredCanonicalPreparationV1,
    queued: crate::canonical_queued_input::CanonicalQueuedRunV1,
    unused: &codex_hepta_memory::ProductionUnusedScope,
    writer: &codex_hepta_memory::ProductionDurableWriter,
    scope: &codex_hepta_contracts::Sha256Digest,
) -> anyhow::Result<RunReceipt> {
    let mut runs = state.runs.lock().map_err(poisoned_state)?;
    Ok(runs.resume_prepared_without_operations(unix_now_ms()?, restored, queued, unused, writer, scope)
        .map_err(run_error)?)
}
