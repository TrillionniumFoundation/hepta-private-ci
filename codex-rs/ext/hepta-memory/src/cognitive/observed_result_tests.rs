use super::*;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::ProductionCognitiveMutationResultStateV1;
use codex_hepta_memory::ProductionCognitiveMutationResultV1;

#[test]
fn observed_mutation_preserves_identity_without_replay_or_raw_payload_disclosure() {
    let grant = Sha256Digest::for_bytes(b"grant");
    let input = Sha256Digest::for_bytes(b"input");
    let one = 1_u64.to_be_bytes();
    let zero = 0_u64.to_be_bytes();
    let parts: [&[u8]; 9] = [
        b"hepta:production-cognitive-mutation-operation:v1",
        grant.as_str().as_bytes(),
        &one,
        &one,
        b"lease:test",
        &one,
        b"remember",
        input.as_str().as_bytes(),
        &zero,
    ];
    let mut framed = Vec::new();
    for part in parts {
        framed.extend_from_slice(&(part.len() as u64).to_be_bytes());
        framed.extend_from_slice(part);
    }
    let mut result = ProductionCognitiveMutationResultV1 {
        schema_version: 1,
        namespace: "production_cognitive_mutation".to_owned(),
        state: ProductionCognitiveMutationResultStateV1::Rejected,
        mutation_kind: "remember".to_owned(),
        operation_digest: Sha256Digest::for_bytes(&framed),
        input_payload_sha256: input,
        expected_predecessor_revision: None,
        owner_agent_id: AgentId::parse("00000000-0000-4000-8000-000000000211").unwrap(),
        authority_grant_digest: grant,
        authority_epoch: 1,
        owner_epoch: 1,
        lease_id: "lease:test".to_owned(),
        generation: 1,
        provenance_event_id: "event:prepared".to_owned(),
        provenance_outbox_id: "outbox:test".to_owned(),
        latest_event_id: "event:rejected".to_owned(),
        latest_event_kind: "reconcile_rejected".to_owned(),
        latest_payload_json: "{\"internal\":\"private-payload\"}".to_owned(),
        commit: None,
        result_sha256: Sha256Digest::for_bytes(b"placeholder"),
        external_effect: false,
    };
    result.result_sha256 = result.compute_result_sha256();
    result.validate().unwrap();
    let error = mutation_error(ProductionCognitiveMutationError::ObservedResult(Box::new(
        result.clone(),
    )));
    let FunctionCallError::RespondToModel(body) = error else {
        panic!("expected typed observation")
    };
    let value: Value = serde_json::from_str(&body).unwrap();
    assert_eq!(
        value["error"]["code"],
        "hepta_cognitive_result_already_observed"
    );
    assert_eq!(value["error"]["retryable"], false);
    assert_eq!(value["error"]["observed_result"]["state"], "rejected");
    assert_eq!(
        value["error"]["observed_result"]["operation_digest"],
        serde_json::to_value(&result.operation_digest).unwrap()
    );
    assert_eq!(
        value["error"]["observed_result"]["result_sha256"],
        serde_json::to_value(&result.result_sha256).unwrap()
    );
    assert!(!body.contains("private-payload"));
    assert!(!body.contains("lease:test"));
    assert!(value.get("success").is_none());

    result.result_sha256 = Sha256Digest::for_bytes(b"corrupt");
    let error = mutation_error(ProductionCognitiveMutationError::ObservedResult(Box::new(
        result,
    )));
    let FunctionCallError::RespondToModel(body) = error else {
        panic!("expected integrity refusal")
    };
    let value: Value = serde_json::from_str(&body).unwrap();
    assert_eq!(
        value["error"]["code"],
        "hepta_cognitive_invalid_durable_result"
    );
    assert!(value["error"].get("observed_result").is_none());
    assert!(!body.contains("private-payload"));
}
