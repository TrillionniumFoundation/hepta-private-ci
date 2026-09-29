#![cfg(all(unix, feature = "qualification"))]

use std::os::unix::process::ExitStatusExt;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_supervisor::inspect_qualification_crash_probe;
use codex_hepta_supervisor::publish_qualification_crash_probe;

const CHILD_TEST: &str = "sigkill_child_publishes_actual_supervisor_journals";
const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

#[test]
fn actual_sigkill_preserves_lease_restart_intent_and_transaction() -> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let run_root = temp.path().join("agent-run");
    let ready = temp.path().join("ready");
    let mut child = Command::new(std::env::current_exe()?)
        .arg("--ignored")
        .arg("--exact")
        .arg(CHILD_TEST)
        .arg("--nocapture")
        .env("HEPTA_SUPERVISOR_CRASH_PROBE_ROOT", &run_root)
        .env("HEPTA_SUPERVISOR_CRASH_PROBE_READY", &ready)
        .spawn()?;

    let deadline = Instant::now() + Duration::from_secs(10);
    while !ready.exists() {
        if let Some(status) = child.try_wait()? {
            return Err(format!("crash probe exited before SIGKILL: {status}").into());
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            return Err("crash probe did not publish readiness".into());
        }
        std::thread::sleep(Duration::from_millis(10));
    }

    // SAFETY: child.id() is the live subprocess spawned above and SIGKILL has
    // no pointer or aliasing requirements.
    let result = unsafe { libc::kill(child.id() as i32, libc::SIGKILL) };
    if result != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    let status = child.wait()?;
    assert_eq!(status.signal(), Some(libc::SIGKILL));

    let agent_id = AgentId::parse(AGENT_ID)?;
    let receipt = inspect_qualification_crash_probe(&run_root, &agent_id)?;
    assert!(receipt.process_lease_valid);
    assert!(receipt.restart_pending);
    Ok(())
}

#[test]
#[ignore = "spawned only by the SIGKILL parent test"]
fn sigkill_child_publishes_actual_supervisor_journals() -> Result<(), Box<dyn std::error::Error>> {
    let run_root = std::env::var_os("HEPTA_SUPERVISOR_CRASH_PROBE_ROOT")
        .map(std::path::PathBuf::from)
        .ok_or("missing crash probe root")?;
    let ready = std::env::var_os("HEPTA_SUPERVISOR_CRASH_PROBE_READY")
        .map(std::path::PathBuf::from)
        .ok_or("missing crash probe ready path")?;
    let agent_id = AgentId::parse(AGENT_ID)?;
    publish_qualification_crash_probe(&run_root, agent_id)?;
    let file = std::fs::File::create(&ready)?;
    file.sync_all()?;
    std::fs::File::open(ready.parent().ok_or("ready path has no parent")?)?.sync_all()?;
    loop {
        std::thread::sleep(Duration::from_secs(60));
    }
}
