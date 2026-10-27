use super::*;
use pretty_assertions::assert_eq;
use std::os::unix::net::UnixStream;

struct PairCleanup {
    fleet: Option<PairFleet>,
}

impl Drop for PairCleanup {
    fn drop(&mut self) {
        if let Some(fleet) = self.fleet.as_mut()
            && let Err(error) = fleet.shutdown()
        {
            eprintln!("connection fixture cleanup failed: {error:#}");
        }
    }
}

#[test]
fn rejected_envelopes_leave_the_same_child_serving_current_health() -> Result<()> {
    let _pair_product_test_guard = PAIR_PRODUCT_TEST_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let mut cleanup = PairCleanup {
        fleet: Some(PairFleet::new(1)?),
    };
    let fixture = cleanup.fleet.as_mut().context("pair fixture")?;
    fixture.start_all()?;
    fixture.wait_ready(Duration::from_secs(60))?;
    let agent_id = fixture.agents[0].clone();
    let before = fixture.pair_runtime_fence(&agent_id)?;
    let record = fixture
        .registry
        .load()?
        .agent(&agent_id)
        .cloned()
        .context("agent record")?;
    let stale_spawn = before
        .spawn_generation
        .checked_sub(1)
        .context("a prior spawn generation")?;
    let mut unsupported_schema = AgentdRequest::health(3, before.spawn_generation);
    unsupported_schema.schema_version += 1;
    for (request, code, message) in [
        (
            AgentdRequest::health(1, stale_spawn),
            "request_rejected",
            format!(
                "agentd generation fenced: request spawn generation {stale_spawn} does not match {}",
                before.spawn_generation
            ),
        ),
        (
            unsupported_schema,
            "unsupported_schema",
            "unsupported agentd control schema".to_string(),
        ),
    ] {
        let current = AgentdRequest::health(request.request_id + 1, before.spawn_generation);
        let rejected = AgentdResponse {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id: request.request_id,
            agent_id: agent_id.clone(),
            spawn_generation: before.spawn_generation,
            current_generation: request.spawn_generation,
            payload: AgentdPayload::Error {
                code: code.to_string(),
                message,
            },
        };
        let healthy = AgentdResponse {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id: current.request_id,
            agent_id: agent_id.clone(),
            spawn_generation: before.spawn_generation,
            current_generation: before.runtime_generation,
            payload: AgentdPayload::Health(HealthSnapshot {
                promotion_ready: true,
                ready: true,
                fenced: false,
                lifecycle: AgentLifecycle::Running,
                process_id: u32::try_from(before.agent_pid)?,
                workspace: record.manifest.workspace.as_path().to_path_buf(),
                home_root: record.layout.home_root().to_path_buf(),
                run_root: record.layout.run_root().to_path_buf(),
            }),
        };
        // Do not tick the Supervisor between requests: a restarted child must
        // not conceal a connection-level rejection that killed the old child.
        for (request, expected) in [(request, rejected), (current, healthy)] {
            let mut stream = UnixStream::connect(record.layout.agentd_control_socket())?;
            stream.set_read_timeout(Some(Duration::from_secs(3)))?;
            stream.set_write_timeout(Some(Duration::from_secs(3)))?;
            serde_json::to_writer(&mut stream, &request)?;
            stream.write_all(b"\n")?;
            let mut bytes = Vec::new();
            BufReader::new(stream).read_until(b'\n', &mut bytes)?;
            let response: AgentdResponse = serde_json::from_slice(&bytes)?;
            assert_eq!(response, expected);
        }
    }
    fixture.shutdown()?;
    cleanup.fleet = None;
    Ok(())
}
