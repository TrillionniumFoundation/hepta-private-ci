use serde_json::json;

use super::*;

fn intent() -> ExecutionIntentV1 {
    ExecutionIntentV1 {
        schema_version: EXECUTION_ENVELOPE_SCHEMA_VERSION_V1,
        operation_id: "operation:p1-test".to_string(),
        subject_id: "agent:test".to_string(),
        scope_id: "scope:research".to_string(),
        destination_id: "codex:exec-server".to_string(),
        target: ExecutionTargetV1::CodexExecServerProcess,
        generation: 7,
        fence: 11,
        authority_epoch: 4,
        payload_sha256: Sha256Digest::for_bytes(b"example-tool-payload"),
        payload_bytes: b"example-tool-payload".len() as u32,
        deadline_unix_ms: 1_800_000_000_000,
        max_wall_ms: 5000,
    }
}

fn digest_hex(bytes: &[u8; 32]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn observation(
    value: &ExecutionIntentV1,
    state: ExecutionTransportObservationV1,
) -> ExecutionObservationV1 {
    ExecutionObservationV1 {
        schema_version: EXECUTION_ENVELOPE_SCHEMA_VERSION_V1,
        operation_id: value.operation_id.clone(),
        scope_id: value.scope_id.clone(),
        destination_id: value.destination_id.clone(),
        generation: value.generation,
        fence: value.fence,
        authority_epoch: value.authority_epoch,
        request_sha256: value
            .binding_proposal()
            .expect("valid intent")
            .request_sha256,
        transport: state,
        claimed_original_receipt_sha256: None,
    }
}

#[test]
fn canonical_sha256_vectors_match_an_independent_big_endian_reference() {
    let proposed = intent().binding_proposal().expect("proposal");
    assert_eq!(
        digest_hex(&proposed.request_sha256),
        "089c25dab7c2c930918cdff41800b686d05e2b4440bc85ff43b46cbc0c313052"
    );
    assert_eq!(
        digest_hex(&proposed.scope_sha256),
        "06dae7b898732c7141ef45a199427d82fb87dccbc49543fce3594ec510caf72d"
    );
}

#[test]
fn real_payload_bytes_are_checked_before_proposing_a_binding() {
    let value = intent();
    assert_eq!(value.verify_payload(b"example-tool-payload"), Ok(()));
    assert_eq!(
        value.verify_payload(b"example-tool-payloaD"),
        Err(ExecutionEnvelopeErrorV1::PayloadMismatch)
    );
    assert_eq!(
        value.verify_payload(b""),
        Err(ExecutionEnvelopeErrorV1::PayloadMismatch)
    );
}

#[test]
fn binding_proposal_has_no_authority_and_binds_original_bytes() {
    let value = intent();
    let proposed = value.binding_proposal().expect("valid proposal");
    assert_ne!(proposed.request_sha256, [0; 32]);
    assert_ne!(proposed.scope_sha256, [0; 32]);
    assert_eq!(
        proposed.proposed_final_use_binding.request_sha256,
        proposed.request_sha256
    );
    assert_eq!(
        proposed.proposed_final_use_binding.scope_sha256,
        proposed.scope_sha256
    );
    assert_eq!(
        proposed.proposed_final_use_binding.subject_id,
        value.subject_id
    );
    assert_eq!(
        proposed.proposed_final_use_binding.destination_id,
        value.destination_id
    );
    let expected_payload_sha256: [u8; 32] = Sha256::digest(b"example-tool-payload").into();
    assert_eq!(
        proposed.proposed_final_use_binding.payload_sha256,
        expected_payload_sha256
    );
}

#[test]
fn all_request_bindings_are_deterministic_across_json_field_order() {
    let value = intent();
    let mut reordered = serde_json::to_value(&value).expect("serialize");
    let object = reordered.as_object_mut().expect("object");
    let id = object.remove("operation_id").expect("id");
    object.insert("operation_id".to_string(), id);
    let other: ExecutionIntentV1 =
        serde_json::from_value(reordered).expect("parse canonical fields");
    assert_eq!(
        value.binding_proposal().expect("left"),
        other.binding_proposal().expect("right")
    );
}

#[test]
fn kind_is_bound_model_only_never_aliases_tool_intent() {
    let value = intent();
    let mut model = value.clone();
    model.target = ExecutionTargetV1::CodexAppServerModelOnly;
    assert_ne!(
        value.binding_proposal().expect("tool").request_sha256,
        model.binding_proposal().expect("model").request_sha256
    );
    assert_eq!(
        value.binding_proposal().expect("tool").scope_sha256,
        model.binding_proposal().expect("model").scope_sha256
    );
}

#[test]
fn every_sensitive_request_field_is_in_request_hash() {
    let value = intent();
    let original = value.binding_proposal().expect("original").request_sha256;
    let mut variants = Vec::new();
    let mut next = value.clone();
    next.operation_id.push('x');
    variants.push(next);
    let mut next = value.clone();
    next.subject_id.push('x');
    variants.push(next);
    let mut next = value.clone();
    next.scope_id.push('x');
    variants.push(next);
    let mut next = value.clone();
    next.destination_id.push('x');
    variants.push(next);
    let mut next = value.clone();
    next.generation += 1;
    variants.push(next);
    let mut next = value.clone();
    next.fence += 1;
    variants.push(next);
    let mut next = value.clone();
    next.authority_epoch += 1;
    variants.push(next);
    let mut next = value.clone();
    next.max_wall_ms += 1;
    variants.push(next);
    let mut next = value.clone();
    next.deadline_unix_ms += 1;
    variants.push(next);
    let mut next = value.clone();
    next.payload_bytes += 1;
    variants.push(next);
    let mut next = value;
    next.payload_sha256 = Sha256Digest::for_bytes(b"other physical bytes");
    variants.push(next);
    for variant in variants {
        assert_ne!(
            original,
            variant
                .binding_proposal()
                .expect("valid variant")
                .request_sha256
        );
    }
}

#[test]
fn scope_hash_changes_with_principal_destination_generation_fence_and_epoch() {
    let value = intent();
    let original = value.binding_proposal().expect("original").scope_sha256;
    let mut variants = Vec::new();
    let mut next = value.clone();
    next.subject_id = "agent:other".to_string();
    variants.push(next);
    let mut next = value.clone();
    next.scope_id = "scope:other".to_string();
    variants.push(next);
    let mut next = value.clone();
    next.destination_id = "other-executor".to_string();
    variants.push(next);
    let mut next = value.clone();
    next.generation += 1;
    variants.push(next);
    let mut next = value.clone();
    next.fence += 1;
    variants.push(next);
    let mut next = value;
    next.authority_epoch += 1;
    variants.push(next);
    for variant in variants {
        assert_ne!(
            original,
            variant
                .binding_proposal()
                .expect("valid variant")
                .scope_sha256
        );
    }
}

#[test]
fn identity_validation_rejects_path_escape_unicode_and_unbounded_strings() {
    let oversized = "x".repeat(129);
    for bad in [
        "",
        "../escape",
        "a\nb",
        "scope space",
        "界",
        oversized.as_str(),
    ] {
        let mut value = intent();
        value.operation_id = bad.to_string();
        assert_eq!(
            value.validate(),
            Err(ExecutionEnvelopeErrorV1::InvalidIdentity)
        );
        let mut value = intent();
        value.destination_id = bad.to_string();
        assert_eq!(
            value.validate(),
            Err(ExecutionEnvelopeErrorV1::InvalidIdentity)
        );
    }
}

#[test]
fn zero_generation_fence_or_authority_epoch_fails_closed() {
    let mut value = intent();
    value.generation = 0;
    assert_eq!(
        value.validate(),
        Err(ExecutionEnvelopeErrorV1::InvalidGenerationOrEpoch)
    );
    let mut value = intent();
    value.fence = 0;
    assert_eq!(
        value.validate(),
        Err(ExecutionEnvelopeErrorV1::InvalidGenerationOrEpoch)
    );
    let mut value = intent();
    value.authority_epoch = 0;
    assert_eq!(
        value.validate(),
        Err(ExecutionEnvelopeErrorV1::InvalidGenerationOrEpoch)
    );
}

#[test]
fn bounded_deadlines_payloads_and_versions_are_enforced() {
    let mut value = intent();
    value.schema_version = 2;
    assert_eq!(
        value.validate(),
        Err(ExecutionEnvelopeErrorV1::InvalidVersion)
    );
    for wall in [0, MAX_EXECUTION_WALL_MS_V1 + 1] {
        let mut value = intent();
        value.max_wall_ms = wall;
        assert_eq!(
            value.validate(),
            Err(ExecutionEnvelopeErrorV1::InvalidDeadlineOrBudget)
        );
    }
    let mut value = intent();
    value.deadline_unix_ms = 0;
    assert_eq!(
        value.validate(),
        Err(ExecutionEnvelopeErrorV1::InvalidDeadlineOrBudget)
    );
    for size in [0, MAX_EXECUTION_PAYLOAD_BYTES_V1 + 1] {
        let mut value = intent();
        value.payload_bytes = size;
        assert_eq!(
            value.validate(),
            Err(ExecutionEnvelopeErrorV1::InvalidPayloadSize)
        );
    }
}

#[test]
fn malformed_or_zero_sha256_digest_is_not_admitted() {
    for bad in [
        "0".repeat(64),
        "A".repeat(64),
        "x".repeat(64),
        "abc".to_string(),
    ] {
        let mut value = serde_json::to_value(intent()).expect("object");
        value["payload_sha256"] = json!(bad);
        let value: ExecutionIntentV1 = serde_json::from_value(value).expect("deserialize");
        assert_eq!(
            value.validate(),
            Err(ExecutionEnvelopeErrorV1::InvalidDigest)
        );
    }
}

#[test]
fn unknown_intent_and_observation_fields_fail_deserialization() {
    let mut value = serde_json::to_value(intent()).expect("intent");
    value["tool_granted"] = json!(true);
    assert!(serde_json::from_value::<ExecutionIntentV1>(value).is_err());

    let mut value = serde_json::to_value(observation(
        &intent(),
        ExecutionTransportObservationV1::Indeterminate,
    ))
    .expect("observation");
    value["provider_completed"] = json!(true);
    assert!(serde_json::from_value::<ExecutionObservationV1>(value).is_err());
}

#[test]
fn duplicated_json_identity_fields_are_rejected_before_validation() {
    let canonical = serde_json::to_string(&intent()).expect("serialize");
    let duplicated = canonical.replacen(
        "\"operation_id\":",
        "\"operation_id\":\"forged\",\"operation_id\":",
        1,
    );
    assert_ne!(canonical, duplicated);
    assert!(serde_json::from_str::<ExecutionIntentV1>(&duplicated).is_err());

    let original = observation(&intent(), ExecutionTransportObservationV1::Indeterminate);
    let canonical = serde_json::to_string(&original).expect("serialize");
    let duplicated = canonical.replacen(
        "\"request_sha256\":",
        "\"request_sha256\":[0],\"request_sha256\":",
        1,
    );
    assert_ne!(canonical, duplicated);
    assert!(serde_json::from_str::<ExecutionObservationV1>(&duplicated).is_err());
}

#[test]
fn unknown_enum_profile_does_not_fallback_to_process() {
    let mut value = serde_json::to_value(intent()).expect("intent");
    value["target"] = json!("unknown_future_provider");
    assert!(serde_json::from_value::<ExecutionIntentV1>(value).is_err());
}

#[test]
fn ambiguous_or_lost_dispatch_has_only_original_owner_reconciliation() {
    let value = intent();
    for state in [
        ExecutionTransportObservationV1::NotSentClaimed,
        ExecutionTransportObservationV1::AcceptedClaimed,
        ExecutionTransportObservationV1::Indeterminate,
    ] {
        let observed = observation(&value, state);
        let plan = plan_execution_reconciliation_v1(&value, &observed).expect("plan");
        assert_eq!(
            plan.action,
            ExecutionReconcileOnlyV1::LookupOriginalOperation
        );
        assert_eq!(
            plan.request_sha256,
            value.binding_proposal().expect("binding").request_sha256
        );
        assert_eq!(plan.operation_id, value.operation_id);
        assert_eq!(plan.generation, value.generation);
        assert_eq!(plan.fence, value.fence);
    }
}

#[test]
fn terminal_claim_can_only_request_original_receipt_verification() {
    let value = intent();
    let mut observed = observation(&value, ExecutionTransportObservationV1::TerminalClaimed);
    assert_eq!(
        plan_execution_reconciliation_v1(&value, &observed),
        Err(ExecutionEnvelopeErrorV1::InvalidObservation)
    );
    observed.claimed_original_receipt_sha256 = Some(Sha256Digest::for_bytes(b"claim-only"));
    let plan = plan_execution_reconciliation_v1(&value, &observed).expect("plan");
    assert_eq!(plan.action, ExecutionReconcileOnlyV1::VerifyOriginalReceipt);
    assert_eq!(plan.operation_id, value.operation_id);
}

#[test]
fn terminal_claim_with_empty_or_zero_receipt_digest_is_rejected() {
    let value = intent();
    for bad in ["0".repeat(64), "x".repeat(64)] {
        let mut observed = serde_json::to_value(observation(
            &value,
            ExecutionTransportObservationV1::TerminalClaimed,
        ))
        .expect("serialize");
        observed["claimed_original_receipt_sha256"] = json!(bad);
        let observed: ExecutionObservationV1 =
            serde_json::from_value(observed).expect("deserialize");
        assert_eq!(
            plan_execution_reconciliation_v1(&value, &observed),
            Err(ExecutionEnvelopeErrorV1::InvalidDigest)
        );
    }
}

#[test]
fn nonterminal_observations_must_not_smuggle_terminal_receipt_digest() {
    let value = intent();
    for state in [
        ExecutionTransportObservationV1::AcceptedClaimed,
        ExecutionTransportObservationV1::Indeterminate,
        ExecutionTransportObservationV1::NotSentClaimed,
    ] {
        let mut observed = observation(&value, state);
        observed.claimed_original_receipt_sha256 =
            Some(Sha256Digest::for_bytes(b"fake-observation"));
        assert_eq!(
            plan_execution_reconciliation_v1(&value, &observed),
            Err(ExecutionEnvelopeErrorV1::InvalidObservation)
        );
    }
}

#[test]
fn stale_or_cross_scope_observations_fail_before_reconciliation() {
    let value = intent();
    let base = observation(&value, ExecutionTransportObservationV1::Indeterminate);
    let mut variants = Vec::new();
    let mut next = base.clone();
    next.operation_id.push('x');
    variants.push(next);
    let mut next = base.clone();
    next.scope_id.push('x');
    variants.push(next);
    let mut next = base.clone();
    next.destination_id.push('x');
    variants.push(next);
    let mut next = base.clone();
    next.generation += 1;
    variants.push(next);
    let mut next = base.clone();
    next.fence += 1;
    variants.push(next);
    let mut next = base.clone();
    next.authority_epoch += 1;
    variants.push(next);
    let mut next = base;
    next.request_sha256 = [5; 32];
    variants.push(next);
    for observed in variants {
        assert_eq!(
            plan_execution_reconciliation_v1(&value, &observed),
            Err(ExecutionEnvelopeErrorV1::ObservationMismatch)
        );
    }
}

#[test]
fn observation_schema_version_is_strict() {
    let value = intent();
    let mut observed = observation(&value, ExecutionTransportObservationV1::Indeterminate);
    observed.schema_version += 1;
    assert_eq!(
        plan_execution_reconciliation_v1(&value, &observed),
        Err(ExecutionEnvelopeErrorV1::InvalidVersion)
    );
}
