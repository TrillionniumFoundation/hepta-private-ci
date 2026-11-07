use super::*;
use crate::AGENTD_CONTROL_SCHEMA_VERSION;
use crate::AgentdMethod;
use crate::AgentdPayload;
use crate::AgentdRequest;
use crate::AgentdResponse;
use crate::MAX_CONTROL_FRAME_BYTES;

#[test]
fn maximum_generation_pages_and_inputs_roundtrip_within_existing_frame() {
    let step = GenerationStepV1 {
        client_operation_id: "x".repeat(256),
        expected_snapshot_digest: [255; 32],
        task_digest: [255; 32],
        source_frontier: [255; 32],
        input: vec![255; MAX_GENERATION_CONTROL_INPUT_BYTES],
        deadline_micros: u64::MAX,
    };
    for operation in [
        GenerationControlRequestV1::Step {
            request: Box::new(step.clone()),
        },
        GenerationControlRequestV1::LookupIntent {
            expected_operation_id: "x".repeat(256),
            request: Box::new(step),
        },
    ] {
        let mut altered = serde_json::to_value(&operation).expect("operation value");
        altered["allow_if_missing"] = serde_json::json!(true);
        assert!(serde_json::from_value::<GenerationControlRequestV1>(altered).is_err());
        let request = AgentdRequest {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id: u64::MAX,
            spawn_generation: u64::MAX,
            method: AgentdMethod::Generation {
                request: Box::new(operation),
            },
        };
        let encoded = serde_json::to_vec(&request).expect("encode maximum request");
        assert!((encoded.len() as u64) < MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<AgentdRequest>(&encoded).expect("decode request"),
            request
        );
    }

    let response = AgentdResponse {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: u64::MAX,
        agent_id: codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")
            .expect("agent"),
        spawn_generation: u64::MAX,
        current_generation: u64::MAX,
        payload: AgentdPayload::Generation(GenerationControlResponseV1::Output {
            delivery: GenerationOutputReferenceV1 {
                operation_id: "x".repeat(256),
                request_digest: [255; 32],
                prefix_offset: u64::MAX,
                bytes: u32::MAX,
                chunk_digest: [255; 32],
            },
            offset: u32::MAX,
            bytes: vec![255; usize::from(MAX_GENERATION_OUTPUT_PAGE_BYTES)],
            complete: true,
        }),
    };
    let encoded = serde_json::to_vec(&response).expect("encode maximum page");
    assert!((encoded.len() as u64) < MAX_CONTROL_FRAME_BYTES);
    assert_eq!(
        serde_json::from_slice::<AgentdResponse>(&encoded).expect("decode page"),
        response
    );
}

#[test]
fn generation_wire_rejects_unknown_fields_and_unbounded_byte_values() {
    for request in [
        GenerationControlRequestV1::Status {},
        GenerationControlRequestV1::Cost {},
        GenerationControlRequestV1::Drain {},
        GenerationControlRequestV1::Resume {},
    ] {
        let mut encoded = serde_json::to_value(&request).expect("encode empty request");
        assert_eq!(
            serde_json::from_value::<GenerationControlRequestV1>(encoded.clone())
                .expect("decode empty request"),
            request
        );
        encoded["grant"] = serde_json::json!(true);
        assert!(serde_json::from_value::<GenerationControlRequestV1>(encoded).is_err());
    }
    for response in [
        GenerationControlResponseV1::Acknowledged {},
        GenerationControlResponseV1::CancelRequested {},
        GenerationControlResponseV1::Resumed {},
        GenerationControlResponseV1::IntentMissing {
            operation_id: "original-pinned-operation".into(),
        },
    ] {
        let mut encoded = serde_json::to_value(&response).expect("encode empty response");
        assert_eq!(
            serde_json::from_value::<GenerationControlResponseV1>(encoded.clone())
                .expect("decode empty response"),
            response
        );
        encoded["grant"] = serde_json::json!(true);
        assert!(serde_json::from_value::<GenerationControlResponseV1>(encoded).is_err());
    }
    assert!(
        serde_json::from_str::<GenerationControlRequestV1>(
            r#"{"operation":"status","grant":true}"#
        )
        .is_err()
    );
    assert!(
        serde_json::from_str::<GenerationControlRequestV1>(
            r#"{"operation":"output","expected_chunk_digest":[0],"offset":0,"limit":1}"#
        )
        .is_err()
    );
    assert!(
        serde_json::from_str::<GenerationControlRequestV1>(
            r#"{"operation":"output","expected_chunk_digest":null,"offset":0,"limit":65536}"#
        )
        .is_err()
    );
}
