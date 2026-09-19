use std::fs;

use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;

fn fixture() -> anyhow::Result<(tempfile::TempDir, FleetRegistry, AgentdState)> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let manifest = AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet_root)?,
        ResourceBudget::local_default(),
    )?;
    let record = registry.register(manifest)?;
    registry.compare_and_transition(
        &agent_id,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
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
    let state = AgentdState::new(identity, registry.clone(), /*event_capacity*/ 16)?;
    registry.compare_and_transition(
        &state.identity.agent_id,
        /*expected_generation*/ 1,
        AgentLifecycle::Running,
    )?;
    state.refresh_generation()?;
    state.mark_app_server_ready()?;
    Ok((temp, registry, state))
}

#[tokio::test]
async fn serving_agent_survives_unrelated_registry_corruption() {
    let (_temp, registry, state) = fixture().expect("runtime fixture");
    let peer = registry
        .layout()
        .agents_root()
        .join("019153a4-3088-7e03-a56a-9b1964f75dd3");
    fs::create_dir(peer).expect("incomplete peer");
    assert!(registry.load().is_err());
    state
        .refresh_generation()
        .expect("local generation remains valid");
    let response = state
        .response(
            /*request_id*/ 1,
            /*spawn_generation*/ 1,
            crate::AgentdMethod::Lifecycle,
        )
        .await
        .expect("serving control response");
    assert_eq!(
        serde_json::to_value(response.payload).expect("serialize actual lifecycle"),
        serde_json::to_value(AgentdPayload::Lifecycle(LifecycleSnapshot {
            lifecycle: AgentLifecycle::Running,
            app_server_ready: true,
            fenced: false,
        }))
        .expect("serialize expected lifecycle")
    );
}

#[tokio::test]
async fn wire_run_lifecycle_is_daemon_owned_and_recovers_uncertain_dispatch() {
    let (_temp, registry, state) = fixture().expect("runtime fixture");
    let snapshot = crate::AgentdRunSnapshot {
        run_id: "run.product.1".to_string(),
        request_digest: "1".repeat(64),
        objective_digest: "2".repeat(64),
        body_digest: "3".repeat(64),
        artifact_set_digest: "4".repeat(64),
        authority_epoch: 2,
        deadline_ms: u64::MAX - 1,
    };
    let started = state
        .response(
            1,
            1,
            crate::AgentdMethod::RunStart {
                snapshot: snapshot.clone(),
            },
        )
        .await
        .expect("start through daemon");
    let AgentdPayload::RunReceipt(started) = started.payload else {
        panic!("expected run receipt");
    };
    assert_eq!(started.phase, crate::AgentdRunPhase::Admitted);
    assert_eq!(started.revision, 1);

    let attached = state
        .response(
            2,
            1,
            crate::AgentdMethod::RunAttachContext {
                expected_revision: started.revision,
                attachment: crate::AgentdContextAttachment {
                    run_id: snapshot.run_id.clone(),
                    request_digest: snapshot.request_digest.clone(),
                    objective_digest: snapshot.objective_digest.clone(),
                    body_digest: snapshot.body_digest.clone(),
                    artifact_set_digest: snapshot.artifact_set_digest.clone(),
                    authority_epoch: snapshot.authority_epoch,
                    deadline_ms: snapshot.deadline_ms,
                    context_digest: "5".repeat(64),
                    compilation_receipt_digest: "6".repeat(64),
                },
            },
        )
        .await
        .expect("attach through daemon");
    let AgentdPayload::RunReceipt(attached) = attached.payload else {
        panic!("expected attached receipt");
    };
    assert_eq!(attached.phase, crate::AgentdRunPhase::ContextAttached);

    let dispatched = state
        .response(
            3,
            1,
            crate::AgentdMethod::RunMarkDispatched {
                run_id: snapshot.run_id.clone(),
                expected_revision: attached.revision,
            },
        )
        .await
        .expect("dispatch through daemon");
    let AgentdPayload::RunReceipt(dispatched) = dispatched.payload else {
        panic!("expected dispatch receipt");
    };
    assert_eq!(dispatched.phase, crate::AgentdRunPhase::Dispatched);

    let identity = state.identity.clone();
    drop(state);
    let recovered =
        AgentdState::new(identity, registry, /*event_capacity*/ 16).expect("recover state");
    let status = recovered
        .response(
            4,
            1,
            crate::AgentdMethod::RunGet {
                run_id: snapshot.run_id,
            },
        )
        .await
        .expect("get recovered run");
    let AgentdPayload::RunStatus {
        receipt: Some(receipt),
    } = status.payload
    else {
        panic!("expected recovered run status");
    };
    assert_eq!(receipt.phase, crate::AgentdRunPhase::Indeterminate);
    assert_eq!(receipt.revision, dispatched.revision + 1);
}

#[test]
fn missing_local_record_immediately_fences_the_serving_agent() {
    let (_temp, _registry, state) = fixture().expect("runtime fixture");
    fs::remove_file(state.identity.layout.agent_config()).expect("remove local manifest");
    assert!(matches!(
        state.refresh_generation(),
        Err(AgentdError::GenerationFenced(_))
    ));
    assert!(state.is_fenced().expect("fenced state"));
}

#[test]
fn targeted_read_preserves_lifecycle_and_resource_fences() {
    let (_temp, registry, state) = fixture().expect("runtime fixture");
    let mut identity = state.identity.clone();
    identity.resources.turn_queue_capacity += 1;
    let changed = AgentdState::new(identity, registry.clone(), /*event_capacity*/ 16)
        .expect("changed launch identity");
    assert!(matches!(
        changed.refresh_generation(),
        Err(AgentdError::GenerationFenced(_))
    ));
    registry
        .compare_and_transition(
            &state.identity.agent_id,
            /*expected_generation*/ 2,
            AgentLifecycle::Draining,
        )
        .expect("draining");
    state.refresh_generation().expect("drain remains valid");
    registry
        .compare_and_transition(
            &state.identity.agent_id,
            /*expected_generation*/ 3,
            AgentLifecycle::Stopped,
        )
        .expect("stopped");
    assert!(matches!(
        state.refresh_generation(),
        Err(AgentdError::GenerationFenced(_))
    ));
}
