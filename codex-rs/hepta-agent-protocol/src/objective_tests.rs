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
            execution: Some(ObjectiveRunExecutionBinding {
                request_digest: digest('5'),
                objective_digest: digest('1'),
                body_digest: digest('6'),
                artifact_set_digest: digest('7'),
                authority_epoch: 7,
                generation: 3,
                fence_digest: digest('8'),
                deadline_ms: 9_999_000,
            }),
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
fn objective_execution_binding_is_additive_and_strict() {
    let outcome = ObjectiveStartOutcome::Admitted {
        receipt: ObjectiveRunAdmission {
            run_id: "run.objective.compat".to_string(),
            objective_digest: digest('1'),
            hard_constraint_digest: digest('2'),
            publication_digest: digest('3'),
            chain_digest: digest('4'),
            disposition: "explicit_abstain".to_string(),
            execution: None,
            idempotent: false,
        },
    };
    let bytes = serde_json::to_vec(&outcome).expect("serialize without binding");
    assert!(!String::from_utf8_lossy(&bytes).contains("execution"));
    assert_eq!(
        serde_json::from_slice::<ObjectiveStartOutcome>(&bytes).expect("decode without binding"),
        outcome
    );

    let mut value = serde_json::to_value(outcome).expect("value");
    value["receipt"]["execution"] = serde_json::json!({
        "request_digest": digest('5'),
        "objective_digest": digest('1'),
        "body_digest": digest('6'),
        "artifact_set_digest": digest('7'),
        "authority_epoch": 7,
        "generation": 3,
        "fence_digest": digest('8'),
        "deadline_ms": 9_999_000,
        "unknown": true
    });
    assert!(serde_json::from_value::<ObjectiveStartOutcome>(value).is_err());
}
