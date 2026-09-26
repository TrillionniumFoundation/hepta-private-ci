use super::*;
use crate::SUPERVISORD_CONTROL_SCHEMA_VERSION;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use pretty_assertions::assert_eq;
use std::path::Path;

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn received_start_survives_socket_expiry_while_waiting_for_owner()
-> Result<(), SupervisorError> {
    let temp = tempfile::Builder::new()
        .prefix("hsio-")
        .tempdir_in("/tmp")?;
    let root = HeptaFleetRoot::parse(temp.path().join("fleet"))
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    let registry = FleetRegistry::initialize(root.clone())?;
    let id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    let workspace = temp.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    registry.register(AgentManifest::new(
        id.clone(),
        WorkspaceBinding::new(workspace, &root)?,
        ResourceBudget::local_default(),
    )?)?;
    let release = ReleaseId::parse("received-start")?;
    // The real child exits immediately, including when the assertion fails.
    registry.install_release(release.clone(), Path::new("/bin/true"), Vec::new())?;
    registry.allow_release(&id, &release)?;
    let (supervisor, report) = Supervisor::recover(
        registry.clone(),
        UnixProcessDriver::new(16).map_err(|error| SupervisorError::Invalid(error.to_string()))?,
        SupervisorConfig::local_default(),
        Instant::now(),
    )?;
    assert!(report.faults.is_empty());
    let state = Arc::new(DaemonState {
        registry: registry.clone(),
        supervisor: Mutex::new(supervisor),
        supervisor_epoch: SupervisorEpoch::new(),
        production_grant_verifier: None,
        observed_faults: AtomicU64::new(0),
    });
    let snapshot = {
        let owner = state.supervisor.lock().await;
        agent_status_locked(&state, &owner, &id)?
    };
    let (locked_tx, locked_rx) = tokio::sync::oneshot::channel();
    let (release_tx, release_rx) = std::sync::mpsc::sync_channel(1);
    let held_state = Arc::clone(&state);
    let holder = tokio::task::spawn_blocking(move || {
        let owner = held_state.supervisor.blocking_lock();
        locked_tx.send(()).map_err(|()| {
            SupervisorError::Invalid("contention fixture receiver closed".to_string())
        })?;
        release_rx
            .recv_timeout(IO_TIMEOUT + Duration::from_secs(15))
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        drop(owner);
        Ok::<(), SupervisorError>(())
    });
    locked_rx
        .await
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    let cancellation = CancellationToken::new();
    let server = SupervisordServer::bind(
        root.layout().supervisor_socket().to_path_buf(),
        Arc::clone(&state),
        cancellation.clone(),
    )
    .await?;
    let server_task = tokio::spawn(server.run());
    let mut client = UnixStream::connect(root.layout().supervisor_socket()).await?;
    let request = SupervisordRequest {
        schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
        request_id: 1,
        method: SupervisordMethod::Start {
            fence: snapshot.control_fence,
            release_id: release,
        },
    };
    let mut frame = serde_json::to_vec(&request)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    frame.push(b'\n');
    client.write_all(&frame).await?;
    client.shutdown().await?;
    drop(client);
    tokio::time::sleep(IO_TIMEOUT + Duration::from_millis(100)).await;
    release_tx
        .try_send(())
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    holder
        .await
        .map_err(|error| SupervisorError::Invalid(error.to_string()))??;
    let completion = timeout(Duration::from_secs(15), async {
        loop {
            if registry.load_agent(&id)?.lifecycle.lifecycle == AgentLifecycle::Starting {
                return Ok::<(), SupervisorError>(());
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await;
    cancellation.cancel();
    server_task
        .await
        .map_err(|error| SupervisorError::Invalid(error.to_string()))??;
    completion.map_err(|_| {
        SupervisorError::Invalid(
            "received request was abandoned when its socket expired".to_string(),
        )
    })??;
    assert_eq!(
        registry.load_agent(&id)?.lifecycle.lifecycle,
        AgentLifecycle::Starting
    );
    assert!(
        state
            .supervisor
            .lock()
            .await
            .snapshot(&id)
            .expect("tracked child")
            .active
    );
    Ok(())
}
