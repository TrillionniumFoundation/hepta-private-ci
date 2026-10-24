//! Actual process credential checks only. No service, issuer, writer or device
//! is started by this explicit privileged test.

use super::*;
use crate::HostAuthorityRegisteredIdentity;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;

struct ChildGuard(Child);

impl Drop for ChildGuard {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

#[test]
#[ignore = "explicit Root credential test; only the spawned child changes credentials"]
fn original_owner_process_rejects_same_uid_with_different_gid() -> Result<(), Box<dyn std::error::Error>> {
    // SAFETY: geteuid takes no pointers and reads the actual caller identity.
    assert_eq!(unsafe { libc::geteuid() }, 0, "this test requires actual Root");
    let temporary = tempfile::tempdir()?;
    let fleet = HeptaFleetRoot::parse(temporary.path().join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    let workspace = temporary.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let record = registry.register(AgentManifest::new(agent.clone(),
        WorkspaceBinding::new(workspace.clone(), &fleet)?, ResourceBudget::local_default())?)?;
    let starting = registry.compare_and_transition(&agent, record.lifecycle.generation, AgentLifecycle::Starting)?;
    for gid in [60001_u32, 60002] {
        let mut child = ChildGuard(Command::new("/usr/bin/setpriv")
            .args(["--reuid=60001", "--clear-groups", "--no-new-privs", "--inh-caps=-all",
                   "--ambient-caps=-all", "--bounding-set=-all"])
            .arg(format!("--regid={gid}")).arg("/bin/cat")
            .stdin(Stdio::piped()).stdout(Stdio::null()).stderr(Stdio::null()).spawn()?);
        let deadline = Instant::now() + Duration::from_secs(5);
        let observed = loop {
            let status = std::fs::read_to_string(format!("/proc/{}/status", child.0.id()))?;
            if status.contains("Uid:\t60001\t60001\t60001\t60001")
                && status.contains(&format!("Gid:\t{gid}\t{gid}\t{gid}\t{gid}"))
                && status.contains("NoNewPrivs:\t1")
            {
                break status;
            }
            assert!(child.0.try_wait()?.is_none(), "credential child exited before observation");
            assert!(Instant::now() < deadline, "credential transition did not complete");
            std::thread::sleep(Duration::from_millis(2));
        };
        let stat = std::fs::read_to_string(format!("/proc/{}/stat", child.0.id()))?;
        let ticks = stat.rsplit_once(") ").ok_or("invalid stat")?.1
            .split_whitespace().nth(19).ok_or("missing start ticks")?.parse()?;
        let registration = HostAuthorityRegistration {
            schema_version: 1, peer_pid: child.0.id(),
            boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim().into(),
            process_start_ticks: ticks,
            registered_identity: HostAuthorityRegisteredIdentity {
                agent_id: agent.clone(), spawn_generation: starting.generation,
                fleet_root: fleet.as_path().to_path_buf(), workspace: workspace.clone(),
                resources: record.manifest.resources.clone(),
            },
            checkpoint_owner_agent_id: agent.clone(), publisher_epoch: 1,
        };
        verify_process(&registration, /*uid*/ 60001, gid)?;
        let wrong_gid = if gid == 60001 { 60002 } else { 60001 };
        let error = verify_process(&registration, /*uid*/ 60001, wrong_gid).unwrap_err();
        assert!(error.to_string().contains("UID/GID"));
        assert!(observed.lines().any(|line| line == "CapEff:\t0000000000000000"));
        println!("ROOT_PROCESS_GID actual_pid={} uid=60001 actual_gid={gid} correct_accepted=true different_gid_rejected=true",
            child.0.id());
    }
    Ok(())
}
