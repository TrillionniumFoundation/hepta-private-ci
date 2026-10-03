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
        limit: MAX_CONTROL_FRAME_BYTES as usize,
    };
    assert!(serde_json::to_writer(&mut buffer, &response("\n".repeat(1_000_000))?).is_err());
    assert!(buffer.overflowed);
    assert!(buffer.bytes.len() < MAX_CONTROL_FRAME_BYTES as usize);
    Ok(())
}

#[test]
fn full_native_receipt_is_never_truncated_to_fit_an_escaped_control_frame() -> TestResult {
    let json = serde_json::to_string(&"\n".repeat(24_000))?;
    assert!((json.len() as u64) < MAX_CONTROL_FRAME_BYTES);
    let mut original = response(String::new())?;
    original.payload = AgentdPayload::NativeModelReceipt {
        request_id: "assessment-1".into(),
        native_record_json: Some(json),
    };
    let bytes = encode_response(original)?;
    let decoded: AgentdResponse = serde_json::from_slice(&bytes)?;
    assert!(bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
    assert!(
        matches!(decoded.payload, AgentdPayload::Error { code, .. } if code == "response_too_large")
    );
    Ok(())
}

#[test]
fn only_whole_canary_response_uses_its_original_record_ceiling() -> TestResult {
    let query = crate::CanaryOperationQueryV2 {
        model_generation: 1,
        configuration_digest: "a".repeat(64),
        body_digest: "b".repeat(64),
        scope_digest: "c".repeat(64),
        objective_digest: "d".repeat(64),
        tick_id: "actual-canary".into(),
        input_semantic_digest: "e".repeat(64),
    };
    let mut original = response(String::new())?;
    original.payload = AgentdPayload::CanaryOperationReceipt {
        query: query.clone(),
        source_digest: "f".repeat(64),
        receipt_hex: "ab".repeat(40_000),
    };
    let whole = encode_response_with_limit(
        original.clone(),
        crate::canary_operation_receipt::response_limit(
            &crate::AgentdMethod::CanaryOperationReceipt { query },
        ),
    )?;
    assert!(whole.len() as u64 > MAX_CONTROL_FRAME_BYTES);
    assert_eq!(serde_json::from_slice::<AgentdResponse>(&whole)?, original);
    let bounded = encode_response(original)?;
    assert!(bounded.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
    assert!(
        matches!(serde_json::from_slice::<AgentdResponse>(&bounded)?.payload,
        AgentdPayload::Error { code, .. } if code == "response_too_large")
    );
    Ok(())
}

#[test]
fn completed_proposal_response_preserves_the_whole_original_packet() -> TestResult {
    let mut original = response(String::new())?;
    let proposal_id = "actual-completed-proposal".to_string();
    original.payload = AgentdPayload::PlasticityCompletedProposal {
        proposal_id: proposal_id.clone(),
        observation_hex: Some("ab".repeat(40_000)),
    };
    let method = crate::AgentdMethod::PlasticityCompletedProposal { proposal_id };
    let whole = encode_response_with_limit(
        original.clone(),
        crate::canary_operation_receipt::response_limit(&method),
    )?;
    assert!(whole.len() as u64 > MAX_CONTROL_FRAME_BYTES);
    assert_eq!(serde_json::from_slice::<AgentdResponse>(&whole)?, original);
    let bounded = encode_response(original)?;
    assert!(
        matches!(serde_json::from_slice::<AgentdResponse>(&bounded)?.payload,
        AgentdPayload::Error { code, .. } if code == "response_too_large")
    );
    Ok(())
}

#[test]
fn prepared_whole_frame_uses_only_its_finite_budget_and_never_truncates() -> TestResult {
    let method = crate::AgentdMethod::PreparedGenerationV2 {
        generation: 2,
        configuration_digest: "config".into(),
        body_digest: "body".into(),
    };
    let limit = crate::prepared_generation_response_limit(&method);
    assert!(limit > MAX_CONTROL_FRAME_BYTES);
    assert_eq!(
        crate::prepared_generation_response_limit(&crate::AgentdMethod::Health),
        MAX_CONTROL_FRAME_BYTES
    );
    let mut original = response(String::new())?;
    original.payload = AgentdPayload::PreparedGenerationV2 {
        generation: 2,
        configuration_digest: "config".into(),
        body_digest: "body".into(),
        prepared_hex: Some("ab".repeat(MAX_CONTROL_FRAME_BYTES as usize)),
    };
    let bytes = encode_response_with_limit(original.clone(), limit)?;
    assert!(bytes.len() as u64 > MAX_CONTROL_FRAME_BYTES && bytes.len() as u64 <= limit);
    let decoded: AgentdResponse = serde_json::from_slice(&bytes)?;
    assert_eq!(decoded, original);
    let legacy: AgentdResponse = serde_json::from_slice(&encode_response(original)?)?;
    assert!(matches!(legacy.payload,AgentdPayload::Error{code,..} if code=="response_too_large"));
    Ok(())
}
