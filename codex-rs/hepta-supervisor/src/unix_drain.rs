//! One bounded Agentd drain request and a fully validated response.
//! Request framing is newline based; it does not require a successful half-close.

use std::io::BufRead;
use std::io::BufReader;
use std::io::Read;
use std::io::Write;
use std::os::unix::net::UnixStream;

use codex_hepta_agent_protocol::AGENTD_CONTROL_SCHEMA_VERSION;
use codex_hepta_agent_protocol::AgentdPayload;
use codex_hepta_agent_protocol::AgentdRequest;
use codex_hepta_agent_protocol::AgentdResponse;
use codex_hepta_agent_protocol::MAX_CONTROL_FRAME_BYTES;
use codex_hepta_fleet::AgentLifecycle;

use super::AgentHealthProbeIdentity;
use super::HEALTH_PROBE_IO_TIMEOUT;
use crate::ProcessDriverError;

// Preserve classification and the original error as a source while naming the
// failing transport stage. This introduces no new retry or accepted error kind.
#[derive(Debug, thiserror::Error)]
#[error("Agentd drain {stage}: {source}")]
struct DrainIoError {
    stage: &'static str,
    #[source]
    source: std::io::Error,
}

fn drain_io_error(stage: &'static str, source: std::io::Error) -> std::io::Error {
    std::io::Error::new(source.kind(), DrainIoError { stage, source })
}

fn read_agent_drain_response(stream: UnixStream) -> std::io::Result<Vec<u8>> {
    let mut reader = BufReader::new(stream).take(MAX_CONTROL_FRAME_BYTES + 1);
    let mut response = Vec::new();
    reader
        .read_until(b'\n', &mut response)
        .map_err(|error| drain_io_error("read_response", error))?;
    Ok(response)
}

fn read_agent_drain_frame(
    identity: &AgentHealthProbeIdentity,
    request: &[u8],
) -> std::io::Result<Vec<u8>> {
    let mut stream = UnixStream::connect(&identity.control_socket)
        .map_err(|error| drain_io_error("connect", error))?;
    stream
        .set_read_timeout(Some(HEALTH_PROBE_IO_TIMEOUT))
        .map_err(|error| drain_io_error("set_read_timeout", error))?;
    stream
        .set_write_timeout(Some(HEALTH_PROBE_IO_TIMEOUT))
        .map_err(|error| drain_io_error("set_write_timeout", error))?;
    stream
        .write_all(request)
        .map_err(|error| drain_io_error("write_request", error))?;
    // Both peers use a bounded newline frame. Do not insert a write-half-close
    // between the complete request and a response the peer may already have sent.
    read_agent_drain_response(stream)
}

pub(super) fn query_agent_drain_once(
    identity: &AgentHealthProbeIdentity,
    request_id: u64,
) -> Result<bool, ProcessDriverError> {
    let request = AgentdRequest::drain(request_id, identity.spawn_generation);
    let mut bytes = serde_json::to_vec(&request)?;
    bytes.push(b'\n');
    if bytes.len() as u64 > MAX_CONTROL_FRAME_BYTES {
        return Err(ProcessDriverError::new(
            "Agentd drain request exceeded the bounded control frame",
        ));
    }
    let response_bytes = match read_agent_drain_frame(identity, &bytes) {
        Ok(response) => response,
        Err(error)
            if matches!(
                error.kind(),
                std::io::ErrorKind::NotFound
                    | std::io::ErrorKind::ConnectionRefused
                    | std::io::ErrorKind::ConnectionReset
                    | std::io::ErrorKind::ConnectionAborted
                    | std::io::ErrorKind::BrokenPipe
                    | std::io::ErrorKind::TimedOut
                    | std::io::ErrorKind::WouldBlock
                    | std::io::ErrorKind::UnexpectedEof
                    | std::io::ErrorKind::Interrupted
            ) =>
        {
            // Shutdown can remove the control socket before waitpid sees exit.
            // No response is NOT a drain acknowledgement. Preserve the existing
            // deadline/escalation path instead of aborting lifecycle observation.
            return Ok(false);
        }
        Err(error) => return Err(error.into()),
    };
    decode_agent_drain_response(identity, request_id, &response_bytes)
}

fn decode_agent_drain_response(
    identity: &AgentHealthProbeIdentity,
    request_id: u64,
    response_bytes: &[u8],
) -> Result<bool, ProcessDriverError> {
    if response_bytes.is_empty() {
        return Ok(false);
    }
    if response_bytes.len() as u64 > MAX_CONTROL_FRAME_BYTES || !response_bytes.ends_with(b"\n") {
        return Err(ProcessDriverError::new(
            "Agentd drain response was not a bounded complete frame",
        ));
    }
    let response: AgentdResponse = serde_json::from_slice(response_bytes)?;
    let exact_envelope = response.schema_version == AGENTD_CONTROL_SCHEMA_VERSION
        && response.request_id == request_id
        && response.agent_id == identity.agent_id
        && response.spawn_generation == identity.spawn_generation
        && identity
            .spawn_generation
            .checked_add(2)
            .is_some_and(|generation| response.current_generation == generation);
    let AgentdPayload::Drain(snapshot) = response.payload else {
        return Err(ProcessDriverError::new(
            "Agentd drain request did not return a drain acknowledgement",
        ));
    };
    if !exact_envelope
        || snapshot.lifecycle != AgentLifecycle::Draining
        || snapshot.fenced
        || !snapshot.admission_closed
    {
        return Err(ProcessDriverError::new(
            "Agentd drain acknowledgement did not bind the current draining generation",
        ));
    }
    Ok(snapshot.drained && snapshot.running_turns == 0)
}

#[cfg(test)]
#[path = "unix_drain_tests.rs"]
mod tests;
