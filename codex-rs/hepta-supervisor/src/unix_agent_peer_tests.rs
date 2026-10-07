use std::io::Read;
use std::os::unix::net::UnixListener;

use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

use super::AgentHealthProbeIdentity;
use super::query_agent_drain_once;
use super::query_agent_health_once;

type TestResult = Result<(), Box<dyn std::error::Error>>;

enum AgentProbe {
    Health,
    Drain,
}

fn reject_wrong_live_peer(probe: AgentProbe) -> TestResult {
    let temp = tempfile::Builder::new()
        .prefix("hpeer-")
        .tempdir_in("/tmp")?;
    let socket = temp.path().join("agent.sock");
    let listener = UnixListener::bind(&socket)?;
    let mut identity = AgentHealthProbeIdentity {
        agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?,
        spawn_generation: 7,
        process_id: std::process::id(),
        workspace: temp.path().to_path_buf(),
        home_root: temp.path().join("home"),
        run_root: temp.path().join("run"),
        control_socket: socket,
    };
    let mut unrelated = std::process::Command::new("/bin/sleep").arg("30").spawn()?;
    identity.process_id = unrelated.id();
    let worker = std::thread::spawn(move || -> std::io::Result<Vec<u8>> {
        let (mut stream, _) = listener.accept()?;
        stream.set_read_timeout(Some(super::HEALTH_PROBE_IO_TIMEOUT))?;
        let mut request = Vec::new();
        stream.read_to_end(&mut request)?;
        Ok(request)
    });
    let result = match probe {
        AgentProbe::Health => query_agent_health_once(&identity, /*request_id*/ 19).map(|_| ()),
        AgentProbe::Drain => query_agent_drain_once(&identity, /*request_id*/ 19).map(|_| ()),
    };
    let still_running = unrelated.try_wait()?.is_none();
    unrelated.kill()?;
    unrelated.wait()?;
    let request = worker
        .join()
        .map_err(|_| std::io::Error::other("peer fixture thread panicked"))??;
    assert_eq!(
        result.err().map(|error| error.to_string()),
        Some("control socket peer does not match the expected process and owner".to_string())
    );
    assert_eq!(request, Vec::<u8>::new());
    assert!(
        still_running,
        "rejection must not signal the claimed process"
    );
    Ok(())
}

#[test]
fn agent_health_rejects_same_owner_wrong_live_process_before_sending_request() -> TestResult {
    reject_wrong_live_peer(AgentProbe::Health)
}

#[test]
fn agent_drain_rejects_same_owner_wrong_live_process_before_sending_request() -> TestResult {
    reject_wrong_live_peer(AgentProbe::Drain)
}
