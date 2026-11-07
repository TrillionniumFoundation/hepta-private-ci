use super::test_model_client;
use super::test_model_info;
use super::transport_selection_context;
use super::transport_selection_registry;
use crate::Prompt;
use crate::client::WebsocketConnectionIdentity;
use crate::model_provider_policy::ProviderWireSemantic;
use crate::model_provider_policy::logical_responses_request;
use crate::model_provider_policy::prepare_model_provider_policy;
use crate::model_provider_policy::provider_websocket_wire_payload;
use crate::responses_metadata::CodexResponsesMetadata;
use crate::responses_metadata::CodexResponsesRequestKind;
use crate::responses_metadata::CompactionTurnMetadata;
use codex_analytics::CompactionImplementation;
use codex_analytics::CompactionPhase;
use codex_analytics::CompactionReason;
use codex_analytics::CompactionTrigger;
use codex_api::ResponseCreateWsRequest;
use codex_extension_api::ExtensionData;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderTransport;
use codex_model_provider_info::WireApi;
use codex_model_provider_info::create_oss_provider_with_base_url;
use codex_protocol::config_types::ReasoningSummary;
use codex_protocol::protocol::SessionSource;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;

fn metadata(kind: CodexResponsesRequestKind) -> CodexResponsesMetadata {
    let mut metadata = CodexResponsesMetadata::new(
        "installation".to_string(),
        "session".to_string(),
        "thread-1".to_string(),
        "window".to_string(),
    );
    metadata.turn_id = Some("turn-1".to_string());
    metadata.request_kind = Some(kind);
    metadata.sandbox_mode = Some("workspace-write".to_string());
    let configured = BTreeMap::from([("codex_security_surface".to_string(), "sdk".to_string())]);
    metadata.extra = configured.clone();
    metadata.websocket_connection_extra = Some(configured);
    metadata
}

fn compaction_kind(phase: CompactionPhase) -> CodexResponsesRequestKind {
    CodexResponsesRequestKind::Compaction(CompactionTurnMetadata::new(
        CompactionTrigger::Auto,
        CompactionReason::ContextLimit,
        CompactionImplementation::ResponsesCompactionV2,
        phase,
    ))
}

#[test]
fn compaction_phase_reuses_socket_identity_but_keeps_recovery_phase() {
    let provider = create_oss_provider_with_base_url("http://127.0.0.1:1/v1", WireApi::Responses)
        .to_api_provider(/*auth_mode*/ None)
        .expect("provider");
    let turn = metadata(CodexResponsesRequestKind::Turn);
    let connection = WebsocketConnectionIdentity::from_provider(
        &provider, /*beta_features_header*/ None, &turn,
    )
    .expect("turn connection identity");
    let recovery = serde_json::to_value(turn.turn_recovery_compatibility_projection())
        .expect("turn recovery projection");

    for phase in [CompactionPhase::PreTurn, CompactionPhase::MidTurn] {
        let compact = metadata(compaction_kind(phase));
        assert_eq!(
            connection,
            WebsocketConnectionIdentity::from_provider(
                &provider, /*beta_features_header*/ None, &compact,
            )
            .expect("compaction connection identity")
        );
        let compact_recovery =
            serde_json::to_value(compact.turn_recovery_compatibility_projection())
                .expect("compaction recovery projection");
        assert_ne!(recovery, compact_recovery);
        assert_eq!(compact_recovery["request_kind"], "compaction");
    }
}

#[test]
fn compaction_still_rebinds_sandbox_and_product_owned_connection_metadata() {
    let provider = create_oss_provider_with_base_url("http://127.0.0.1:1/v1", WireApi::Responses)
        .to_api_provider(/*auth_mode*/ None)
        .expect("provider");
    let turn = metadata(CodexResponsesRequestKind::Turn);
    let connection = WebsocketConnectionIdentity::from_provider(
        &provider, /*beta_features_header*/ None, &turn,
    )
    .expect("turn connection identity");
    let compact = metadata(compaction_kind(CompactionPhase::MidTurn));

    let mut changed_sandbox = compact.clone();
    changed_sandbox.sandbox_mode = Some("danger-full-access".to_string());
    assert_ne!(
        connection,
        WebsocketConnectionIdentity::from_provider(
            &provider,
            /*beta_features_header*/ None,
            &changed_sandbox,
        )
        .expect("different sandbox identity")
    );
    let mut changed_product = compact;
    let configured = BTreeMap::from([("codex_security_surface".to_string(), "other".to_string())]);
    changed_product.extra = configured.clone();
    changed_product.websocket_connection_extra = Some(configured);
    assert_ne!(
        connection,
        WebsocketConnectionIdentity::from_provider(
            &provider,
            /*beta_features_header*/ None,
            &changed_product,
        )
        .expect("different product identity")
    );
    let memory = metadata(CodexResponsesRequestKind::Memory);
    assert_ne!(
        connection,
        WebsocketConnectionIdentity::from_provider(
            &provider, /*beta_features_header*/ None, &memory,
        )
        .expect("memory request remains separate")
    );
}

#[test]
fn compaction_phase_still_reaches_wire_and_provider_request_binding() {
    let client = test_model_client(SessionSource::Exec);
    let provider = create_oss_provider_with_base_url("http://127.0.0.1:1/v1", WireApi::Responses)
        .to_api_provider(/*auth_mode*/ None)
        .expect("provider");
    let registry = transport_selection_registry(/*active*/ None);
    let stores = (
        ExtensionData::new("session-1"),
        ExtensionData::new("thread-1"),
        ExtensionData::new("turn-1"),
    );
    let mut bindings = Vec::new();
    for (kind, provider_kind, expected_kind) in [
        (
            CodexResponsesRequestKind::Turn,
            ModelProviderRequestKind::Turn,
            "turn",
        ),
        (
            compaction_kind(CompactionPhase::MidTurn),
            ModelProviderRequestKind::Compaction,
            "compaction",
        ),
    ] {
        let metadata = metadata(kind);
        // Hold model-visible input constant so only request phase distinguishes these bindings.
        let request = client
            .build_responses_request(
                &Prompt::default(),
                &test_model_info(),
                /*effort*/ None,
                ReasoningSummary::None,
                /*service_tier*/ None,
                &metadata,
                &provider,
            )
            .expect("Responses request");
        let payload = ResponseCreateWsRequest {
            client_metadata: Some(metadata.client_metadata()),
            ..ResponseCreateWsRequest::from(&request)
        };
        let encoded = serde_json::to_value(&payload).expect("encoded response.create");
        let encoded_metadata = encoded["client_metadata"]["x-codex-turn-metadata"]
            .as_str()
            .expect("request-scoped metadata carrier");
        let expected_metadata = metadata
            .turn_metadata_value()
            .expect("complete turn metadata");
        assert_eq!(
            serde_json::from_str::<serde_json::Value>(encoded_metadata)
                .expect("encoded turn metadata"),
            expected_metadata
        );
        let wire = provider_websocket_wire_payload(&payload).expect("physical wire semantics");
        assert_eq!(
            wire["client_metadata"]["x-codex-turn-metadata"],
            expected_metadata
        );
        assert_eq!(
            wire["client_metadata"]["x-codex-turn-metadata"]["request_kind"],
            expected_kind
        );
        let context = transport_selection_context(
            &registry,
            (&stores.0, &stores.1, &stores.2),
            provider_kind,
        );
        let prepared = prepare_model_provider_policy(
            &context,
            &provider.name,
            &request.model,
            ModelProviderTransport::WebSocket,
            "ws://127.0.0.1:1/v1/responses",
            &logical_responses_request(&request),
            &ProviderWireSemantic::new(
                &wire, /*routing_hint*/ None, /*responses_lite*/ false,
            ),
            /*previous_response_id*/ None,
            /*generate*/ true,
        )
        .expect("per-request provider binding");
        let input = prepared.invocation_input(&context);
        assert!(matches!(
            (expected_kind, input.request_kind),
            ("turn", ModelProviderRequestKind::Turn)
                | ("compaction", ModelProviderRequestKind::Compaction)
        ));
        let fingerprint = prepared
            .turn_recovery_fingerprint(
                &provider.headers,
                /*beta_features_header*/ None,
                &metadata.turn_recovery_compatibility_projection(),
                /*routing_hint*/ None,
                /*responses_lite*/ false,
            )
            .expect("request-specific recovery fingerprint");
        bindings.push((
            input.request_binding_id.to_string(),
            input.logical_request_sha256.as_str().to_string(),
            input.wire_semantic_sha256.as_str().to_string(),
            fingerprint.as_str().to_string(),
        ));
    }
    assert_eq!(bindings[0].1, bindings[1].1);
    assert_ne!(bindings[0].0, bindings[1].0);
    assert_ne!(bindings[0].2, bindings[1].2);
    assert_ne!(bindings[0].3, bindings[1].3);
}
