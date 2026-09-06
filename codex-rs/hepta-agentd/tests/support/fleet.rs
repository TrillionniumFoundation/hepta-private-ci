use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::HealthSnapshot;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::AgentCommand;
use codex_hepta_supervisor::AgentRelease;
use codex_hepta_supervisor::Supervisor;
use codex_hepta_supervisor::SupervisorConfig;
use codex_hepta_supervisor::UnixProcessDriver;
use codex_utils_absolute_path::AbsolutePathBuf;

const READY_TIMEOUT: Duration = Duration::from_secs(60);

pub(crate) struct AgentFixture {
    pub(crate) agent_id: AgentId,
    pub(crate) layout: HeptaAgentLayout,
    pub(crate) workspace: PathBuf,
}

pub(crate) struct FleetHarness {
    _temp: tempfile::TempDir,
    root: PathBuf,
    fleet_root: HeptaFleetRoot,
    pub(crate) registry: FleetRegistry,
    pub(crate) supervisor: Supervisor<UnixProcessDriver>,
    supervisor_config: SupervisorConfig,
    agent_ids: Vec<AgentId>,
    started: bool,
}

impl FleetHarness {
    pub(crate) fn new() -> Result<Self> {
        let temp = tempfile::tempdir()?;
        let root = temp.path().canonicalize()?;
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet"))?;
        let registry = FleetRegistry::initialize(fleet_root.clone())?;
        let mut config = SupervisorConfig::local_default();
        config.health_timeout = READY_TIMEOUT;
        config.drain_timeout = Duration::from_secs(2);
        config.stop_grace = Duration::from_secs(1);
        let driver = UnixProcessDriver::new(256)?;
        let (supervisor, recovery) =
            Supervisor::recover(registry.clone(), driver, config.clone(), Instant::now())?;
        ensure!(
            recovery.faults.is_empty(),
            "unexpected supervisor recovery faults: {:?}",
            recovery.faults
        );
        Ok(Self {
            _temp: temp,
            root,
            fleet_root,
            registry,
            supervisor,
            supervisor_config: config,
            agent_ids: Vec::new(),
            started: false,
        })
    }

    #[allow(dead_code)]
    pub(crate) fn register(
        &mut self,
        agent_id: &str,
        workspace_name: &str,
    ) -> Result<AgentFixture> {
        self.register_with_resources(agent_id, workspace_name, ResourceBudget::local_default())
    }

    pub(crate) fn register_with_resources(
        &mut self,
        agent_id: &str,
        workspace_name: &str,
        resources: ResourceBudget,
    ) -> Result<AgentFixture> {
        ensure!(
            !self.started,
            "all fleet agents must be registered before the first process starts"
        );
        let workspace = self.root.join(workspace_name);
        std::fs::create_dir(&workspace)?;
        let workspace = workspace.canonicalize()?;
        let agent_id = AgentId::parse(agent_id).map_err(anyhow::Error::msg)?;
        let binding = WorkspaceBinding::new(&workspace, &self.fleet_root)?;
        let manifest = AgentManifest::new(agent_id.clone(), binding, resources)?;
        let record = self.registry.register(manifest)?;
        self.agent_ids.push(agent_id.clone());
        let driver = UnixProcessDriver::new(256)?;
        let (supervisor, recovery) = Supervisor::recover(
            self.registry.clone(),
            driver,
            self.supervisor_config.clone(),
            Instant::now(),
        )?;
        ensure!(
            recovery.faults.is_empty(),
            "unexpected supervisor recovery faults after registering {agent_id}: {:?}",
            recovery.faults
        );
        self.supervisor = supervisor;
        Ok(AgentFixture {
            agent_id,
            layout: record.layout,
            workspace,
        })
    }

    #[allow(dead_code)]
    pub(crate) fn start(&mut self, agent: &AgentFixture) -> Result<()> {
        let binary = agentd_binary()?;
        let command = AgentCommand::new(binary, Vec::new())?;
        self.supervisor
            .start(&agent.agent_id, command, Instant::now())?;
        self.started = true;
        Ok(())
    }

    #[allow(dead_code)]
    pub(crate) fn start_release(
        &mut self,
        agent: &AgentFixture,
        release: AgentRelease,
    ) -> Result<()> {
        self.supervisor
            .start_release(&agent.agent_id, release, Instant::now())?;
        self.started = true;
        Ok(())
    }

    pub(crate) fn control_client(
        &self,
        agent: &AgentFixture,
        generation: u64,
    ) -> Result<AgentdClient> {
        AgentdClient::new(
            agent.layout.agentd_control_socket().to_path_buf(),
            agent.agent_id.clone(),
            generation,
        )
        .map_err(Into::into)
    }

    pub(crate) async fn wait_ready(
        &mut self,
        agent: &AgentFixture,
        generation: u64,
    ) -> Result<(AgentdClient, HealthSnapshot)> {
        let control = self.control_client(agent, generation)?;
        let health = self.wait_until_ready(&agent.agent_id, &control).await?;
        ensure!(
            health.workspace == agent.workspace,
            "agent workspace drifted"
        );
        ensure!(
            health.home_root == agent.layout.home_root(),
            "agent home drifted"
        );
        Ok((control, health))
    }

    pub(crate) async fn wait_until_ready(
        &mut self,
        agent_id: &AgentId,
        control: &AgentdClient,
    ) -> Result<HealthSnapshot> {
        let deadline = Instant::now() + READY_TIMEOUT;
        loop {
            let report = self.supervisor.tick(Instant::now());
            ensure!(
                report.faults.is_empty(),
                "supervisor faults while waiting for {agent_id}: {:?}",
                report.faults
            );
            if let Ok(health) = control.health().await
                && health.ready
            {
                return Ok(health);
            }
            if Instant::now() >= deadline {
                let snapshot = self.supervisor.snapshot(agent_id);
                bail!("timed out waiting for agent {agent_id} readiness; snapshot={snapshot:?}");
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    }
}

pub(crate) fn agentd_binary() -> Result<PathBuf> {
    Ok(codex_utils_cargo_bin::cargo_bin("codex-hepta-agentd")?)
}

impl Drop for FleetHarness {
    fn drop(&mut self) {
        for agent_id in &self.agent_ids {
            let _ = self.supervisor.kill(agent_id);
        }
        let deadline = Instant::now() + Duration::from_secs(3);
        while Instant::now() < deadline {
            self.supervisor.tick(Instant::now());
            if self.agent_ids.iter().all(|agent_id| {
                self.supervisor
                    .snapshot(agent_id)
                    .is_none_or(|snapshot| !snapshot.active)
            }) {
                break;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
    }
}

#[allow(dead_code)]
pub(crate) async fn connect_app_server(
    socket_path: &Path,
    client_name: &str,
    channel_capacity: usize,
) -> Result<RemoteAppServerClient> {
    connect_app_server_with_experimental(
        socket_path,
        client_name,
        channel_capacity,
        /*experimental_api*/ false,
    )
    .await
}

pub(crate) async fn connect_app_server_with_experimental(
    socket_path: &Path,
    client_name: &str,
    channel_capacity: usize,
    experimental_api: bool,
) -> Result<RemoteAppServerClient> {
    let socket_path = AbsolutePathBuf::from_absolute_path(socket_path)?;
    Ok(RemoteAppServerClient::connect(RemoteAppServerConnectArgs {
        endpoint: RemoteAppServerEndpoint::UnixSocket { socket_path },
        client_name: client_name.to_string(),
        client_version: env!("CARGO_PKG_VERSION").to_string(),
        experimental_api,
        mcp_server_openai_form_elicitation: false,
        opt_out_notification_methods: Vec::new(),
        channel_capacity,
    })
    .await?)
}
