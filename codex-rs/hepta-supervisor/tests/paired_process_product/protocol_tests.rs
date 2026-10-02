use std::io::BufRead;
use std::io::BufReader;
use std::io::Write;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use anyhow::Context;
use anyhow::Result;
use codex_hepta_agent_protocol::AgentdPayload;
use codex_hepta_agent_protocol::AgentdRequest;
use codex_hepta_agent_protocol::AgentdResponse;
use codex_hepta_matrix_protocol::MATRIXD_CONTROL_SCHEMA_VERSION;
use codex_hepta_matrix_protocol::MatrixdMethod;
use codex_hepta_matrix_protocol::MatrixdPayload;
use codex_hepta_matrix_protocol::MatrixdRequest;
use codex_hepta_matrix_protocol::MatrixdResponse;
use serde::Serialize;
use serde::de::DeserializeOwned;

use super::PAIR_PRODUCT_TEST_LOCK;
use super::PairFleet;

#[test]
fn paired_child_methods_and_exact_drain_use_real_protocol_validation() -> Result<()> {
    let _guard = PAIR_PRODUCT_TEST_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let mut fixture = PairFleet::new(1)?;
    fixture.start_all()?;
    fixture.wait_ready(Duration::from_secs(30))?;
    let agent = fixture.agents[0].clone();
    let fence = fixture.pair_runtime_fence(&agent)?;
    let record = fixture
        .registry
        .load()?
        .agent(&agent)
        .cloned()
        .context("agent")?;
    let agent_socket = record.layout.agentd_control_socket();

    let health: AgentdResponse = exchange(
        agent_socket,
        &AgentdRequest::health(1, fence.spawn_generation),
    )?;
    anyhow::ensure!(
        health.agent_id == agent
            && health.current_generation == fence.runtime_generation
            && matches!(health.payload, AgentdPayload::Health(ref value) if value.ready),
        "real Agentd health response did not bind the running child"
    );
    for request in [
        AgentdRequest::lifecycle(2, fence.spawn_generation),
        AgentdRequest::drain(3, fence.spawn_generation),
        AgentdRequest::drain(4, fence.spawn_generation + 1),
    ] {
        let response: AgentdResponse = exchange(agent_socket, &request)?;
        anyhow::ensure!(
            response.request_id == request.request_id
                && response.agent_id == agent
                && matches!(response.payload, AgentdPayload::Error { .. }),
            "unsupported, premature or stale request was acknowledged"
        );
    }

    let matrix_socket = record.layout.matrixd_control_socket();
    for (request_id, method) in [
        (5, MatrixdMethod::Health),
        (6, MatrixdMethod::Snapshot),
        (
            7,
            MatrixdMethod::Events {
                after_cursor: 0,
                limit: 1,
            },
        ),
    ] {
        let is_health = method == MatrixdMethod::Health;
        let request = MatrixdRequest {
            schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
            request_id,
            agent_id: agent.clone(),
            fence: None,
            method,
        };
        let response: MatrixdResponse = exchange(matrix_socket, &request)?;
        response.validate()?;
        anyhow::ensure!(
            response.request_id == request_id && response.agent_id == agent,
            "Matrix response identity changed"
        );
        anyhow::ensure!(
            matches!(response.payload, MatrixdPayload::Health(_)) == is_health
                && (is_health || matches!(response.payload, MatrixdPayload::Error { .. })),
            "Matrix fixture returned success for an unsupported method"
        );
    }

    // This invokes UnixProcessDriver's actual exact-generation drain verifier;
    // a Health reply or unbound Drain acknowledgement fails the tick contract.
    fixture
        .supervisor
        .as_mut()
        .context("supervisor")?
        .drain(&agent, Instant::now())?;
    fixture.wait_agents_inactive(std::slice::from_ref(&agent), Duration::from_secs(30))?;
    fixture.shutdown()?;
    Ok(())
}

fn exchange<Request: Serialize, Response: DeserializeOwned>(
    socket: &Path,
    request: &Request,
) -> Result<Response> {
    let mut stream = UnixStream::connect(socket)?;
    stream.set_read_timeout(Some(Duration::from_secs(5)))?;
    stream.set_write_timeout(Some(Duration::from_secs(5)))?;
    serde_json::to_writer(&mut stream, request)?;
    stream.write_all(b"\n")?;
    let mut response = Vec::new();
    BufReader::new(stream).read_until(b'\n', &mut response)?;
    Ok(serde_json::from_slice(&response)?)
}
