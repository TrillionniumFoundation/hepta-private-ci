//! Actual recovered-material Root and ordinary post-A daemon processes. The
//! source child remains a separate real peer; no embedded owner runs here.

use std::os::fd::AsRawFd;
use std::os::unix::net::UnixDatagram;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_paths::HeptaFleetRoot;

use super::post_a_plan::OriginalPostAPlan;
use crate::ordinary_q24_process_child_tests::ExitedOriginalProcess;
use crate::ordinary_q24_process_child_tests::OriginalChild;
use crate::ordinary_q24_process_child_tests::OriginalChildDescriptors;

pub(super) struct RunningOrdinaryPostA {
    pub(super) plan: OriginalPostAPlan,
    pub(super) daemon: OriginalChild,
    pub(super) root: OriginalChild,
    source: Option<OriginalChild>,
}

impl RunningOrdinaryPostA {
    pub(super) fn start(
        plan: OriginalPostAPlan,
        start_original_source: impl FnOnce(
            UnixDatagram,
            &OriginalPostAPlan,
        ) -> anyhow::Result<OriginalChild>
        + Send,
    ) -> anyhow::Result<Self> {
        let end = plan.resources.end;
        anyhow::ensure!(Instant::now() < end, "original post-A startup deadline");
        super::recovery::remove_retired_control_nodes(&plan.resources.original)?;
        let mut slots = Vec::new();
        for _ in 0..7 {
            slots.push(tempfile::tempfile()?);
        }
        let own_pidfd = tempfile::tempfile()?;
        let mut command = Command::new(codex_utils_cargo_bin::cargo_bin("hepta-authority-host")?);
        command
            .arg("serve-recovered-material-session")
            .arg("--config")
            .arg(&plan.resources.successor.service)
            .arg("--registration")
            .arg(&plan.resources.successor.registration)
            .arg("--owner-pidfd-stdin")
            .stdin(std::process::Stdio::null())
            .arg("--root-pidfd")
            .arg(own_pidfd.as_raw_fd().to_string())
            .arg("--historical-task-deployment")
            .arg(&plan.root.historical)
            .arg("--post-a-learning-deployment")
            .arg(&plan.root.learning)
            .arg("--post-a-publication-deployment")
            .arg(&plan.root.publication)
            .arg("--post-a-independent-evaluation-deployment")
            .arg(&plan.root.independent_b);
        for (name, file) in [
            "--root-handoff-fd",
            "--root-historical-task-read-handoff-fd",
            "--root-learning-handoff-fd",
            "--root-q24-model-handoff-fd",
            "--root-generation-publication-handoff-fd",
            "--root-independent-b-evaluation-handoff-fd",
            "--root-independent-b-source-handoff-fd",
        ]
        .into_iter()
        .zip(&slots)
        {
            command.arg(name).arg(file.as_raw_fd().to_string());
        }
        let descriptors: Vec<_> = slots.iter().map(AsRawFd::as_raw_fd).collect();
        let (root, (plan, daemon, source)) = super::root_pair::spawn_with_original_pairs(
            &mut command,
            &descriptors,
            own_pidfd.as_raw_fd(),
            end,
            move |mut pairs| {
                let source_receive = pairs
                    .pop()
                    .ok_or_else(|| anyhow::anyhow!("original source pair absent"))?;
                let source = start_original_source(source_receive, &plan)?;
                require_actual_credentials(&source, 60002, 60001, end)?;
                // Root has not exec'ed yet. Its fixed B deployment must now
                // refer to this actual independent peer, not the learner PID.
                let source_data: serde_json::Value = serde_json::from_slice(
                    &super::observer::read_private(&plan.root.independent_b, 65_536)?,
                )?;
                let peer = &source_data["source_peer"];
                anyhow::ensure!(
                    peer["uid"] == 60002
                        && peer["pid"] == source.lifetime().pid
                        && peer["boot_id"] == source.lifetime().boot_id
                        && peer["process_start_ticks"] == source.lifetime().start_ticks,
                    "fixed B source deployment differs from the actual source child"
                );
                anyhow::ensure!(
                    pairs.len() == 6,
                    "exact six original learner handoffs required"
                );
                let daemon = spawn_original_daemon(&plan, &pairs)?;
                require_actual_credentials(&daemon, 60001, 60001, end)?;
                plan.resources
                    .successor
                    .register_live_child(&plan.resources.original, &daemon)?;
                source.require_live()?;
                let owner = daemon.original_pidfd()?;
                Ok(((plan, daemon, source), owner))
            },
        )?;
        drop((slots, own_pidfd));
        plan.resources.original.root.require_distinct_live(&root)?;
        let running = Self {
            plan,
            daemon,
            root,
            source: Some(source),
        };
        running.require_live()?;
        Ok(running)
    }

    pub(super) fn client(&self) -> anyhow::Result<crate::AgentdClient> {
        let identity = &self.plan.resources.successor.identity;
        Ok(crate::AgentdClient::new(
            identity.control_socket.clone(),
            identity.agent_id.clone(),
            identity.spawn_generation,
        )?)
    }

    pub(super) fn join_original_source(&mut self) -> anyhow::Result<ExitedOriginalProcess> {
        self.require_live()?;
        let source = self
            .source
            .take()
            .ok_or_else(|| anyhow::anyhow!("original source process already joined"))?;
        let exited = source.wait_success_until(self.plan.resources.end)?;
        self.require_live()?;
        exited.require_dead()?;
        Ok(exited)
    }

    pub(super) fn require_live(&self) -> anyhow::Result<()> {
        anyhow::ensure!(
            Instant::now() < self.plan.resources.end,
            "original post-A process deadline"
        );
        self.daemon.require_live()?;
        self.root.require_live()
    }

    pub(super) async fn promote_when_initialized(&self) -> anyhow::Result<()> {
        let client = self.client()?;
        loop {
            self.require_live()?;
            if let Ok(health) = client.health().await {
                self.require_health_identity(&health)?;
                if health.promotion_ready {
                    anyhow::ensure!(
                        !health.ready && health.lifecycle == AgentLifecycle::Starting,
                        "actual successor Starting readiness required before promotion"
                    );
                    break;
                }
            }
            self.require_live()?;
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        let identity = &self.plan.resources.successor.identity;
        let registry = FleetRegistry::open_existing(HeptaFleetRoot::parse(&identity.fleet_root)?)?;
        registry.compare_and_transition(
            &identity.agent_id,
            identity.spawn_generation,
            AgentLifecycle::Running,
        )?;
        loop {
            self.require_live()?;
            if let Ok(health) = client.health().await {
                self.require_health_identity(&health)?;
                if health.ready {
                    anyhow::ensure!(
                        health.lifecycle == AgentLifecycle::Running,
                        "actual successor Running readiness"
                    );
                    return self.require_live();
                }
            }
            self.require_live()?;
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    }

    fn require_health_identity(&self, health: &crate::HealthSnapshot) -> anyhow::Result<()> {
        let identity = &self.plan.resources.successor.identity;
        anyhow::ensure!(
            !health.fenced
                && health.process_id == self.daemon.lifetime().pid
                && health.workspace == identity.workspace
                && health.home_root == identity.home_root
                && health.run_root == identity.run_root,
            "actual successor control identity differs"
        );
        self.require_live()
    }
}

fn require_actual_credentials(
    child: &OriginalChild,
    uid: u32,
    gid: u32,
    end: Instant,
) -> anyhow::Result<()> {
    loop {
        child.require_live()?;
        anyhow::ensure!(
            Instant::now() < end,
            "actual child credential transition deadline"
        );
        if crate::authority_host_runtime::verify_process_credentials(child.lifetime().pid, uid, gid)
            .is_ok()
        {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(5));
    }
}

fn spawn_original_daemon(
    plan: &OriginalPostAPlan,
    pairs: &[UnixDatagram],
) -> anyhow::Result<OriginalChild> {
    let identity = &plan.resources.successor.identity;
    let control = crate::bind_root_agentd_socket(&identity.control_socket, 60001, 60001)?;
    let app_server = crate::bind_root_agentd_socket(&identity.app_server_socket, 60001, 60001)?;
    let mut command = Command::new(codex_utils_cargo_bin::cargo_bin("codex-hepta-agentd")?);
    command
        .current_dir(&identity.workspace)
        .env(
            codex_hepta_paths::HEPTA_FLEET_ROOT_ENV,
            &identity.fleet_root,
        )
        .env(
            crate::config::HEPTA_AGENT_ID_ENV,
            identity.agent_id.as_str(),
        )
        .env(
            crate::config::HEPTA_AGENT_GENERATION_ENV,
            identity.spawn_generation.to_string(),
        )
        .env(crate::config::HEPTA_AGENT_HOME_ENV, &identity.home_root)
        .env(crate::config::HEPTA_AGENT_RUN_ROOT_ENV, &identity.run_root)
        .env("CODEX_HOME", &identity.home_root)
        .args(["--root-production-profile", "q24-post-a"])
        .args([
            "--root-production-uid",
            "60001",
            "--root-production-gid",
            "60001",
        ])
        .arg("--root-production-lifetime-ms")
        .arg(super::root::LIFETIME_MS.to_string())
        .arg("--q24-post-a-deployment-fd")
        .arg(plan.sealed.as_raw_fd().to_string())
        .arg("--root-production-control-fd")
        .arg(control.as_raw_fd().to_string())
        .arg("--root-production-app-server-fd")
        .arg(app_server.as_raw_fd().to_string())
        .arg("--authbus-trust-file")
        .arg(&plan.resources.original.plan.objective_trust)
        .arg("--authbus-checkpoint-file")
        .arg(&plan.resources.original.plan.replay_checkpoint)
        .arg("--objective-profile-file")
        .arg(&plan.resources.original.plan.objective_profile);
    for (name, pair) in [
        "--root-production-handoff-fd",
        "--root-historical-task-read-handoff-fd",
        "--root-learning-handoff-fd",
        "--root-q24-model-handoff-fd",
        "--root-generation-publication-handoff-fd",
        "--root-independent-b-evaluation-handoff-fd",
    ]
    .into_iter()
    .zip(pairs)
    {
        command.arg(name).arg(pair.as_raw_fd().to_string());
    }
    let mut inherited: Vec<_> = pairs.iter().map(AsRawFd::as_raw_fd).collect();
    inherited.extend([
        plan.sealed.as_raw_fd(),
        control.as_raw_fd(),
        app_server.as_raw_fd(),
    ]);
    Ok(OriginalChild::spawn(
        &mut command,
        OriginalChildDescriptors {
            inherited,
            own_pidfd_slot: None,
        },
    )?)
}
