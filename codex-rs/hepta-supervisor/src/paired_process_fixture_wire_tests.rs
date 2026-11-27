use anyhow::Result;
use codex_hepta_agent_protocol::AGENTD_CONTROL_SCHEMA_VERSION;
use codex_hepta_agent_protocol::AgentdMethod as ProtocolMethod;
use codex_hepta_agent_protocol::AgentdPayload as ProtocolPayload;
use codex_hepta_agent_protocol::AgentdRequest as ProtocolRequest;
use codex_hepta_agent_protocol::AgentdResponse as ProtocolResponse;
use codex_hepta_agent_protocol::DrainSnapshot;
use codex_hepta_agent_protocol::HealthSnapshot;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use pretty_assertions::assert_eq;
use serde::Serialize;

use super::AgentdMethod;
use super::AgentdPayload;
use super::AgentdRequest;
use super::AgentdResponse;

fn frame(value: &impl Serialize) -> Result<Vec<u8>> {
    let mut bytes = serde_json::to_vec(value)?;
    bytes.push(b'\n');
    Ok(bytes)
}

fn response(payload: AgentdPayload) -> Result<AgentdResponse> {
    Ok(AgentdResponse {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: u64::MAX - 1,
        agent_id: AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dd5")?,
        spawn_generation: 5,
        current_generation: 6,
        payload,
    })
}

fn assert_response_frame(actual: AgentdResponse, payload: ProtocolPayload) -> Result<()> {
    let expected = ProtocolResponse {
        schema_version: actual.schema_version,
        request_id: actual.request_id,
        agent_id: actual.agent_id.clone(),
        spawn_generation: actual.spawn_generation,
        current_generation: actual.current_generation,
        payload,
    };
    let actual_frame = frame(&actual)?;
    let expected_frame = frame(&expected)?;
    assert_eq!(actual_frame, expected_frame);
    assert_eq!(
        serde_json::from_slice::<ProtocolResponse>(&actual_frame)?,
        expected
    );
    assert_eq!(
        serde_json::from_slice::<AgentdResponse>(&expected_frame)?,
        actual
    );
    Ok(())
}

#[test]
fn health_and_drain_requests_match_complete_protocol_frames() -> Result<()> {
    let requests = [
        (
            ProtocolRequest::health(/*request_id*/ u64::MAX, /*spawn_generation*/ 5),
            AgentdMethod::Health {},
        ),
        (
            ProtocolRequest::drain(/*request_id*/ 41, /*spawn_generation*/ 17),
            AgentdMethod::Drain {},
        ),
    ];
    for (expected, method) in requests {
        let expected_frame = frame(&expected)?;
        let actual = serde_json::from_slice::<AgentdRequest>(&expected_frame)?;
        assert_eq!(
            actual,
            AgentdRequest {
                _schema_version: expected.schema_version,
                request_id: expected.request_id,
                _spawn_generation: expected.spawn_generation,
                method,
            }
        );
        let actual_frame = frame(&actual)?;
        assert_eq!(actual_frame, expected_frame);
        assert_eq!(
            serde_json::from_slice::<ProtocolRequest>(&actual_frame)?,
            expected
        );
    }
    Ok(())
}

#[test]
fn health_responses_match_complete_protocol_frames() -> Result<()> {
    for (lifecycle, current_generation) in [
        (AgentLifecycle::Starting, 5),
        (AgentLifecycle::Running, 6),
        (AgentLifecycle::Draining, 7),
        (AgentLifecycle::Stopped, 8),
        (AgentLifecycle::Failed, 9),
    ] {
        let health = HealthSnapshot {
            promotion_ready: true,
            ready: lifecycle == AgentLifecycle::Running,
            fenced: false,
            lifecycle,
            process_id: 31415,
            workspace: "/fixture/workspace".into(),
            home_root: "/fixture/home".into(),
            run_root: "/fixture/run".into(),
        };
        let mut actual = response(AgentdPayload::Health(health.clone()))?;
        actual.current_generation = current_generation;
        assert_response_frame(actual, ProtocolPayload::Health(health))?;
    }
    Ok(())
}

#[test]
fn drain_responses_match_complete_protocol_frames() -> Result<()> {
    for (lifecycle, current_generation) in [
        (AgentLifecycle::Starting, 5),
        (AgentLifecycle::Running, 6),
        (AgentLifecycle::Draining, 7),
        (AgentLifecycle::Stopped, 8),
        (AgentLifecycle::Failed, 9),
    ] {
        let draining = lifecycle == AgentLifecycle::Draining;
        let drain = DrainSnapshot {
            admission_closed: draining,
            running_turns: 0,
            drained: draining,
            lifecycle,
            fenced: false,
        };
        let mut actual = response(AgentdPayload::Drain(drain.clone()))?;
        actual.current_generation = current_generation;
        assert_response_frame(actual, ProtocolPayload::Drain(drain))?;
    }
    Ok(())
}

#[test]
fn unsupported_methods_and_malformed_requests_fail_closed() -> Result<()> {
    for method in [ProtocolMethod::Capabilities, ProtocolMethod::Lifecycle] {
        let request = ProtocolRequest {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id: 41,
            spawn_generation: 5,
            method,
        };
        let bytes = frame(&request)?;
        assert_eq!(serde_json::from_slice::<ProtocolRequest>(&bytes)?, request);
        assert!(serde_json::from_slice::<AgentdRequest>(&bytes).is_err());
    }

    for bytes in [
        br#"{"schema_version":2,"request_id":41,"spawn_generation":5,"method":{"type":"unknown"}}"#.as_slice(),
        br#"{"schema_version":2,"request_id":41,"spawn_generation":5,"method":{"type":"health"},"extra":1}"#.as_slice(),
        br#"{"schema_version":2,"spawn_generation":5,"method":{"type":"drain"}}"#.as_slice(),
        br#"{"schema_version":2,"request_id":41,"spawn_generation":"5","method":{"type":"health"}}"#.as_slice(),
        br#"{"schema_version":2,"request_id":41,"request_id":42,"spawn_generation":5,"method":{"type":"health"}}"#.as_slice(),
    ] {
        assert!(serde_json::from_slice::<ProtocolRequest>(bytes).is_err());
        assert!(serde_json::from_slice::<AgentdRequest>(bytes).is_err());
    }
    // Empty struct variants reject method fields outside this fixture's subset,
    // independently of how the full protocol handles a unit variant's fields.
    let extra_method_field = br#"{"schema_version":2,"request_id":41,"spawn_generation":5,"method":{"type":"health","extra":1}}"#;
    assert!(serde_json::from_slice::<AgentdRequest>(extra_method_field).is_err());
    Ok(())
}

#[test]
fn extra_response_fields_and_unsupported_payloads_fail_closed() -> Result<()> {
    let health = HealthSnapshot {
        promotion_ready: true,
        ready: true,
        fenced: false,
        lifecycle: AgentLifecycle::Running,
        process_id: 31415,
        workspace: "/fixture/workspace".into(),
        home_root: "/fixture/home".into(),
        run_root: "/fixture/run".into(),
    };
    let actual = response(AgentdPayload::Health(health))?;
    let mut extra_envelope = serde_json::to_value(&actual)?;
    extra_envelope["extra"] = serde_json::json!(1);
    let mut extra_payload = serde_json::to_value(&actual)?;
    extra_payload["payload"]["extra"] = serde_json::json!(1);
    for value in [extra_envelope, extra_payload] {
        let bytes = serde_json::to_vec(&value)?;
        assert!(serde_json::from_slice::<ProtocolResponse>(&bytes).is_err());
        assert!(serde_json::from_slice::<AgentdResponse>(&bytes).is_err());
    }

    let other = ProtocolResponse {
        schema_version: actual.schema_version,
        request_id: actual.request_id,
        agent_id: actual.agent_id,
        spawn_generation: actual.spawn_generation,
        current_generation: actual.current_generation,
        payload: ProtocolPayload::Error {
            code: "fixture_control".to_string(),
            message: "unsupported payload".to_string(),
        },
    };
    let bytes = frame(&other)?;
    assert_eq!(serde_json::from_slice::<ProtocolResponse>(&bytes)?, other);
    assert!(serde_json::from_slice::<AgentdResponse>(&bytes).is_err());
    Ok(())
}
