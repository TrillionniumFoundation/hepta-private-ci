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
async fn live_control_routes_run_lifecycle_through_agentd_state() {
    let (_temp, _registry, state) = fixture().expect("runtime fixture");
    let now_ms = u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock")
            .as_millis(),
    )
    .expect("millisecond clock");
    let snapshot = RunSnapshot {
        run_id: "run.live.1".to_string(),
        request_digest: "1".repeat(64),
        objective_digest: "2".repeat(64),
        body_digest: "3".repeat(64),
        artifact_set_digest: "4".repeat(64),
        authority_epoch: 2,
        deadline_ms: now_ms + 60_000,
    };
    let start = state
        .response(
            10,
            1,
            crate::AgentdMethod::RunStart {
                snapshot: snapshot.clone(),
            },
        )
        .await
        .expect("run start");
    let admitted = match start.payload {
        AgentdPayload::RunReceipt(receipt) => receipt,
        payload => panic!("unexpected start payload: {payload:?}"),
    };
    assert_eq!(admitted.phase, RunPhase::Admitted);

    let attachment = ContextAttachment {
        run_id: snapshot.run_id.clone(),
        request_digest: snapshot.request_digest,
        objective_digest: snapshot.objective_digest,
        body_digest: snapshot.body_digest,
        artifact_set_digest: snapshot.artifact_set_digest,
        authority_epoch: snapshot.authority_epoch,
        deadline_ms: snapshot.deadline_ms,
        context_digest: "5".repeat(64),
        compilation_receipt_digest: "6".repeat(64),
    };
    let attached = state
        .response(
            11,
            1,
            crate::AgentdMethod::RunAttachContext {
                expected_revision: admitted.revision,
                attachment,
            },
        )
        .await
        .expect("attach context");
    let attached = match attached.payload {
        AgentdPayload::RunReceipt(receipt) => receipt,
        payload => panic!("unexpected attach payload: {payload:?}"),
    };
    assert_eq!(attached.phase, RunPhase::ContextAttached);

    let dispatched = state
        .response(
            12,
            1,
            crate::AgentdMethod::RunMarkDispatched {
                run_id: "run.live.1".to_string(),
                expected_revision: attached.revision,
            },
        )
        .await
        .expect("mark dispatched");
    let dispatched = match dispatched.payload {
        AgentdPayload::RunReceipt(receipt) => receipt,
        payload => panic!("unexpected dispatch payload: {payload:?}"),
    };
    assert_eq!(dispatched.phase, RunPhase::Dispatched);

    state.mark_draining().expect("begin drain");
    let new_snapshot = RunSnapshot {
        run_id: "run.live.2".to_string(),
        request_digest: "a".repeat(64),
        objective_digest: "b".repeat(64),
        body_digest: "c".repeat(64),
        artifact_set_digest: "d".repeat(64),
        authority_epoch: 2,
        deadline_ms: now_ms + 60_000,
    };
    assert!(
        state
            .response(
                13,
                1,
                crate::AgentdMethod::RunStart {
                    snapshot: new_snapshot,
                },
            )
            .await
            .is_err()
    );
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
    let changed = AgentdState::new(identity, registry.clone(), /*event_capacity*/ 16);
    assert!(
        matches!(changed, Err(AgentdError::Protocol(message)) if message.contains("InvalidGeneration")),
        "same-generation composition drift reached a serving Agentd"
    );
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
