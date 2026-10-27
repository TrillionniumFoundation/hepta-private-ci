use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Digest32;
use std::time::Duration;
use std::time::Instant;
use tokio_util::sync::CancellationToken;

fn snapshot() -> CognitiveContextSnapshot {
    CognitiveContextSnapshot {
        snapshot_digest: "original-snapshot".to_owned(),
        read_digest: "original-read".to_owned(),
        omitted_records: 0,
        items: Vec::new(),
        plan: None,
    }
}

// Shape/control fixture only; this does not claim to be an actual model receipt.
fn observation() -> CognitiveNeuralExecutionV1 {
    let digest = Sha256Digest::for_bytes(b"explicit control fixture");
    CognitiveNeuralExecutionV1 {
        source: crate::CognitiveNeuralSourceV1::SelectedInitial,
        owner_id: AgentId::parse("00000000-0000-4000-8000-000000000220").unwrap(),
        body_generation: 1,
        model_generation: 1,
        parameter_file_digest: digest.clone(),
        adapter_digest: digest.clone(),
        backbone_digest: digest.clone(),
        contract_digest: digest.clone(),
        ready_digest: digest.clone(),
        load_request_digest: digest.clone(),
        load_reservation_digest: digest.clone(),
        load_output_digest: digest.clone(),
        forward_request_digest: digest.clone(),
        forward_reservation_digest: digest.clone(),
        forward_payload_digest: digest.clone(),
        input_digest: digest.clone(),
        response_digest: digest.clone(),
        logits_digest: digest,
        execution_ns: 1,
        input_tokens: 1,
        observed_rss_bytes: 1,
    }
}

fn expected(observed: &CognitiveNeuralExecutionV1) -> ExpectedNeuralReadV1<'_> {
    ExpectedNeuralReadV1 {
        owner: &observed.owner_id,
        body_generation: observed.body_generation,
        parameter: observed.parameter_file_digest.as_str().parse().unwrap(),
        model_generation: observed.model_generation,
        response: observed.response_digest.as_str().parse().unwrap(),
        source: observed.source,
    }
}

#[test]
fn one_original_observation_survives_cloning_and_cannot_be_replaced() {
    let execution = NeuralCognitiveExecutionV1::bounded_read();
    execution.collect_settled_read_v1().unwrap();
    let observed = observation();
    assert!(
        execution
            .match_settled_read_v1(expected(&observed))
            .is_err()
    );
    execution
        .clone()
        .observe_settled_read_v1(observed.clone())
        .unwrap();
    execution
        .match_settled_read_v1(expected(&observed))
        .unwrap();
    assert!(
        execution
            .clone()
            .observe_settled_read_v1(observation())
            .is_err()
    );
    assert!(execution.collect_settled_read_v1().is_err());
    assert_eq!(
        execution.context_with_execution_v1(snapshot()).unwrap(),
        CognitiveContextExecutionV1 {
            schema_version: 1,
            snapshot: snapshot(),
            neural: Some(observed),
        }
    );
}

#[test]
fn different_owner_model_response_or_admission_cannot_reuse_a_forward() {
    let execution = NeuralCognitiveExecutionV1::bounded_read();
    execution.collect_settled_read_v1().unwrap();
    let observed = observation();
    execution.observe_settled_read_v1(observed.clone()).unwrap();
    for changed in 0..6 {
        let other_owner = AgentId::parse("00000000-0000-4000-8000-000000000221").unwrap();
        let mut wanted = expected(&observed);
        match changed {
            0 => wanted.owner = &other_owner,
            1 => wanted.body_generation += 1,
            2 => wanted.parameter = Digest32::of_bytes(b"different parameters"),
            3 => wanted.model_generation += 1,
            4 => wanted.response = Digest32::of_bytes(b"different response"),
            5 => wanted.source = crate::CognitiveNeuralSourceV1::EvaluatedChild,
            _ => unreachable!(),
        }
        assert!(execution.match_settled_read_v1(wanted).is_err());
    }
}

#[test]
fn cancellation_deadline_and_envelope_budget_remain_closed() {
    let cancellation = CancellationToken::new();
    let execution = NeuralCognitiveExecutionV1::with_deadline(
        Instant::now() + Duration::from_secs(2),
        cancellation.clone(),
    );
    execution.collect_settled_read_v1().unwrap();
    execution.observe_settled_read_v1(observation()).unwrap();
    cancellation.cancel();
    assert!(execution.context_with_execution_v1(snapshot()).is_err());
    assert!(execution.observe_settled_read_v1(observation()).is_err());
    let expired =
        NeuralCognitiveExecutionV1::with_deadline(Instant::now(), CancellationToken::new());
    assert!(expired.collect_settled_read_v1().is_err());
    let mut context = CognitiveContextExecutionV1 {
        schema_version: 1,
        snapshot: snapshot(),
        neural: Some(observation()),
    };
    validate_context_execution_v1(&context).unwrap();
    context.schema_version = 2;
    assert!(validate_context_execution_v1(&context).is_err());
    context.schema_version = 1;
    context.snapshot.read_digest = "x".repeat(crate::MAX_COGNITIVE_CONTEXT_BYTES);
    assert!(validate_context_execution_v1(&context).is_err());
}

#[test]
fn incomplete_measurement_and_unknown_fields_are_not_accepted() {
    let execution = NeuralCognitiveExecutionV1::bounded_read();
    execution.collect_settled_read_v1().unwrap();
    let mut invalid = observation();
    invalid.model_generation = 2;
    assert!(execution.observe_settled_read_v1(invalid).is_err());
    let mut invalid = observation();
    invalid.response_digest = Sha256Digest::parse("0".repeat(64)).unwrap();
    assert!(execution.observe_settled_read_v1(invalid).is_err());
    let mut wire = serde_json::to_value(observation()).unwrap();
    wire["execution_authority"] = serde_json::json!(true);
    assert!(serde_json::from_value::<CognitiveNeuralExecutionV1>(wire).is_err());
    let mut unknown_source = serde_json::to_value(observation()).unwrap();
    unknown_source["source"] = serde_json::json!("unregistered_source");
    assert!(serde_json::from_value::<CognitiveNeuralExecutionV1>(unknown_source).is_err());
    for invalid_digest in ["", "not-a-digest", &"a".repeat(65)] {
        let mut wire = serde_json::to_value(observation()).unwrap();
        wire["response_digest"] = serde_json::json!(invalid_digest);
        let decoded = serde_json::from_value::<CognitiveNeuralExecutionV1>(wire).unwrap();
        assert!(execution.observe_settled_read_v1(decoded).is_err());
    }
    execution.observe_settled_read_v1(observation()).unwrap();
}
