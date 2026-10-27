use super::*;
use codex_hepta_agentd::AgentdCapability;
use codex_hepta_agentd::AgentdCapabilitySet;
use codex_hepta_agentd::CognitiveContextExecutionV1;
use pretty_assertions::assert_eq;

// Explicit serialization fixture, never a model execution or authority receipt.
fn context() -> CognitiveContextExecutionV1 {
    let mut neural = serde_json::json!({"source":"selected_initial",
        "owner_id":"00000000-0000-4000-8000-000000000220","body_generation":1,
        "model_generation":1,"execution_ns":1,"input_tokens":1,"observed_rss_bytes":1});
    for name in [
        "parameter_file_digest",
        "adapter_digest",
        "backbone_digest",
        "contract_digest",
        "ready_digest",
        "load_request_digest",
        "load_reservation_digest",
        "load_output_digest",
        "forward_request_digest",
        "forward_reservation_digest",
        "forward_payload_digest",
        "input_digest",
        "response_digest",
        "logits_digest",
    ] {
        neural[name] = serde_json::json!(Digest32::of_bytes(name.as_bytes()).to_string());
    }
    serde_json::from_value(serde_json::json!({"schema_version":1,"neural":neural,
        "snapshot":{"snapshot_digest":"original-cut","read_digest":"original-read",
            "omitted_records":0,"items":[],"plan":null}}))
    .unwrap()
}

#[test]
fn provenance_changes_only_nonprompt_metadata_and_existing_payload_binding() {
    let mut context = context();
    let original = serde_json::to_string(&context.snapshot).unwrap();
    let first = cognitive_context::prepare("first-native-request", &context).unwrap();
    context.neural.as_mut().unwrap().execution_ns += 1;
    let changed = cognitive_context::prepare("first-native-request", &context).unwrap();
    let another = cognitive_context::prepare("another-native-request", &context).unwrap();
    assert_eq!(first.additional_context, changed.additional_context);
    assert_eq!(
        first.additional_context["hepta-cognitive-owner"].value,
        original
    );
    assert_eq!(
        first.owner_context_digest,
        control::digest(original.as_bytes())
    );
    assert_eq!(first.metadata.len(), 1);
    let (key, value) = first.metadata.iter().next().unwrap();
    assert!(key.len() <= 64 && value.len() == 64 && value.len() <= 128);
    assert!(
        key.bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_')
    );
    assert!(!value.parse::<Digest32>().unwrap().is_zero());
    assert_ne!(first.metadata, changed.metadata);
    assert_ne!(changed.metadata, another.metadata);
    let payload = |attachment: cognitive_context::CognitiveAttachmentV1| {
        serde_json::to_vec(&TurnStartParams {
            additional_context: Some(attachment.additional_context),
            responsesapi_client_metadata: Some(attachment.metadata),
            ..Default::default()
        })
        .unwrap()
    };
    let mut intent = binding().intent;
    intent.payload_digest = Digest32::of_bytes(&payload(first));
    intent.lease_payload_digest = intent.payload_digest;
    let before = codex_request_digest(&intent);
    intent.payload_digest = Digest32::of_bytes(&payload(changed));
    intent.lease_payload_digest = intent.payload_digest;
    assert_ne!(before, codex_request_digest(&intent));
}

#[test]
fn missing_unknown_or_downgraded_execution_capability_is_refused() {
    let old = AgentdCapability::new(
        COGNITIVE_CONTEXT_REVALIDATION_CAPABILITY,
        /*major*/ 1,
        /*minor*/ 0,
    )
    .unwrap();
    let new = AgentdCapability::new(
        COGNITIVE_CONTEXT_EXECUTION_CAPABILITY_V1,
        /*major*/ 1,
        /*minor*/ 0,
    )
    .unwrap();
    assert!(
        cognitive_context::require_capabilities(
            &AgentdCapabilitySet::new(vec![old.clone()]).unwrap()
        )
        .is_err()
    );
    let mut supported = AgentdCapabilitySet::new(vec![old, new]).unwrap();
    cognitive_context::require_capabilities(&supported).unwrap();
    supported.schema_version += 1;
    assert!(cognitive_context::require_capabilities(&supported).is_err());
    supported.schema_version -= 1;
    supported
        .capabilities
        .iter_mut()
        .find(|value| value.id == COGNITIVE_CONTEXT_EXECUTION_CAPABILITY_V1)
        .unwrap()
        .major += 1;
    assert!(cognitive_context::require_capabilities(&supported).is_err());
}
