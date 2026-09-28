use super::*;
use codex_hepta_agent_components::contracts::AgentId;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

fn response(message: String) -> TestResult<AgentdResponse> {
    Ok(AgentdResponse {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: u64::MAX,
        agent_id: AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dd3")?,
        spawn_generation: u64::MAX,
        current_generation: u64::MAX,
        payload: AgentdPayload::Error {
            code: "fixture".into(),
            message,
        },
    })
}

#[test]
fn oversize_response_is_a_bounded_error_with_original_identity() -> TestResult {
    let original = response("\n".repeat(65_536))?;
    let request_id = original.request_id;
    let agent = original.agent_id.clone();
    let bytes = encode_response(original)?;
    assert!(bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
    assert!(bytes.ends_with(b"\n"));
    let decoded: AgentdResponse = serde_json::from_slice(&bytes)?;
    assert_eq!(decoded.request_id, request_id);
    assert_eq!(decoded.agent_id, agent);
    assert_eq!(decoded.spawn_generation, u64::MAX);
    assert_eq!(decoded.current_generation, u64::MAX);
    assert!(
        matches!(decoded.payload, AgentdPayload::Error { code, .. } if code == "response_too_large")
    );
    Ok(())
}

#[test]
fn page_budget_leaves_room_for_maximum_identity_envelope() -> TestResult {
    let bytes = encode_response(response("x".repeat(crate::MAX_AUTOMATION_LIST_PAGE_BYTES))?)?;
    assert!(bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
    let decoded: AgentdResponse = serde_json::from_slice(&bytes)?;
    assert!(matches!(decoded.payload, AgentdPayload::Error { code, .. } if code == "fixture"));
    Ok(())
}

#[test]
fn encoder_never_buffers_more_than_one_control_frame() -> TestResult {
    let mut buffer = ControlFrameBuffer {
        bytes: Vec::with_capacity(MAX_CONTROL_FRAME_BYTES as usize),
        overflowed: false,
    };
    assert!(serde_json::to_writer(&mut buffer, &response("\n".repeat(1_000_000))?).is_err());
    assert!(buffer.overflowed);
    assert!(buffer.bytes.len() < MAX_CONTROL_FRAME_BYTES as usize);
    Ok(())
}
