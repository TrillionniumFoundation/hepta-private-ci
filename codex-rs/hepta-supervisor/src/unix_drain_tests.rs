use std::io::BufRead;
use std::io::BufReader;
use std::io::Write;
use std::os::unix::net::UnixListener;
use std::os::unix::net::UnixStream;

use codex_hepta_agent_protocol::AGENTD_CONTROL_SCHEMA_VERSION;
use codex_hepta_agent_protocol::AgentdPayload;
use codex_hepta_agent_protocol::AgentdResponse;
use codex_hepta_agent_protocol::DrainSnapshot;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use pretty_assertions::assert_eq;

use super::AgentHealthProbeIdentity;
use super::DrainIoError;
use super::decode_agent_drain_response;
use super::drain_io_error;
use super::query_agent_drain_once;
use super::read_agent_drain_response;
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

// The response is fully written and the peer is already closed before the
// client reads. No thread timing, sleep, retry or half-close is needed to reach
// the transport state in which a valid reply must still be consumed.
fn closed_peer_response(bytes: &[u8]) -> TestResult<Vec<u8>> {
    let (client, mut peer) = UnixStream::pair()?;
    peer.write_all(bytes)?;
    drop(peer);
    Ok(read_agent_drain_response(client)?)
}

#[test]
fn completed_reply_survives_peer_close_before_response_read() -> TestResult {
    let temp = tempfile::tempdir()?;
    let identity = identity(&temp)?;
    let expected = frame(&acknowledgement(&identity))?;
    let observed = closed_peer_response(&expected)?;
    assert_eq!(observed, expected);
    assert!(decode_agent_drain_response(
        &identity, /*request_id*/ 17, &observed
    )?);
    Ok(())
}

#[test]
fn closed_peer_does_not_bypass_frame_or_generation_validation() -> TestResult {
    let temp = tempfile::tempdir()?;
    let identity = identity(&temp)?;
    let empty = closed_peer_response(b"")?;
    assert!(!decode_agent_drain_response(
        &identity, /*request_id*/ 17, &empty
    )?);
    for bytes in [b"not-json\n".as_slice(), b"{}".as_slice()] {
        let observed = closed_peer_response(bytes)?;
        assert!(decode_agent_drain_response(&identity, /*request_id*/ 17, &observed).is_err());
    }
    let mut wrong = acknowledgement(&identity);
    wrong.current_generation = 8;
    let observed = closed_peer_response(&frame(&wrong)?)?;
    assert!(decode_agent_drain_response(&identity, /*request_id*/ 17, &observed).is_err());
    Ok(())
}

#[test]
fn transport_context_retains_error_kind_and_original_errno() -> TestResult {
    for code in [libc::EACCES, libc::ENOTCONN, libc::ECONNRESET] {
        let original = std::io::Error::from_raw_os_error(code);
        let original_kind = original.kind();
        let original_text = original.to_string();
        let error = drain_io_error("read_response", original);
        assert_eq!(error.kind(), original_kind);
        assert_eq!(
            error.to_string(),
            format!("Agentd drain read_response: {original_text}")
        );
        let source = error
            .get_ref()
            .and_then(|value| value.downcast_ref::<DrainIoError>())
            .ok_or_else(|| std::io::Error::other("missing original drain error"))?;
        assert_eq!(source.source.raw_os_error(), Some(code));
    }
    Ok(())
}
