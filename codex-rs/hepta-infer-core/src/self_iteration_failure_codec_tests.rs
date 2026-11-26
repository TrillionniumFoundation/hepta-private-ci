//! Raw codec fidelity and finite bounds; these fixtures grant no owner custody.
use super::*;
use crate::durable_control::native::NativeRequest;
use crate::durable_control::native::NativeReservationState;

fn facts() -> SelfIterationModelFailureFactsV1 {
    let request = SelfIterationModelRequestV1 {
        request_id: StableId::new("original.failure.request").expect("id"),
        role: SelfIterationModelRoleV1::Generator,
        envelope_digest: Digest32::of_bytes(b"envelope"),
        candidate_digest: None,
        prompt: "  原始\n\t🙂 request  ".into(),
        deadline_ms: 10000,
        maximum_response_bytes: 8192,
    };
    SelfIterationModelFailureFactsV1 {
        native_record: NativeRunRecord {
            request: NativeRequest {
                request_id: request.request_id.to_string(),
                principal_id: "original-agent".into(),
                worker_generation: 7,
                model: "original-model".into(),
                payload_digest: Digest32::of_bytes(b"full original source").to_string(),
            },
            revision: 1,
            state: NativeReservationState::Reserved,
            dispatch: None,
            turn_id: None,
            cancel_requested: false,
            pre_dispatch_stop: None,
            pre_effect_abort: None,
            dispatch_rejection: None,
            terminal_owner: None,
            terminal_publication: None,
            observation: None,
        },
        request,
        root_outcome_bytes: br#"{"original_fixture":"not_authority"}"#.to_vec(),
        observed_at_ms: 11000,
    }
}
#[test]
fn full_request_roles_and_original_native_record_roundtrip_without_authority_or_trimming() {
    let mut original = facts();
    for role in [
        SelfIterationModelRoleV1::Generator,
        SelfIterationModelRoleV1::Evaluator,
        SelfIterationModelRoleV1::Selector,
        SelfIterationModelRoleV1::Observer,
    ] {
        original.request.role = role;
        original.request.candidate_digest =
            (role != SelfIterationModelRoleV1::Generator).then(|| Digest32::of_bytes(b"frozen"));
        let request = encode_self_iteration_model_request_v1(&original.request).expect("full");
        assert_eq!(
            decode_self_iteration_model_request_v1(&request).expect("same"),
            original.request
        );
        let bytes = encode_self_iteration_model_failure_facts_v1(&original).expect("full");
        assert_eq!(
            decode_self_iteration_model_failure_facts_v1(&bytes).expect("same"),
            original
        );
        assert_eq!(
            original.native_record.state,
            NativeReservationState::Reserved,
            "codec accepts facts without falsely classifying them terminal"
        );
    }
}
#[test]
fn full_valid_prompt_escaping_preserves_the_complete_original_request() {
    let mut original = facts().request;
    original.prompt = "\u{0001}".repeat(MAX_SELF_ITERATION_MODEL_PROMPT_BYTES);
    original.validate(1).expect("original maximum prompt");
    let bytes = encode_self_iteration_model_request_v1(&original).expect("whole escaped prompt");
    assert!(bytes.len() > 16 * 1024);
    assert_eq!(
        decode_self_iteration_model_request_v1(&bytes).expect("exact original"),
        original
    );
    original.prompt.push('x');
    assert!(encode_self_iteration_model_request_v1(&original).is_err());
}

#[test]
fn incomplete_noncanonical_tampered_and_oversized_whole_packets_are_denied() {
    let original = facts();
    let bytes = encode_self_iteration_model_failure_facts_v1(&original).expect("full");
    for end in [0, 7, 16, 31, bytes.len() - 1] {
        assert!(decode_self_iteration_model_failure_facts_v1(&bytes[..end]).is_err());
    }
    let mut changed = bytes.clone();
    changed[20] ^= 1;
    assert!(decode_self_iteration_model_failure_facts_v1(&changed).is_err());
    let mut trailing = bytes;
    trailing.push(0);
    assert!(decode_self_iteration_model_failure_facts_v1(&trailing).is_err());
    let request = encode_self_iteration_model_request_v1(&original.request).expect("request");
    let pretty: serde_json::Value = serde_json::from_slice(&request).expect("json");
    assert!(
        decode_self_iteration_model_request_v1(
            &serde_json::to_vec_pretty(&pretty).expect("pretty")
        )
        .is_err()
    );
    let mut large = original.clone();
    large.root_outcome_bytes = vec![b'x'; MAX_SELF_ITERATION_ROOT_FAILURE_OUTCOME_BYTES_V1 + 1];
    assert!(encode_self_iteration_model_failure_facts_v1(&large).is_err());
    large = original;
    large.observed_at_ms = 0;
    assert!(encode_self_iteration_model_failure_facts_v1(&large).is_err());
}
