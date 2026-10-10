use std::io::BufRead;
use std::io::BufReader;
use std::io::Write;
use std::os::unix::net::UnixListener;

use codex_hepta_agent_protocol::AGENTD_CONTROL_SCHEMA_VERSION;
use codex_hepta_agent_protocol::AgentdPayload;
use codex_hepta_agent_protocol::AgentdResponse;
use codex_hepta_agent_protocol::DrainSnapshot;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;

use super::AgentHealthProbeIdentity;
use super::query_agent_drain_once;
use crate::ProcessDriverError;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

fn identity(temp: &tempfile::TempDir) -> TestResult<AgentHealthProbeIdentity> {
    Ok(AgentHealthProbeIdentity {
        agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?,
        spawn_generation: 7,
        process_id: std::process::id(),
        workspace: temp.path().to_path_buf(),
        home_root: temp.path().join("home"),
        run_root: temp.path().join("run"),
        control_socket: temp.path().join("drain.sock"),
    })
}

fn exchange(
    identity: &AgentHealthProbeIdentity,
    bytes: Vec<u8>,
) -> TestResult<Result<bool, ProcessDriverError>> {
    let listener = UnixListener::bind(&identity.control_socket)?;
    let server = std::thread::spawn(move || -> std::io::Result<()> {
        let (mut stream, _) = listener.accept()?;
        let mut request = String::new();
        BufReader::new(&mut stream).read_line(&mut request)?;
        stream.write_all(&bytes)
    });
    let observed = query_agent_drain_once(identity, 17);
    let completion = server
        .join()
        .map_err(|_| std::io::Error::other("test server panic"))?;
    std::fs::remove_file(&identity.control_socket)?;
    completion?;
    Ok(observed)
}

fn acknowledgement(identity: &AgentHealthProbeIdentity) -> AgentdResponse {
    AgentdResponse {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 17,
        agent_id: identity.agent_id.clone(),
        spawn_generation: 7,
        current_generation: 9,
        payload: AgentdPayload::Drain(DrainSnapshot {
            admission_closed: true,
            running_turns: 0,
            drained: true,
            lifecycle: AgentLifecycle::Draining,
            fenced: false,
        }),
    }
}

fn frame(response: &AgentdResponse) -> TestResult<Vec<u8>> {
    let mut bytes = serde_json::to_vec(response)?;
    bytes.push(b'\n');
    Ok(bytes)
}

#[test]
fn missing_or_closed_socket_never_becomes_a_drain_acknowledgement() -> TestResult {
    let temp = tempfile::tempdir()?;
    let identity = identity(&temp)?;
    assert!(!query_agent_drain_once(&identity, 17)?);
    assert!(!exchange(&identity, Vec::new())??);
    assert!(!query_agent_drain_once(&identity, 18)?);
    Ok(())
}

#[test]
fn malformed_or_wrong_generation_drain_frames_still_reject() -> TestResult {
    let temp = tempfile::tempdir()?;
    let identity = identity(&temp)?;
    assert!(exchange(&identity, b"not-json\n".to_vec())?.is_err());
    assert!(exchange(&identity, b"{}".to_vec())?.is_err());
    let mut response = acknowledgement(&identity);
    response.current_generation = 8;
    assert!(exchange(&identity, frame(&response)?)?.is_err());
    response.current_generation = 9;
    response.request_id = 16;
    assert!(exchange(&identity, frame(&response)?)?.is_err());
    Ok(())
}

#[test]
fn only_exact_closed_admission_with_no_running_turns_is_drained() -> TestResult {
    let temp = tempfile::tempdir()?;
    let identity = identity(&temp)?;
    let response = acknowledgement(&identity);
    assert!(exchange(&identity, frame(&response)?)??);
    let mut busy = response.clone();
    if let AgentdPayload::Drain(snapshot) = &mut busy.payload {
        snapshot.running_turns = 1;
    }
    assert!(!exchange(&identity, frame(&busy)?)??);
    let mut fenced = response;
    if let AgentdPayload::Drain(snapshot) = &mut fenced.payload {
        snapshot.fenced = true;
    }
    assert!(exchange(&identity, frame(&fenced)?)?.is_err());
    Ok(())
}
