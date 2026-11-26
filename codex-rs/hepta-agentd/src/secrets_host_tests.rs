#![allow(clippy::expect_used)]
//! Physical worker lifecycle and original scheduling expiry through the real host.
use super::*;
use codex_hepta_agent_components::contracts::AgentId;
use codex_hepta_agent_components::fleet::AgentLifecycle;
use codex_hepta_agent_components::fleet::AgentManifest;
use codex_hepta_agent_components::fleet::FleetRegistry;
use codex_hepta_agent_components::fleet::ResourceBudget;
use codex_hepta_agent_components::fleet::WorkspaceBinding;
use codex_hepta_agent_components::paths::HeptaFleetRoot;
use std::os::unix::net::UnixListener;

pub(crate) struct Fixture {
    _temp: tempfile::TempDir,
    pub(crate) state: Arc<AgentdState>,
    pub(crate) host: Arc<AgentdSecretsHost>,
    pub(crate) client: Arc<SecretsRuntimeClient>,
    pub(crate) listener: UnixListener,
}
pub(crate) fn fixture() -> Fixture {
    let temp = tempfile::tempdir().expect("physical fixture");
    let root = temp.path().canonicalize().expect("canonical fixture");
    let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fixture registry");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("fixture Agent");
    let record = registry
        .register(
            AgentManifest::new(
                agent_id.clone(),
                WorkspaceBinding::new(&workspace, &fleet_root).expect("binding"),
                ResourceBudget::local_default(),
            )
            .expect("manifest"),
        )
        .expect("register");
    registry
        .compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)
        .expect("Starting");
    let identity = crate::AgentdIdentity {
        agent_id: agent_id.clone(),
        layout: record.layout.clone(),
        spawn_generation: 1,
        fleet_root: fleet_root.as_path().to_owned(),
        workspace,
        resources: record.manifest.resources,
        home_root: record.layout.home_root().to_owned(),
        run_root: record.layout.run_root().to_owned(),
        control_socket: record.layout.agentd_control_socket().to_owned(),
        app_server_socket: record.layout.app_server_socket().to_owned(),
    };
    let state = Arc::new(AgentdState::new(identity, registry.clone(), 16).expect("actual state"));
    registry
        .compare_and_transition(&agent_id, 1, AgentLifecycle::Running)
        .expect("Running");
    state.refresh_generation().expect("generation");
    let endpoint = root.join("untrusted-daemon.sock");
    let listener = UnixListener::bind(&endpoint).expect("actual untrusted peer");
    listener.set_nonblocking(true).expect("bounded observer");
    // This untrusted listener has our UID, deliberately differing from the pin.
    // It can observe connects but cannot produce a qualified daemon response.
    let uid = unsafe { libc::geteuid() };
    let config = serde_json::from_value(serde_json::json!({"schema_version":1,"agent_uid":uid,"agent_id":agent_id.as_str(),"runtime_uid":uid+1,"socket_path":endpoint,"operation_timeout_ms":30000})).expect("fixture config");
    let client =
        SecretsRuntimeClient::new(config, agent_id.as_str()).expect("enrolled client shape");
    let host = Arc::new(AgentdSecretsHost {
        client: Arc::new(client),
        state: Arc::downgrade(&state),
        slots: Arc::new(Semaphore::new(MAX_WORKERS)),
        workers: Mutex::new(PhysicalWorkers {
            closed: false,
            handles: Vec::new(),
        }),
    });
    let client = Arc::clone(&host.client);
    Fixture {
        _temp: temp,
        state,
        host,
        client,
        listener,
    }
}

#[tokio::test]
async fn secrets_finished_worker_slot_is_released_only_by_physical_owner_join() {
    let fixture = fixture();
    let reply = fixture
        .host
        .dispatch(AgentdMethod::SecretsOriginalStatus {
            original_id: "finished-original".into(),
        })
        .expect("actual worker");
    assert!(matches!(
        reply.await.expect("original reply"),
        SecretsOriginalObservation::Unknown { .. }
    ));
    // A finished thread cannot release its own permit. The original owner
    // must physically join it before a subsequent admission reuses its slot.
    std::thread::sleep(Duration::from_millis(10));
    assert_eq!(fixture.host.slots.available_permits(), MAX_WORKERS - 1);
    assert_eq!(fixture.host.pending_workers(), 0);
    assert_eq!(fixture.host.slots.available_permits(), MAX_WORKERS);
    fixture
        .host
        .shutdown()
        .await
        .expect("physical owner joined");
}

#[tokio::test]
async fn secrets_poisoned_owner_still_joins_original_workers_before_reporting_failure() {
    let fixture = fixture();
    let reply = fixture
        .host
        .dispatch(AgentdMethod::SecretsOriginalStatus {
            original_id: "poisoned-original".into(),
        })
        .expect("actual worker");
    assert!(matches!(
        reply.await.expect("original reply"),
        SecretsOriginalObservation::Unknown { .. }
    ));
    let host = Arc::clone(&fixture.host);
    assert!(
        std::thread::spawn(move || {
            let _guard = host.workers.lock().expect("owner lock");
            panic!("simulate failed owner while original handle remains tracked");
        })
        .join()
        .is_err()
    );
    assert!(fixture.host.closed());
    assert!(fixture.host.shutdown().await.is_err());
    assert_eq!(fixture.host.slots.available_permits(), MAX_WORKERS);
}
