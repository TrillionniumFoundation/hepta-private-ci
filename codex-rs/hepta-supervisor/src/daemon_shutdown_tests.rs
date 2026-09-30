use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::time::Duration;
use std::time::Instant;

use anyhow::Result;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_paths::HeptaFleetRoot;
use codex_uds::UnixStream;
use tokio::io::AsyncWriteExt;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::DaemonState;
use super::SupervisorEpoch;
use super::SupervisordServer;
use super::execution::Execution;
use super::mutex::MeasuredMutex;
use super::owner::SingleInstanceLock;
use crate::Supervisor;
use crate::SupervisorConfig;
use crate::UnixProcessDriver;

pub(super) struct Fixture {
    pub(super) temp: tempfile::TempDir,
    pub(super) state: Arc<DaemonState<UnixProcessDriver>>,
    pub(super) cancellation: CancellationToken,
}

impl Fixture {
    pub(super) fn new() -> Result<Self> {
        let temp = tempfile::Builder::new()
            .prefix("hsup-owner-")
            .tempdir_in("/tmp")?;
        let root = HeptaFleetRoot::parse(temp.path().canonicalize()?.join("fleet"))?;
        let registry = FleetRegistry::initialize(root)?;
        let instance = SingleInstanceLock::acquire(registry.layout().supervisor_lock())?;
        let driver = UnixProcessDriver::new(256).map_err(anyhow::Error::msg)?;
        let (supervisor, recovery) = Supervisor::recover(
            registry.clone(),
            driver,
            SupervisorConfig::local_default(),
            Instant::now(),
        )?;
        assert!(recovery.faults.is_empty());
        let cancellation = CancellationToken::new();
        let execution = Execution::new(cancellation.clone());
        let epoch = SupervisorEpoch::new();
        execution.view.publish(
            &registry,
            &supervisor,
            &epoch,
            /*recovery_observation_blocked*/ false,
        )?;
        let runtime_modules = crate::DurableRuntimeModuleSupervisorV1::open(
            registry.layout().runtime_module_supervisor_state(),
        )?;
        let state = Arc::new(DaemonState {
            registry,
            supervisor: MeasuredMutex::new(supervisor),
            supervisor_epoch: epoch,
            production_grant_verifier: None,
            observed_faults: AtomicU64::new(0),
            recovery_observation_blocked: std::sync::RwLock::new(Default::default()),
            runtime_modules: MeasuredMutex::new(runtime_modules),
            execution,
            _instance: instance,
        });
        Ok(Self {
            temp,
            state,
            cancellation,
        })
    }
}

#[tokio::test(flavor = "current_thread")]
async fn shutdown_drains_accepted_connection_before_owner_can_be_replaced() -> Result<()> {
    let Fixture {
        temp,
        state,
        cancellation,
    } = Fixture::new()?;
    let path = state.registry.layout().supervisor_socket().to_path_buf();
    let lock = state.registry.layout().supervisor_lock().to_path_buf();
    let server =
        SupervisordServer::bind(path.clone(), Arc::clone(&state), cancellation.clone()).await?;
    let capacity = Arc::clone(&server.connections);
    let daemon = tokio::spawn(server.run());
    let mut idle = UnixStream::connect(&path).await?;
    idle.write_all(b"{").await?;
    timeout(Duration::from_secs(1), async {
        while capacity.available_permits() == super::CONNECTION_CAPACITY {
            tokio::task::yield_now().await;
        }
    })
    .await?;
    drop(state);
    cancellation.cancel();
    tokio::task::yield_now().await;
    assert!(
        !daemon.is_finished(),
        "accepted request was detached on shutdown"
    );
    assert!(SingleInstanceLock::acquire(&lock).is_err());
    drop(idle);
    timeout(Duration::from_secs(3), daemon).await???;
    SingleInstanceLock::acquire(&lock)?;
    drop(temp);
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn dropping_server_future_aborts_and_reaps_idle_connections() -> Result<()> {
    let Fixture {
        temp,
        state,
        cancellation,
    } = Fixture::new()?;
    let path = state.registry.layout().supervisor_socket().to_path_buf();
    let lock = state.registry.layout().supervisor_lock().to_path_buf();
    let server = SupervisordServer::bind(path.clone(), Arc::clone(&state), cancellation).await?;
    let capacity = Arc::clone(&server.connections);
    let daemon = tokio::spawn(server.run());
    let mut idle = UnixStream::connect(&path).await?;
    idle.write_all(b"{").await?;
    timeout(Duration::from_secs(1), async {
        while capacity.available_permits() == super::CONNECTION_CAPACITY {
            tokio::task::yield_now().await;
        }
    })
    .await?;
    drop(state);
    daemon.abort();
    assert!(daemon.await.expect_err("aborted task").is_cancelled());
    timeout(Duration::from_secs(1), async {
        while capacity.available_permits() != super::CONNECTION_CAPACITY {
            tokio::task::yield_now().await;
        }
    })
    .await?;
    SingleInstanceLock::acquire(&lock)?;
    drop(idle);
    drop(temp);
    Ok(())
}
