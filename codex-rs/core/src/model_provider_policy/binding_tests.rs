use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderTransport;
use http::HeaderMap;
use http::HeaderValue;
use serde_json::Value;

use super::EphemeralModelInputBinding;
use super::ModelProviderPolicyContext;
use super::ProviderRoutingHint;
use super::bytes_sha256;
use super::canonical_endpoint_sha256;
use super::canonical_sha256;
use super::ephemeral_input_witness_sha256;
use super::prepare_model_provider_attempt;
use super::prepare_model_provider_policy;

fn stores() -> (ExtensionData, ExtensionData, ExtensionData) {
    (
        ExtensionData::new("session"),
        ExtensionData::new("thread-1"),
        ExtensionData::new("turn-1"),
    )
}

#[test]
fn canonical_digest_is_independent_of_object_key_order() {
    let left: Value =
        serde_json::from_str(r#"{"b":{"y":2,"x":1},"a":0}"#).expect("left JSON should parse");
    let right: Value =
        serde_json::from_str(r#"{"a":0,"b":{"x":1,"y":2}}"#).expect("right JSON should parse");

    assert_eq!(
        canonical_sha256(&left).expect("left digest should succeed"),
        canonical_sha256(&right).expect("right digest should succeed")
    );
}

#[test]
fn retry_stable_binding_has_fresh_physical_attempt_identity() {
    let registry = ExtensionRegistryBuilder::<crate::config::Config>::new().build();
    let (session_store, thread_store, turn_store) = stores();
    let context = ModelProviderPolicyContext {
        registry: &registry,
        session_store: &session_store,
        thread_store: &thread_store,
        turn_store: &turn_store,
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        request_kind: ModelProviderRequestKind::Turn,
        ephemeral_input_cwd: None,
    };
    let logical = serde_json::json!({"input": [1, 2, 3], "model": "model-1"});
    let websocket_wire = serde_json::json!({
        "request": {"input": [3], "previous_response_id": "prior"},
        "routing_hint": "model=model-1;tier=fast",
    });
    let http_wire = serde_json::json!({
        "request": logical,
        "routing_hint": "model=model-1;tier=fast",
    });

    let first = prepare_model_provider_policy(
        &context,
        "provider-1",
        "model-1",
        ModelProviderTransport::WebSocket,
        "https://user:secret@example.test/responses?region=one&api_key=secret-one",
        &logical,
        &websocket_wire,
        Some("prior"),
        true,
    )
    .expect("first binding should succeed");
    let second = prepare_model_provider_policy(
        &context,
        "provider-1",
        "model-1",
        ModelProviderTransport::Http,
        "https://other:rotated@example.test/responses?api_key=rotated&region=two",
        &logical,
        &http_wire,
        None,
        true,
    )
    .expect("second binding should succeed");

    assert_eq!(first.request_binding_id, second.request_binding_id);
    assert_ne!(first.attempt_id, second.attempt_id);
    assert_eq!(first.provider_config_sha256, second.provider_config_sha256);
    assert_eq!(first.endpoint_sha256, second.endpoint_sha256);
    assert_ne!(first.wire_semantic_sha256, second.wire_semantic_sha256);
    assert_eq!(first.ephemeral_input_sha256, None);
    assert_eq!(first.ephemeral_input_witness_sha256, None);
}

#[test]
fn routing_hint_is_physical_wire_semantics_not_logical_identity() {
    let registry = ExtensionRegistryBuilder::<crate::config::Config>::new().build();
    let (session_store, thread_store, turn_store) = stores();
    let context = ModelProviderPolicyContext {
        registry: &registry,
        session_store: &session_store,
        thread_store: &thread_store,
        turn_store: &turn_store,
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        request_kind: ModelProviderRequestKind::Turn,
        ephemeral_input_cwd: None,
    };
    let logical = serde_json::json!({
        "input": [1],
        "model": "model-1",
        "service_tier": "fast",
    });
    let with_hint =
        serde_json::json!({"request": logical, "routing_hint": "model=model-1;tier=fast"});
    let without_hint = serde_json::json!({"request": logical, "routing_hint": null});

    let first = prepare_model_provider_policy(
        &context,
        "provider-1",
        "model-1",
        ModelProviderTransport::Http,
        "https://example.test/responses",
        &logical,
        &with_hint,
        None,
        true,
    )
    .expect("hinted binding should succeed");
    let second = prepare_model_provider_policy(
        &context,
        "provider-1",
        "model-1",
        ModelProviderTransport::Http,
        "https://example.test/responses",
        &logical,
        &without_hint,
        None,
        true,
    )
    .expect("unhinted binding should succeed");

    assert_eq!(first.request_binding_id, second.request_binding_id);
    assert_ne!(first.wire_semantic_sha256, second.wire_semantic_sha256);
}

#[test]
fn endpoint_digest_sorts_query_names_and_excludes_secrets() {
    let left = canonical_endpoint_sha256(
        "https://alice:secret@example.test/v1/responses?z=secret-z&a=secret-a&z=again",
    )
    .expect("left endpoint should parse");
    let right = canonical_endpoint_sha256(
        "https://bob:rotated@example.test/v1/responses?z=changed&z=other&a=changed",
    )
    .expect("right endpoint should parse");
    let different_path =
        canonical_endpoint_sha256("https://example.test/v2/responses?a=changed&z=changed&z=other")
            .expect("different endpoint should parse");
    let websocket =
        canonical_endpoint_sha256("wss://example.test/v1/responses?a=changed&z=changed&z=other")
            .expect("websocket endpoint should parse");

    assert_eq!(left, right);
    assert_ne!(left, different_path);
    assert_ne!(left, websocket);
}

#[test]
fn recovery_fingerprint_binds_deployment_and_typed_routing_without_binding_credentials() {
    let registry = ExtensionRegistryBuilder::<crate::config::Config>::new().build();
    let (session_store, thread_store, turn_store) = stores();
    let context = ModelProviderPolicyContext {
        registry: &registry,
        session_store: &session_store,
        thread_store: &thread_store,
        turn_store: &turn_store,
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        request_kind: ModelProviderRequestKind::Turn,
        ephemeral_input_cwd: None,
    };
    let logical = serde_json::json!({"input": ["hello"], "model": "model-1"});
    let prepare = |endpoint: &str, transport| {
        prepare_model_provider_policy(
            &context,
            "provider-1",
            "model-1",
            transport,
            endpoint,
            &logical,
            &serde_json::json!({"request": logical.clone()}),
            None,
            true,
        )
        .expect("prepared recovery request")
    };
    let http = prepare(
        "https://tenant.example.test/openai/responses?api-version=2026-08-01&api_key=secret-one",
        ModelProviderTransport::Http,
    );
    let websocket = prepare(
        "wss://tenant.example.test/openai/responses?api_key=secret-two&api-version=2026-08-01",
        ModelProviderTransport::WebSocket,
    );
    let changed_host = prepare(
        "https://other.example.test/openai/responses?api-version=2026-08-01&api_key=secret-one",
        ModelProviderTransport::Http,
    );
    let changed_version = prepare(
        "https://tenant.example.test/openai/responses?api-version=2026-09-01&api_key=secret-one",
        ModelProviderTransport::Http,
    );

    let mut headers = HeaderMap::new();
    headers.insert("openai-organization", HeaderValue::from_static("org-a"));
    headers.insert(
        "authorization",
        HeaderValue::from_static("Bearer secret-one"),
    );
    let routing_header = HeaderValue::from_static("model=model-1;tier=fast");
    let routing = ProviderRoutingHint::from_header(Some(&routing_header))
        .expect("routing hint")
        .expect("routing hint present");
    let fingerprint = |prepared: &super::PreparedModelProviderPolicy,
                       headers: &HeaderMap,
                       beta_features_header: Option<&str>,
                       compatibility: &serde_json::Value,
                       routing: Option<&ProviderRoutingHint>,
                       responses_lite| {
        prepared
            .turn_recovery_fingerprint(
                headers,
                beta_features_header,
                compatibility,
                routing,
                responses_lite,
            )
            .expect("recovery fingerprint")
    };
    let compatibility = serde_json::json!({"sandbox_mode": "workspace-write"});

    let baseline = fingerprint(
        &http,
        &headers,
        Some("feature-a"),
        &compatibility,
        Some(&routing),
        false,
    );
    assert_eq!(
        baseline,
        fingerprint(
            &websocket,
            &headers,
            Some("feature-a"),
            &compatibility,
            Some(&routing),
            false,
        ),
        "HTTP/WebSocket fallback and credential rotation must be stable"
    );
    assert_ne!(
        baseline,
        fingerprint(
            &changed_host,
            &headers,
            Some("feature-a"),
            &compatibility,
            Some(&routing),
            false,
        )
    );
    assert_ne!(
        baseline,
        fingerprint(
            &changed_version,
            &headers,
            Some("feature-a"),
            &compatibility,
            Some(&routing),
            false,
        )
    );

    let mut rotated_auth = headers.clone();
    rotated_auth.insert(
        "authorization",
        HeaderValue::from_static("Bearer secret-two"),
    );
    assert_eq!(
        baseline,
        fingerprint(
            &http,
            &rotated_auth,
            Some("feature-a"),
            &compatibility,
            Some(&routing),
            false,
        )
    );
    let mut changed_tenant = headers.clone();
    changed_tenant.insert("openai-organization", HeaderValue::from_static("org-b"));
    assert_ne!(
        baseline,
        fingerprint(
            &http,
            &changed_tenant,
            Some("feature-a"),
            &compatibility,
            Some(&routing),
            false,
        )
    );

    let mut changed_version_header = headers.clone();
    changed_version_header.insert("version", HeaderValue::from_static("2026-09-01"));
    assert_ne!(
        baseline,
        fingerprint(
            &http,
            &changed_version_header,
            Some("feature-a"),
            &compatibility,
            Some(&routing),
            false,
        )
    );

    let changed_routing_header = HeaderValue::from_static("model=model-1;tier=standard");
    let changed_routing = ProviderRoutingHint::from_header(Some(&changed_routing_header))
        .expect("changed routing hint")
        .expect("changed routing hint present");
    assert_ne!(
        baseline,
        fingerprint(
            &http,
            &headers,
            Some("feature-a"),
            &compatibility,
            Some(&changed_routing),
            false,
        )
    );
    assert_ne!(
        baseline,
        fingerprint(
            &http,
            &headers,
            Some("feature-a"),
            &compatibility,
            Some(&routing),
            true,
        )
    );
    assert_ne!(
        baseline,
        fingerprint(
            &http,
            &headers,
            Some("feature-b"),
            &compatibility,
            Some(&routing),
            false,
        )
    );
    assert_ne!(
        baseline,
        fingerprint(
            &http,
            &headers,
            Some("feature-a"),
            &serde_json::json!({"sandbox_mode": "danger-full-access"}),
            Some(&routing),
            false,
        )
    );
}

#[test]
fn two_phase_attempt_keeps_base_identity_and_binds_effective_input() {
    let registry = ExtensionRegistryBuilder::<crate::config::Config>::new().build();
    let (session_store, thread_store, turn_store) = stores();
    let mut context = ModelProviderPolicyContext {
        registry: &registry,
        session_store: &session_store,
        thread_store: &thread_store,
        turn_store: &turn_store,
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        request_kind: ModelProviderRequestKind::Turn,
        ephemeral_input_cwd: None,
    };
    let base = serde_json::json!({ "input": ["base"], "model": "model-1" });
    let effective = serde_json::json!({
        "input": ["base", "attempt-local-reference"],
        "model": "model-1",
    });
    let effective_wire = serde_json::json!({
        "request": effective,
        "routing_hint": "model=model-1",
    });
    let legacy = prepare_model_provider_policy(
        &context,
        "provider-1",
        "model-1",
        ModelProviderTransport::Http,
        "https://example.test/v1/responses",
        &base,
        &serde_json::json!({ "request": base.clone() }),
        None,
        true,
    )
    .expect("legacy prepared attempt");
    let envelope = prepare_model_provider_attempt(
        &context,
        "provider-1",
        "model-1",
        ModelProviderTransport::Http,
        "https://example.test/v1/responses",
        &base,
        None,
        true,
    )
    .expect("attempt envelope");
    let attempt_id = envelope.attempt_id().to_string();
    let request_binding_id = envelope.request_binding_id.clone();
    assert_eq!(
        request_binding_id,
        "model-provider-request:v1:ead473ccaf97b6ddfeaecef46d42e455e46e2dad258697254f1f84e3ceec385c"
    );
    assert_eq!(
        envelope.base_logical_request_sha256(),
        &canonical_sha256(&base).expect("base digest")
    );

    let input_sha256 = bytes_sha256(b"rendered-input").expect("input digest");
    let authority_sha256 = bytes_sha256(b"host-authority").expect("authority digest");
    let prepared = envelope
        .finalize(
            &effective,
            &effective_wire,
            Some(EphemeralModelInputBinding::new(
                input_sha256.clone(),
                authority_sha256,
            )),
        )
        .expect("finalized attempt");

    assert_eq!(prepared.attempt_id, attempt_id);
    assert_eq!(prepared.request_binding_id, request_binding_id);
    assert_eq!(prepared.request_binding_id, legacy.request_binding_id);
    assert_eq!(
        prepared.logical_request_sha256,
        canonical_sha256(&effective).expect("effective digest")
    );
    assert_ne!(
        prepared.logical_request_sha256,
        canonical_sha256(&base).expect("base digest")
    );
    assert_eq!(prepared.ephemeral_input_sha256, Some(input_sha256));
    assert!(prepared.ephemeral_input_witness_sha256.is_some());
    assert_eq!(legacy.ephemeral_input_sha256, None);
    assert_eq!(legacy.ephemeral_input_witness_sha256, None);

    let missing_pair = prepare_model_provider_attempt(
        &context,
        "provider-1",
        "model-1",
        ModelProviderTransport::Http,
        "https://example.test/v1/responses",
        &base,
        None,
        true,
    )
    .expect("attempt envelope")
    .finalize(&effective, &effective_wire, None);
    let missing_pair = match missing_pair {
        Ok(_) => panic!("changed effective input without a digest pair must fail"),
        Err(error) => error,
    };
    assert_eq!(
        missing_pair.reason_code(),
        "ephemeral_model_input_effective_binding_mismatch"
    );

    let orphan_pair = prepare_model_provider_attempt(
        &context,
        "provider-1",
        "model-1",
        ModelProviderTransport::Http,
        "https://example.test/v1/responses",
        &base,
        None,
        true,
    )
    .expect("attempt envelope")
    .finalize(
        &base,
        &serde_json::json!({ "request": base.clone() }),
        Some(EphemeralModelInputBinding::new(
            bytes_sha256(b"input").expect("input digest"),
            bytes_sha256(b"authority").expect("authority digest"),
        )),
    );
    let orphan_pair = match orphan_pair {
        Ok(_) => panic!("digest pair without changed effective input must fail"),
        Err(error) => error,
    };
    assert_eq!(
        orphan_pair.reason_code(),
        "ephemeral_model_input_effective_binding_mismatch"
    );

    context.thread_id = "thread-other".to_string();
    context.turn_id = "turn-other".to_string();
    context.request_kind = ModelProviderRequestKind::Compaction;
    let invocation = prepared.invocation_input(&context);
    assert_eq!(invocation.thread_id, "thread-1");
    assert_eq!(invocation.turn_id, "turn-1");
    assert_eq!(invocation.request_kind, ModelProviderRequestKind::Turn);
    assert!(invocation.ephemeral_input_sha256.is_some());
    assert!(invocation.ephemeral_input_witness_sha256.is_some());
}

#[test]
fn ephemeral_witness_freezes_physical_attempt_semantics() {
    let digest = |value: &str| bytes_sha256(value.as_bytes()).expect("digest");
    let logical = digest("logical");
    let wire = digest("wire");
    let previous = digest("previous");
    let binding = EphemeralModelInputBinding::new(digest("input"), digest("authority"));
    let witness = ephemeral_input_witness_sha256(
        "attempt-1",
        "thread-1",
        "turn-1",
        "request-1",
        ModelProviderTransport::Http,
        &logical,
        &wire,
        Some(&previous),
        true,
        &binding,
    )
    .expect("witness");
    assert_eq!(
        witness.as_str(),
        "79b42c3f27d21113b2d443ed3829a69d8af919f475ce087a029c90f64fc46c52"
    );
    for changed in [
        ephemeral_input_witness_sha256(
            "attempt-2",
            "thread-1",
            "turn-1",
            "request-1",
            ModelProviderTransport::Http,
            &logical,
            &wire,
            Some(&previous),
            true,
            &binding,
        ),
        ephemeral_input_witness_sha256(
            "attempt-1",
            "thread-1",
            "turn-1",
            "request-1",
            ModelProviderTransport::WebSocket,
            &logical,
            &wire,
            Some(&previous),
            true,
            &binding,
        ),
        ephemeral_input_witness_sha256(
            "attempt-1",
            "thread-1",
            "turn-1",
            "request-1",
            ModelProviderTransport::Http,
            &logical,
            &wire,
            None,
            true,
            &binding,
        ),
        ephemeral_input_witness_sha256(
            "attempt-1",
            "thread-1",
            "turn-1",
            "request-1",
            ModelProviderTransport::Http,
            &logical,
            &digest("changed-wire"),
            Some(&previous),
            true,
            &binding,
        ),
        ephemeral_input_witness_sha256(
            "attempt-1",
            "thread-1",
            "turn-1",
            "request-1",
            ModelProviderTransport::Http,
            &logical,
            &wire,
            Some(&previous),
            true,
            &EphemeralModelInputBinding::new(digest("input"), digest("changed-authority")),
        ),
        ephemeral_input_witness_sha256(
            "attempt-1",
            "thread-2",
            "turn-1",
            "request-1",
            ModelProviderTransport::Http,
            &logical,
            &wire,
            Some(&previous),
            true,
            &binding,
        ),
        ephemeral_input_witness_sha256(
            "attempt-1",
            "thread-1",
            "turn-2",
            "request-1",
            ModelProviderTransport::Http,
            &logical,
            &wire,
            Some(&previous),
            true,
            &binding,
        ),
    ] {
        assert_ne!(changed.expect("changed witness"), witness);
    }
}
