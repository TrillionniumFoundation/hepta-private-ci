use std::time::Duration;

use anyhow::Result;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::ProductionDispatchRequest;
use codex_http_client::HttpClientFactory;
use codex_http_client::OutboundProxyPolicy;
use pretty_assertions::assert_eq;

use super::NATIVE_MODEL_TOPIC_V1;
use super::NativeResponsesTarget;
use super::NativeResponsesTargetConfig;

fn target(endpoint: &str) -> Result<NativeResponsesTarget> {
    NativeResponsesTarget::new(
        NativeResponsesTargetConfig {
            responses_url: endpoint.to_string(),
            bearer: None,
            idle_timeout: Duration::from_secs(2),
            max_request_bytes: 4096,
            max_stream_bytes: 8192,
        },
        &HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault),
    )
}

fn request(target: &NativeResponsesTarget, payload: &str) -> ProductionDispatchRequest {
    ProductionDispatchRequest {
        schema_version: 1,
        namespace: "production_durable_writer".to_string(),
        lease_id: "lease:fixture".to_string(),
        occurrence_key: "operation:original".to_string(),
        topic: NATIVE_MODEL_TOPIC_V1.to_string(),
        payload_json: payload.to_string(),
        payload_sha256: Sha256Digest::for_bytes(payload.as_bytes()),
        idempotency_key: "operation:original".to_string(),
        operation_scope_sha256: Sha256Digest::for_bytes(b"fixture scope"),
        operation_subject_id: "agent:fixture".to_string(),
        operation_destination_id: target.destination_id().to_string(),
        operation_semantic_sha256: Sha256Digest::for_bytes(b"fixture operation"),
        operation_policy_generation: 7,
        expected_predecessor_sha256: None,
        operation_digest: Sha256Digest::for_bytes(b"fixture final-use binding"),
    }
}

#[test]
fn original_model_body_is_not_reserialized() -> Result<()> {
    let target = target("http://127.0.0.1:9999/v1/responses")?;
    let payload = "{\n  \"model\": \"fixture\", \"stream\": true\n}";
    let admitted = request(&target, payload);
    let original = target.original_request(&admitted)?;
    assert_eq!(
        (original.operation_id, original.body),
        (admitted.occurrence_key, payload.as_bytes().to_vec())
    );
    Ok(())
}

#[test]
fn changed_endpoint_cannot_observe_or_enter_the_old_destination() -> Result<()> {
    let old = target("http://127.0.0.1:9999/v1/responses")?;
    let replacement = target("http://127.0.0.1:9998/v1/responses")?;
    let admitted = request(&old, r#"{"model":"fixture","stream":true}"#);
    assert!(replacement.original_request(&admitted).is_err());
    Ok(())
}

#[test]
fn original_operation_and_payload_bindings_are_required() -> Result<()> {
    let target = target("http://127.0.0.1:9999/v1/responses")?;
    let admitted = request(&target, r#"{"model":"fixture","stream":true}"#);
    let mut changed_operation = admitted.clone();
    changed_operation.occurrence_key = "operation:substituted".to_string();
    assert!(target.original_request(&changed_operation).is_err());
    let mut changed_payload = admitted.clone();
    changed_payload.payload_json = r#"{"model":"other","stream":true}"#.to_string();
    assert!(target.original_request(&changed_payload).is_err());
    let mut unsupported_cas = admitted;
    unsupported_cas.expected_predecessor_sha256 = Some(Sha256Digest::for_bytes(b"predecessor"));
    assert!(target.original_request(&unsupported_cas).is_err());
    Ok(())
}
