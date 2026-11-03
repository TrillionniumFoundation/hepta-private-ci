use super::*;
use pretty_assertions::assert_eq;
use serde_json::json;

fn fixture() -> anyhow::Result<(NativeRuntimeTarget, ProductionDispatchRequest)> {
    let params: ProcessStartParams = serde_json::from_value(json!({
        "host": "original-host",
        "executable": "/usr/bin/true",
        "idempotency_key": "original-operation",
    }))?;
    let payload_json = serde_json::to_string(&params)?;
    let target = NativeRuntimeTarget::new(
        "runtime-fixture".to_string(),
        /*max_output_bytes*/ 4096,
    )?;
    let request = ProductionDispatchRequest {
        schema_version: PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
        namespace: PRODUCTION_DURABLE_WRITER_NAMESPACE.to_string(),
        lease_id: "original-lease".to_string(),
        occurrence_key: "original-operation".to_string(),
        topic: NATIVE_RUNTIME_TOPIC_V1.to_string(),
        payload_sha256: Sha256Digest::for_bytes(payload_json.as_bytes()),
        payload_json,
        idempotency_key: "original-operation".to_string(),
        operation_scope_sha256: Sha256Digest::for_bytes(b"original-scope"),
        operation_subject_id: "original-subject".to_string(),
        operation_destination_id: "runtime-fixture".to_string(),
        operation_semantic_sha256: Sha256Digest::for_bytes(b"original-semantics"),
        operation_policy_generation: 7,
        expected_predecessor_sha256: None,
        operation_digest: Sha256Digest::for_bytes(b"original-operation"),
    };
    Ok((target, request))
}

#[test]
fn rejects_rebound_runtime_payload_and_operation_identity() -> anyhow::Result<()> {
    let (target, original) = fixture()?;
    let params = target.original_params(&original).expect("original payload");
    assert_eq!(
        serde_json::to_string(&params).expect("canonical original"),
        original.payload_json
    );

    let mut changed_key = original.clone();
    changed_key.idempotency_key = "replacement-operation".to_string();
    assert!(target.original_params(&changed_key).is_err());

    let mut changed_destination = original.clone();
    changed_destination.operation_destination_id = "another-runtime".to_string();
    assert!(target.original_params(&changed_destination).is_err());

    let mut changed_payload = original.clone();
    let mut value: serde_json::Value =
        serde_json::from_str(&changed_payload.payload_json).expect("original payload");
    value["host"] = json!("substituted-host");
    changed_payload.payload_json = serde_json::to_string(&value).expect("changed payload");
    assert!(target.original_params(&changed_payload).is_err());

    // Even a digest over altered bytes does not make a second process key an
    // admissible original operation or make noncanonical wire bytes equivalent.
    value["idempotency_key"] = json!("replacement-operation");
    changed_payload.payload_json = serde_json::to_string(&value).expect("changed payload");
    changed_payload.payload_sha256 =
        Sha256Digest::for_bytes(changed_payload.payload_json.as_bytes());
    assert!(target.original_params(&changed_payload).is_err());

    let mut noncanonical = original;
    noncanonical.payload_json.push('\n');
    noncanonical.payload_sha256 = Sha256Digest::for_bytes(noncanonical.payload_json.as_bytes());
    assert!(target.original_params(&noncanonical).is_err());
    Ok(())
}

#[tokio::test]
async fn raw_dispatch_cannot_bypass_final_use_handoff() -> anyhow::Result<()> {
    let (target, original) = fixture()?;
    let outcome = target.dispatch(original).await;
    assert!(matches!(outcome, ProductionTargetOutcome::Rejected { .. }));
    Ok(())
}
