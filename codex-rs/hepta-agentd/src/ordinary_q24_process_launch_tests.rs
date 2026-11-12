//! Launch the real product entry points, preserving original descriptors and
//! actual process lifetimes. No in-process Runtime or aggregate is substituted.

use std::fs::File;
use std::os::fd::AsRawFd;
use std::os::unix::net::UnixDatagram;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_paths::HeptaFleetRoot;

use super::fixture::OrdinaryAPlan;
use super::root::write_json;
use crate::ordinary_q24_process_child_tests::OriginalChild;
use crate::ordinary_q24_process_child_tests::OriginalChildDescriptors;

pub(super) struct RunningOrdinaryA {
    pub(super) plan: OrdinaryAPlan,
    pub(super) daemon: OriginalChild,
    pub(super) root: OriginalChild,
    pub(super) end: Instant,
}

impl RunningOrdinaryA {
    pub(super) fn start(plan: OrdinaryAPlan) -> anyhow::Result<Self> {
        let end = Instant::now() + Duration::from_millis(super::root::LIFETIME_MS);
        let (root_send, daemon_receive) = UnixDatagram::pair()?;
        let (initial_send, initial_receive) = UnixDatagram::pair()?;
        let control = crate::bind_root_agentd_socket(&plan.identity.control_socket, 60001, 60001)?;
        let app_server =
            crate::bind_root_agentd_socket(&plan.identity.app_server_socket, 60001, 60001)?;
        let mut command = Command::new(codex_utils_cargo_bin::cargo_bin("codex-hepta-agentd")?);
        command
            .current_dir(&plan.identity.workspace)
            .env(
                codex_hepta_paths::HEPTA_FLEET_ROOT_ENV,
                &plan.identity.fleet_root,
            )
            .env(
                crate::config::HEPTA_AGENT_ID_ENV,
                plan.identity.agent_id.as_str(),
            )
            .env(
                crate::config::HEPTA_AGENT_GENERATION_ENV,
                plan.identity.spawn_generation.to_string(),
            )
            .env(
                crate::config::HEPTA_AGENT_HOME_ENV,
                &plan.identity.home_root,
            )
            .env(
                crate::config::HEPTA_AGENT_RUN_ROOT_ENV,
                &plan.identity.run_root,
            )
            .env("CODEX_HOME", &plan.identity.home_root)
            .args(["--root-production-profile", "q24-initial"])
            .args([
                "--root-production-uid",
                "60001",
                "--root-production-gid",
                "60001",
            ])
            .arg("--root-production-lifetime-ms")
            .arg(super::root::LIFETIME_MS.to_string())
            .arg("--root-production-handoff-fd")
            .arg(daemon_receive.as_raw_fd().to_string())
            .arg("--root-generation-initial-handoff-fd")
            .arg(initial_receive.as_raw_fd().to_string())
            .arg("--q24-initial-deployment-fd")
            .arg(plan.sealed.as_raw_fd().to_string())
            .arg("--root-production-control-fd")
            .arg(control.as_raw_fd().to_string())
            .arg("--root-production-app-server-fd")
            .arg(app_server.as_raw_fd().to_string())
            .arg("--authbus-trust-file")
            .arg(&plan.objective_trust)
            .arg("--authbus-checkpoint-file")
            .arg(&plan.replay_checkpoint)
            .arg("--objective-profile-file")
            .arg(&plan.objective_profile);
        let daemon = OriginalChild::spawn(
            &mut command,
            OriginalChildDescriptors {
                inherited: vec![
                    daemon_receive.as_raw_fd(),
                    initial_receive.as_raw_fd(),
                    plan.sealed.as_raw_fd(),
                    control.as_raw_fd(),
                    app_server.as_raw_fd(),
                ],
                own_pidfd_slot: None,
            },
        )?;
        drop((control, app_server, daemon_receive, initial_receive));
        loop {
            daemon.require_live()?;
            anyhow::ensure!(
                Instant::now() < end,
                "actual daemon credential transition deadline"
            );
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
        let registration = crate::HostAuthorityRegistration {
            schema_version: 1,
            peer_pid: daemon.lifetime().pid,
            boot_id: daemon.lifetime().boot_id.clone(),
            process_start_ticks: daemon.lifetime().start_ticks,
            registered_identity: plan.registered.clone(),
            checkpoint_owner_agent_id: plan.identity.agent_id.clone(),
            publisher_epoch: 1,
        };
        write_json(&plan.root.registration, &registration)?;
        let own_pidfd = tempfile::tempfile()?;
        let mut command = Command::new(codex_utils_cargo_bin::cargo_bin("hepta-authority-host")?);
        command
            .arg("serve-fresh-session")
            .arg("--config")
            .arg(&plan.root.service)
            .arg("--registration")
            .arg(&plan.root.registration)
            .arg("--owner-pidfd-stdin")
            .stdin(File::from(daemon.original_pidfd()?))
            .arg("--root-handoff-fd")
            .arg(root_send.as_raw_fd().to_string())
            .arg("--root-pidfd")
            .arg(own_pidfd.as_raw_fd().to_string())
            .arg("--generation-initial-deployment")
            .arg(&plan.root.initial)
            .arg("--root-generation-initial-handoff-fd")
            .arg(initial_send.as_raw_fd().to_string())
            .arg("--historical-source-deployment")
            .arg(&plan.root.source)
            .arg("--run-start-deployment")
            .arg(&plan.root.run_start)
            // Product readiness on this exact Initial socket, after A opens
            // its owners. Never invoke the component file-trigger helper.
            .arg("--initial-peer-ready");
        let root = OriginalChild::spawn(
            &mut command,
            OriginalChildDescriptors {
                inherited: vec![root_send.as_raw_fd(), initial_send.as_raw_fd()],
                own_pidfd_slot: Some(own_pidfd.as_raw_fd()),
            },
        )?;
        drop((root_send, initial_send, own_pidfd));
        Ok(Self {
            plan,
            daemon,
            root,
            end,
        })
    }

    pub(super) fn client(&self) -> anyhow::Result<crate::AgentdClient> {
        Ok(crate::AgentdClient::new(
            self.plan.identity.control_socket.clone(),
            self.plan.identity.agent_id.clone(),
            self.plan.identity.spawn_generation,
        )?)
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
                        "original Starting readiness required before supervisor promotion"
                    );
                    break;
                }
            }
            self.require_live()?;
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        let registry = FleetRegistry::open_existing(HeptaFleetRoot::parse(
            self.plan.identity.fleet_root.clone(),
        )?)?;
        registry.compare_and_transition(
            &self.plan.identity.agent_id,
            self.plan.identity.spawn_generation,
            AgentLifecycle::Running,
        )?;
        loop {
            self.require_live()?;
            if let Ok(health) = client.health().await {
                self.require_health_identity(&health)?;
                if health.ready {
                    anyhow::ensure!(
                        health.lifecycle == AgentLifecycle::Running,
                        "actual Running readiness"
                    );
                    return self.require_live();
                }
            }
            self.require_live()?;
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    }

    pub(super) fn require_live(&self) -> anyhow::Result<()> {
        anyhow::ensure!(
            Instant::now() < self.end,
            "original ordinary process phase deadline"
        );
        self.daemon.require_live()?;
        self.root.require_live()
    }

    fn require_health_identity(&self, health: &crate::HealthSnapshot) -> anyhow::Result<()> {
        anyhow::ensure!(
            !health.fenced
                && health.process_id == self.daemon.lifetime().pid
                && health.workspace == self.plan.identity.workspace
                && health.home_root == self.plan.identity.home_root
                && health.run_root == self.plan.identity.run_root,
            "actual ordinary health identity/current differs"
        );
        Ok(())
    }
}
