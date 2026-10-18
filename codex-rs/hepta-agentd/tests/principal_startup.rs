#![cfg(all(feature = "server", target_os = "linux"))]
#![allow(clippy::expect_used, clippy::unwrap_used)]
//! The ordinary Agentd image must start with real private, distinct Linux UIDs.
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_agent_components::contracts::AgentId;
use codex_hepta_agent_components::fleet::AgentLifecycle;
use codex_hepta_agent_components::fleet::AgentManifest;
use codex_hepta_agent_components::fleet::FleetRegistry;
use codex_hepta_agent_components::fleet::ResourceBudget;
use codex_hepta_agent_components::fleet::WorkspaceBinding;
use codex_hepta_agent_components::paths::HeptaFleetRoot;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::MemoryFederationScopeKind;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

const GID: u32 = 65534;
const TEST: &str = "distinct_private_workload_uids_start_complete_real_agentd_processes";

fn permissions(path: &Path, uid: u32, mode: u32) -> Result<()> {
    fs::set_permissions(path, fs::Permissions::from_mode(mode))?;
    std::os::unix::fs::chown(path, Some(uid), Some(GID))?;
    Ok(())
}

fn tree_permissions(path: &Path, uid: u32, directory_mode: u32, file_mode: u32) -> Result<()> {
    permissions(path, uid, directory_mode)?;
    for entry in fs::read_dir(path)? {
        let path = entry?.path();
        if path.is_dir() {
            tree_permissions(&path, uid, directory_mode, file_mode)?;
        } else {
            permissions(&path, uid, file_mode)?;
        }
    }
    Ok(())
}

struct Process(Child);

impl Drop for Process {
    fn drop(&mut self) {
        // These handles refer only to this fixture's children. Join on every
        // failure path before the root-owned temporary namespace is removed.
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

impl Process {
    fn stop(&mut self) -> Result<()> {
        ensure!(unsafe { libc::kill(self.0.id() as i32, libc::SIGTERM) } == 0);
        let deadline = Instant::now() + Duration::from_secs(15);
        loop {
            if let Some(status) = self.0.try_wait()? {
                ensure!(
                    status.success(),
                    "Agentd graceful shutdown failed: {status}"
                );
                return Ok(());
            }
            ensure!(Instant::now() < deadline, "Agentd shutdown deadline");
            std::thread::sleep(Duration::from_millis(20));
        }
    }
}

#[tokio::test]
#[ignore = "requires sudo: actual two Linux UIDs and ordinary Agentd processes"]
async fn distinct_private_workload_uids_start_complete_real_agentd_processes() -> Result<()> {
    let binary = codex_utils_cargo_bin::cargo_bin("codex-hepta-agentd")?;
    if unsafe { libc::geteuid() } != 0 {
        let output = Command::new("sudo")
            .args(["-n", "env"])
            .arg(format!(
                "CARGO_BIN_EXE_codex-hepta-agentd={}",
                binary.display()
            ))
            .arg(std::env::current_exe()?)
            .args(["--exact", TEST, "--ignored", "--nocapture"])
            .output()?;
        ensure!(
            output.status.success() && String::from_utf8_lossy(&output.stdout).contains("1 passed"),
            "real root qualification failed: {} {}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        return Ok(());
    }
    let temp = tempfile::Builder::new()
        .prefix("hepta-uid-boot-")
        .tempdir_in("/var/lib")?;
    permissions(temp.path(), /*uid*/ 0, /*mode*/ 0o755)?;
    let image = temp.path().join("codex-hepta-agentd");
    fs::copy(binary, &image)?;
    permissions(&image, /*uid*/ 0, /*mode*/ 0o555)?;
    let fleet = HeptaFleetRoot::parse(temp.path().join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    let mut fixtures = Vec::new();
    for (suffix, uid) in [(1, 65532), (2, 65531)] {
        let id = AgentId::parse(format!("00000000-0000-4000-8000-{suffix:012x}"))?;
        let workspace = temp.path().join(format!("workspace-{suffix}"));
        fs::create_dir(&workspace)?;
        let record = registry.register(AgentManifest::new(
            id.clone(),
            WorkspaceBinding::new(&workspace, &fleet)?,
            ResourceBudget::local_default(),
        )?)?;
        registry.compare_and_transition(
            &id,
            /*expected_generation*/ 0,
            AgentLifecycle::Starting,
        )?;
        permissions(&workspace, uid, /*mode*/ 0o700)?;
        let layout = record.layout;
        tree_permissions(
            layout.agent_root(),
            /*uid*/ 0,
            /*directory_mode*/ 0o750,
            /*file_mode*/ 0o640,
        )?;
        for path in [
            layout.home_root(),
            layout.run_root(),
            layout.logs_root(),
            layout.cognitive_root(),
            layout.matrix_root(),
            layout.automation_root(),
        ] {
            tree_permissions(
                path, uid, /*directory_mode*/ 0o700, /*file_mode*/ 0o600,
            )?;
        }
        let private = layout.home_root().join("private-test-evidence");
        fs::write(&private, id.as_str())?;
        permissions(&private, uid, /*mode*/ 0o600)?;
        let socket_parent = layout.agentd_control_socket().parent().unwrap();
        fs::create_dir(socket_parent)?;
        permissions(socket_parent, uid, /*mode*/ 0o700)?;
        fixtures.push((id, uid, workspace, layout));
    }
    for path in [
        fleet.as_path(),
        registry.layout().run_root(),
        registry.layout().releases_root(),
        registry.layout().agents_root(),
    ] {
        permissions(path, /*uid*/ 0, /*mode*/ 0o750)?;
    }
    permissions(
        registry.layout().state_root(),
        /*uid*/ 0,
        /*mode*/ 0o700,
    )?;
    let mut children = Vec::new();
    for (id, uid, workspace, layout) in &fixtures {
        let log = temp.path().join(format!("{uid}.stderr"));
        let child = Command::new("/usr/bin/setpriv")
            .args([
                "--reuid",
                &uid.to_string(),
                "--regid",
                &GID.to_string(),
                "--clear-groups",
            ])
            .arg(&image)
            .current_dir(workspace)
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .env("HOME", layout.home_root())
            .env("CODEX_HOME", layout.home_root())
            .env("HEPTA_FLEET_ROOT", fleet.as_path())
            .env("HEPTA_AGENT_ID", id.as_str())
            .env("HEPTA_AGENT_GENERATION", "1")
            .env("HEPTA_AGENT_HOME", layout.home_root())
            .env("HEPTA_AGENT_RUN_ROOT", layout.run_root())
            .stdout(Stdio::null())
            .stderr(fs::File::create(&log)?)
            .spawn()?;
        children.push((Process(child), log));
    }
    for ((id, uid, workspace, layout), (child, log)) in fixtures.iter().zip(&mut children) {
        let client = AgentdClient::new(
            layout.agentd_control_socket().to_path_buf(),
            id.clone(),
            /*spawn_generation*/ 1,
        )?;
        let deadline = Instant::now() + Duration::from_secs(60);
        let health = loop {
            ensure!(
                child.0.try_wait()?.is_none(),
                "UID {uid} Agentd exited before readiness: {}",
                fs::read_to_string(log)?
            );
            if let Ok(health) = client.health().await {
                if health.ready {
                    break health;
                }
                if health.promotion_ready {
                    registry.compare_and_transition(
                        id,
                        /*expected_generation*/ 1,
                        AgentLifecycle::Running,
                    )?;
                }
            }
            ensure!(
                Instant::now() < deadline,
                "UID {uid} readiness deadline: {}",
                fs::read_to_string(log)?
            );
            tokio::time::sleep(Duration::from_millis(20)).await;
        };
        ensure!(
            health.process_id == child.0.id()
                && health.workspace == *workspace
                && health.home_root == layout.home_root()
        );
        let status = fs::read_to_string(format!("/proc/{}/status", child.0.id()))?;
        ensure!(status.lines().any(|line| {
            line.starts_with("Uid:")
                && line
                    .split_whitespace()
                    .skip(1)
                    .all(|value| value == uid.to_string())
        }));
        ensure!(client.session_ingress().await?.socket_path == layout.app_server_socket());
        ensure!(
            AgentdClient::new(
                layout.agentd_control_socket().to_path_buf(),
                id.clone(),
                /*spawn_generation*/ 2
            )?
            .health()
            .await
            .is_err(),
            "stale spawn fence accepted"
        );
    }
    // The grant owner reads only its chosen consumer's public registration;
    // private peer geometry and journals are inaccessible to its workload UID.
    let source = AgentdClient::new(
        fixtures[0].3.agentd_control_socket().to_path_buf(),
        fixtures[0].0.clone(),
        /*spawn_generation*/ 1,
    )?;
    let capability = source
        .memory_federation_grant(
            fixtures[1].0.clone(),
            MemoryFederationScopeKind::AgentPrivate,
            /*lifetime_seconds*/ 60,
        )
        .await?;
    source
        .memory_federation_revoke(capability.capability_id)
        .await?;
    ensure!(
        source
            .memory_federation_grant(
                fixtures[0].0.clone(),
                MemoryFederationScopeKind::AgentPrivate,
                /*lifetime_seconds*/ 60
            )
            .await
            .is_err()
    );
    for index in 0..2 {
        let (_, uid, _, own) = &fixtures[index];
        let (_, _, _, peer) = &fixtures[1 - index];
        let script = "import os,sys;assert open(sys.argv[1]).read()==sys.argv[4]\ntry:open(sys.argv[2]).read();raise AssertionError('peer private file accessible')\nexcept PermissionError:pass\ntry:os.kill(int(sys.argv[3]),0);raise AssertionError('peer signal allowed')\nexcept PermissionError:pass";
        let output = Command::new("/usr/bin/setpriv")
            .args([
                "--reuid",
                &uid.to_string(),
                "--regid",
                &GID.to_string(),
                "--clear-groups",
                "/usr/bin/python3",
                "-c",
                script,
            ])
            .arg(own.home_root().join("private-test-evidence"))
            .arg(peer.home_root().join("private-test-evidence"))
            .arg(children[1 - index].0.0.id().to_string())
            .arg(fixtures[index].0.as_str())
            .output()?;
        ensure!(
            output.status.success(),
            "actual UID {uid} isolation denial failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }
    for (child, _) in &mut children {
        child.stop().context("join real Agentd")?;
    }
    ensure!(
        registry.load()?.agents.len() == 2,
        "Supervisor global audit changed"
    );
    Ok(())
}
