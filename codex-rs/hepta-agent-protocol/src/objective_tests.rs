use super::*;

fn digest(byte: char) -> String {
    byte.to_string().repeat(64)
}

fn ingress() -> AuthBusObjectiveIngress {
    AuthBusObjectiveIngress {
        issuer_id: "issuer.objective".to_string(),
        key_epoch: 1,
        message_id: "objective.message.1".to_string(),
        sequence: 1,
        expires_at_ms: 9_999_999,
        signature_hex: "00".repeat(64),
        body: AuthBusObjectiveBody {
            spawn_generation: 3,
            run_id: "run.objective.1".to_string(),
            objective_revision: 1,
            source_envelope_json: "{\"requestId\":\"request.1\"}".to_string(),
            runtime_body_digest: digest('1'),
            preference_state_digest: digest('2'),
            model_tuple_digest: digest('3'),
            prompt_registry_digest: digest('4'),
            artifact_set_digest: digest('5'),
            authority_epoch: 7,
            queued_input: None,
        },
    }
}

#[test]
fn signed_objective_control_request_round_trips_inside_frame_bound() {
    let request = AgentdRequest::objective_start(41, 3, ingress());
    let bytes = serde_json::to_vec(&request).expect("serialize");
    assert!(bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
    assert_eq!(
        serde_json::from_slice::<AgentdRequest>(&bytes).expect("decode"),
        request
    );
}

#[test]
fn objective_start_outcomes_are_strict_wire_types() {
    let outcome = ObjectiveStartOutcome::Admitted {
        receipt: ObjectiveRunAdmission {
            run_id: "run.objective.1".to_string(),
            objective_digest: digest('1'),
            hard_constraint_digest: digest('2'),
            publication_digest: digest('3'),
            chain_digest: digest('4'),
            disposition: "compiled".to_string(),
            idempotent: false,
        },
    };
    let bytes = serde_json::to_vec(&outcome).expect("serialize");
    assert_eq!(
        serde_json::from_slice::<ObjectiveStartOutcome>(&bytes).expect("decode"),
        outcome
    );
}

#[test]
fn optional_queued_input_preserves_legacy_body_bytes_and_covers_the_new_route() {
    let mut request = ingress();
    let legacy = serde_json::to_vec(&request.body).expect("legacy body");
    let decoded: AuthBusObjectiveBody = serde_json::from_slice(&legacy).expect("legacy decode");
    assert_eq!(decoded.queued_input, None);
    assert_eq!(serde_json::to_vec(&decoded).expect("legacy encode"), legacy);
    let legacy_value: serde_json::Value = serde_json::from_slice(&legacy).expect("legacy JSON");
    assert!(legacy_value.get("queued_input").is_none());

    request.body.queued_input = Some(ObjectiveQueuedInputV1 {
        thread_id: "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12".to_string(),
        text: "Edit the requested file and run its test.".to_string(),
    });
    let with_queue = serde_json::to_vec(&request.body).expect("queued body");
    assert_ne!(with_queue, legacy);
    assert_eq!(serde_json::from_slice::<AuthBusObjectiveBody>(&with_queue).expect("queued decode"), request.body);
    request.body.queued_input = None;
    assert_eq!(serde_json::to_vec(&request.body).expect("legacy again"), legacy);
}
