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

fn digest(byte: char) -> String {
    byte.to_string().repeat(64)
}

#[tokio::test]
async fn daemon_control_owns_the_run_lifecycle_and_advertises_it() {
    let (_temp, _registry, state) = fixture().expect("runtime fixture");

    let capabilities = state
        .response(
            /*request_id*/ 10,
            /*spawn_generation*/ 1,
            crate::AgentdMethod::Capabilities,
        )
        .await
        .expect("capabilities");
    let AgentdPayload::Capabilities(capabilities) = capabilities.payload else {
        panic!("expected capabilities payload");
    };
    assert!(capabilities.capabilities.iter().any(|capability| {
        capability.id == crate::AGENTD_RUN_LIFECYCLE_CAPABILITY_ID
            && capability.major == crate::AGENTD_RUN_LIFECYCLE_CAPABILITY_MAJOR
            && capability.minor == crate::AGENTD_RUN_LIFECYCLE_CAPABILITY_MINOR
    }));

    let snapshot = crate::AgentRunSnapshot {
        run_id: "run.control.1".to_string(),
        request_digest: digest('1'),
        objective_digest: digest('2'),
        body_digest: digest('3'),
        artifact_set_digest: digest('4'),
        authority_epoch: 7,
        deadline_ms: u64::MAX - 1,
    };
    let started = state
        .response(
            11,
            1,
            crate::AgentdMethod::RunStart {
                snapshot: snapshot.clone(),
            },
        )
        .await
        .expect("start run");
    let AgentdPayload::RunReceipt(started) = started.payload else {
        panic!("expected run receipt");
    };
    assert_eq!(started.phase, crate::AgentRunPhase::Admitted);
    assert_eq!(started.revision, 1);

    let attached = state
        .response(
            12,
            1,
            crate::AgentdMethod::RunAttachContext {
                expected_revision: started.revision,
                attachment: crate::AgentContextAttachment {
                    run_id: snapshot.run_id.clone(),
                    request_digest: snapshot.request_digest.clone(),
                    objective_digest: snapshot.objective_digest.clone(),
                    body_digest: snapshot.body_digest.clone(),
                    artifact_set_digest: snapshot.artifact_set_digest.clone(),
                    authority_epoch: snapshot.authority_epoch,
                    deadline_ms: snapshot.deadline_ms,
                    context_digest: digest('5'),
                    compilation_receipt_digest: digest('6'),
                },
            },
        )
        .await
        .expect("attach context");
    let AgentdPayload::RunReceipt(attached) = attached.payload else {
        panic!("expected run receipt");
    };
    assert_eq!(attached.phase, crate::AgentRunPhase::ContextAttached);
    assert_eq!(attached.revision, 2);

    let dispatched = state
        .response(
            13,
            1,
            crate::AgentdMethod::RunMarkDispatched {
                run_id: snapshot.run_id.clone(),
                expected_revision: attached.revision,
            },
        )
        .await
        .expect("mark dispatched");
    let AgentdPayload::RunReceipt(dispatched) = dispatched.payload else {
        panic!("expected run receipt");
    };
    assert_eq!(dispatched.phase, crate::AgentRunPhase::Dispatched);
    assert_eq!(dispatched.revision, 3);

    state.mark_draining().expect("begin local drain");
    assert!(
        state
            .response(
                14,
                1,
                crate::AgentdMethod::RunStart {
                    snapshot: crate::AgentRunSnapshot {
                        run_id: "run.control.2".to_string(),
                        ..snapshot.clone()
                    },
                },
            )
            .await
            .is_err()
    );

    let status = state
        .response(
            15,
            1,
            crate::AgentdMethod::RunStatus {
                run_id: snapshot.run_id.clone(),
            },
        )
        .await
        .expect("run remains queryable during drain");
    let AgentdPayload::RunStatus {
        run: Some(draining),
    } = status.payload
    else {
        panic!("expected draining run status");
    };
    assert_eq!(draining.phase, crate::AgentRunPhase::Cancelling);
    assert_eq!(draining.cancel_reason.as_deref(), Some("agentd_shutdown"));

    let terminal = state
        .response(
            16,
            1,
            crate::AgentdMethod::RunObserveTerminal {
                run_id: snapshot.run_id,
                expected_revision: draining.revision,
                phase: crate::AgentRunPhase::Succeeded,
                terminal_observed: true,
            },
        )
        .await
        .expect("terminal observation during drain");
    let AgentdPayload::RunReceipt(terminal) = terminal.payload else {
        panic!("expected terminal receipt");
    };
    assert_eq!(terminal.phase, crate::AgentRunPhase::Succeeded);
    assert!(terminal.terminal_observed);
    assert_eq!(state.active_run_count().expect("active runs"), 0);
}
