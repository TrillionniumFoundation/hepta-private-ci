//! Two new product processes over the original completed business files.
//! The original independent source stays dead; its closed handoff is retained
//! only so the Root's explicit existing-data route can send its original FDs.

use std::os::fd::AsRawFd;
use std::os::unix::net::UnixDatagram;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_paths::HeptaFleetRoot;

use super::cold_deployment::OriginalColdPlan;
use crate::ordinary_q24_process_child_tests::ExitedOriginalProcess;
use crate::ordinary_q24_process_child_tests::OriginalChild;
use crate::ordinary_q24_process_child_tests::OriginalChildDescriptors;

pub(super) struct RunningOrdinaryCold<'a> {
    pub(super) plan: OriginalColdPlan<'a>,
    pub(super) daemon: OriginalChild,
    pub(super) root: OriginalChild,
    closed_source: UnixDatagram,
}

impl<'a> RunningOrdinaryCold<'a> {
    pub(super) fn start(plan: OriginalColdPlan<'a>) -> anyhow::Result<Self> {
        let end = plan.administration.end;
        anyhow::ensure!(Instant::now() < end, "original cold startup deadline");
        plan.original.daemon.require_dead()?;
        plan.original.root.require_dead()?;
        plan.original.source.require_dead()?;
        // The same protected socket paths now belong to the also-exited
        // post-A incarnation. Both original incarnations are proved dead;
        // this helper only removes the exact UID/mode/socket-shaped nodes.
        super::recovery::remove_retired_control_nodes(&plan.original.plan.resources.original)?;
        plan.original.daemon.require_dead()?;
        plan.original.root.require_dead()?;
        let mut slots = Vec::new();
        for _ in 0..7 {
            slots.push(tempfile::tempfile()?);
        }
        let own_pidfd = tempfile::tempfile()?;
        let mut command = Command::new(codex_utils_cargo_bin::cargo_bin("hepta-authority-host")?);
        command
            .arg("serve-recovered-material-session")
            .arg("--config")
            .arg(&plan.administration.successor.service)
            .arg("--registration")
            .arg(&plan.administration.successor.registration)
            .arg("--owner-pidfd-stdin")
            .stdin(std::process::Stdio::null())
            .arg("--root-pidfd")
            .arg(own_pidfd.as_raw_fd().to_string())
            .arg("--historical-task-deployment")
            .arg(&plan.historical)
            .arg("--post-a-learning-deployment")
            .arg(&plan.learning)
            .arg("--post-a-publication-deployment")
            .arg(&plan.publication)
            .arg("--post-a-independent-evaluation-deployment")
            .arg(&plan.original.plan.root.independent_b);
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
        let (root, (plan, daemon, closed_source)) = super::root_pair::spawn_with_original_pairs(
            &mut command,
            &descriptors,
            own_pidfd.as_raw_fd(),
            end,
            move |mut pairs| {
                let closed_source = pairs
                    .pop()
                    .ok_or_else(|| anyhow::anyhow!("original closed source pair absent"))?;
                anyhow::ensure!(pairs.len() == 6, "exact original learner handoffs required");
                plan.original.source.require_dead()?;
                let daemon = spawn_original_daemon(&plan, &pairs)?;
                loop {
                    daemon.require_live()?;
                    anyhow::ensure!(Instant::now() < end, "cold credential deadline");
                    if crate::authority_host_runtime::verify_process_credentials(
                        daemon.lifetime().pid,
                        60001,
                        60001,
                    )
                    .is_ok()
                    {
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(5));
                }
                plan.administration
                    .register_original_child(plan.original, &daemon)?;
                let owner = daemon.original_pidfd()?;
                Ok(((plan, daemon, closed_source), owner))
            },
        )?;
        drop((slots, own_pidfd));
        plan.original.root.require_distinct_live(&root)?;
        plan.original
            .plan
            .resources
            .original
            .root
            .require_distinct_live(&root)?;
        let running = Self {
            plan,
            daemon,
            root,
            closed_source,
        };
        running.require_live()?;
        Ok(running)
    }

    pub(super) fn client(&self) -> anyhow::Result<crate::AgentdClient> {
        let identity = &self.plan.administration.successor.identity;
        Ok(crate::AgentdClient::new(
            identity.control_socket.clone(),
            identity.agent_id.clone(),
            identity.spawn_generation,
        )?)
    }

    pub(super) fn require_live(&self) -> anyhow::Result<()> {
        anyhow::ensure!(
            Instant::now() < self.plan.administration.end,
            "original cold read-only deadline"
        );
        self.plan
            .original
            .daemon
            .require_distinct_live(&self.daemon)?;
        self.plan.original.root.require_distinct_live(&self.root)?;
        self.plan.original.source.require_dead()?;
        self.daemon.require_live()?;
        self.root.require_live()
    }

    pub(super) async fn promote_when_initialized(&self) -> anyhow::Result<()> {
        let client = self.client()?;
        let identity = &self.plan.administration.successor.identity;
        let mut promoted = false;
        loop {
            self.require_live()?;
            if let Ok(health) = client.health().await {
                anyhow::ensure!(
                    !health.fenced
                        && health.process_id == self.daemon.lifetime().pid
                        && health.workspace == identity.workspace
                        && health.home_root == identity.home_root
                        && health.run_root == identity.run_root,
                    "actual cold control identity differs"
                );
                if promoted && health.ready {
                    anyhow::ensure!(
                        health.lifecycle == AgentLifecycle::Running,
                        "actual cold Running readiness"
                    );
                    return self.require_live();
                }
                if !promoted && health.promotion_ready {
                    anyhow::ensure!(
                        !health.ready && health.lifecycle == AgentLifecycle::Starting,
                        "actual cold Starting readiness before promotion"
                    );
                    let registry =
                        FleetRegistry::open_existing(HeptaFleetRoot::parse(&identity.fleet_root)?)?;
                    registry.compare_and_transition(
                        &identity.agent_id,
                        identity.spawn_generation,
                        AgentLifecycle::Running,
                    )?;
                    promoted = true;
                }
            }
            self.require_live()?;
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    }

    pub(super) fn stop_after_original_readback(
        self,
    ) -> anyhow::Result<(
        OriginalColdPlan<'a>,
        ExitedOriginalProcess,
        ExitedOriginalProcess,
    )> {
        self.require_live()?;
        self.daemon.request_original_shutdown()?;
        let Self {
            plan,
            daemon,
            root,
            closed_source,
        } = self;
        let daemon = daemon.wait_success_until(plan.administration.end)?;
        let root = root.wait_success_until(plan.administration.end)?;
        drop(closed_source);
        daemon.require_dead()?;
        root.require_dead()?;
        Ok((plan, daemon, root))
    }
}

fn spawn_original_daemon(
    plan: &OriginalColdPlan<'_>,
    pairs: &[UnixDatagram],
) -> anyhow::Result<OriginalChild> {
    let identity = &plan.administration.successor.identity;
    let control = crate::bind_root_agentd_socket(&identity.control_socket, 60001, 60001)?;
    let app_server = crate::bind_root_agentd_socket(&identity.app_server_socket, 60001, 60001)?;
    let original = &plan.original.plan.resources.original.plan;
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
        .arg(&original.objective_trust)
        .arg("--authbus-checkpoint-file")
        .arg(&original.replay_checkpoint)
        .arg("--objective-profile-file")
        .arg(&original.objective_profile);
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
