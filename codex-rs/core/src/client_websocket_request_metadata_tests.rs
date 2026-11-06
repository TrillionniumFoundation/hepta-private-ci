//! Request snapshots may reuse transport without losing wire or recovery identity.

use super::transport_selection_context;
use super::transport_selection_registry;
use crate::client::WebsocketConnectionIdentity;
use crate::model_provider_policy::ProviderWireSemantic;
use crate::model_provider_policy::canonical_sha256;
use crate::model_provider_policy::logical_responses_request;
use crate::model_provider_policy::prepare_model_provider_policy;
use crate::model_provider_policy::provider_websocket_wire_payload;
use crate::responses_metadata::CodexResponsesMetadata;
use crate::responses_metadata::CodexResponsesRequestKind;
use crate::responses_metadata::CompactionTurnMetadata;
use crate::responses_metadata::TurnMetadataWorkspace;
use crate::responses_metadata::TurnToolFunctionInfo;
use crate::responses_metadata::TurnToolNamespaceInfo;
use crate::responses_metadata::TurnToolSource;
use codex_analytics::CompactionImplementation;
use codex_analytics::CompactionPhase;
use codex_analytics::CompactionReason;
use codex_analytics::CompactionTrigger;
use codex_api::ResponseCreateWsRequest;
use codex_api::ResponsesApiRequest;
use codex_api::RetryConfig;
use codex_extension_api::ExtensionData;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderTransport;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;
use std::time::Duration;

#[test]
fn websocket_connection_reuse_keeps_dynamic_metadata_in_wire_and_recovery_identity() {
    let provider = codex_api::Provider {
        name: "provider-a".to_string(),
        base_url: "https://deployment.example.test/v1".to_string(),
        query_params: None,
        headers: http::HeaderMap::new(),
        retry: RetryConfig {
            max_attempts: 1,
            base_delay: Duration::from_millis(1),
            retry_429: false,
            retry_5xx: false,
            retry_transport: false,
        },
        stream_idle_timeout: Duration::from_secs(5),
    };
    let mut metadata = CodexResponsesMetadata::new(
        "installation-a".to_string(),
        "session-a".to_string(),
        "thread-1".to_string(),
        "window-a".to_string(),
    );
    metadata.request_kind = Some(CodexResponsesRequestKind::Turn);
    metadata.turn_id = Some("turn-1".to_string());
    metadata.sandbox_mode = Some("workspace-write".to_string());
    metadata.node_repl_auto_review_required = Some(false);
    metadata.node_repl_disabled = Some(false);
    let identity = WebsocketConnectionIdentity::from_provider(
        &provider,
        Some("feature-a"),
        &metadata,
        &http::HeaderMap::new(),
    )
    .expect("initial connection identity");

    let request = ResponsesApiRequest {
        model: "gpt-test".to_string(),
        instructions: "follow the prompt".to_string(),
        input: Vec::new(),
        tools: None,
        tool_choice: "auto".to_string(),
        parallel_tool_calls: false,
        reasoning: None,
        store: false,
        stream: true,
        stream_options: None,
        include: Vec::new(),
        service_tier: None,
        prompt_cache_key: None,
        text: None,
        client_metadata: None,
    };
    let wire_payload = |metadata: &CodexResponsesMetadata| {
        let mut payload = ResponseCreateWsRequest::from(&request);
        payload.client_metadata = Some(metadata.client_metadata());
        provider_websocket_wire_payload(&payload).expect("semantic WebSocket payload")
    };
    let initial_wire = wire_payload(&metadata);
    let initial_wire_digest = canonical_sha256(&initial_wire).expect("initial wire digest");
    let registry = transport_selection_registry(/*active*/ None);
    let stores = (
        ExtensionData::new("session-1"),
        ExtensionData::new("thread-1"),
        ExtensionData::new("turn-1"),
    );
    let context = transport_selection_context(
        &registry,
        (&stores.0, &stores.1, &stores.2),
        ModelProviderRequestKind::Turn,
    );
    let logical_request = logical_responses_request(&request);
    let wire_semantic = ProviderWireSemantic::new(
        &initial_wire,
        /*routing_hint*/ None,
        /*responses_lite*/ false,
    );
    let prepared = prepare_model_provider_policy(
        &context,
        &provider.name,
        &request.model,
        ModelProviderTransport::WebSocket,
        "wss://deployment.example.test/v1/responses",
        &logical_request,
        &wire_semantic,
        /*previous_response_id*/ None,
        /*generate*/ true,
    )
    .expect("prepared provider request");
    // Hold all other binding inputs fixed to isolate each metadata field's
    // contribution to the complete cold-recovery fingerprint.
    let recovery_fingerprint = |metadata: &CodexResponsesMetadata| {
        prepared
            .turn_recovery_fingerprint(
                &provider.headers,
                Some("feature-a"),
                &metadata.turn_recovery_compatibility_projection(),
                /*routing_hint*/ None,
                /*responses_lite*/ false,
            )
            .expect("cold-recovery fingerprint")
    };
    let initial_recovery = recovery_fingerprint(&metadata);

    let mut changed_node_review = metadata.clone();
    changed_node_review.node_repl_auto_review_required = Some(true);
    let mut changed_node_availability = metadata.clone();
    changed_node_availability.node_repl_disabled = Some(true);
    let mut changed_workspaces = metadata.clone();
    changed_workspaces.workspaces.insert(
        "/workspace/project".to_string(),
        TurnMetadataWorkspace {
            latest_git_commit_hash: Some("commit-after-prewarm".to_string()),
            has_changes: Some(true),
            ..Default::default()
        },
    );
    let mut changed_inventory = metadata.clone();
    changed_inventory.tool_namespaces_info = Some(BTreeMap::from([(
        "functions".to_string(),
        TurnToolNamespaceInfo {
            name: "functions".to_string(),
            functions: BTreeMap::from([(
                "node_repl".to_string(),
                TurnToolFunctionInfo {
                    name: "node_repl".to_string(),
                    direct: false,
                    code_mode_name: Some("functions.node_repl".to_string()),
                    deferred: false,
                    source: TurnToolSource::Harness,
                },
            )]),
        },
    )]));
    let mut changed_compaction = metadata;
    changed_compaction.request_kind = Some(CodexResponsesRequestKind::Compaction(
        CompactionTurnMetadata::new(
            CompactionTrigger::Auto,
            CompactionReason::ContextLimit,
            CompactionImplementation::ResponsesCompactionV2,
            CompactionPhase::MidTurn,
        ),
    ));
    for (field, changed_metadata) in [
        ("model Node REPL review requirement", changed_node_review),
        ("model Node REPL availability", changed_node_availability),
        ("Git workspaces", changed_workspaces),
        ("tool namespace inventory", changed_inventory),
        ("inline compaction", changed_compaction),
    ] {
        assert_eq!(
            identity,
            WebsocketConnectionIdentity::from_provider(
                &provider,
                Some("feature-a"),
                &changed_metadata,
                &http::HeaderMap::new(),
            )
            .expect("connection identity after request metadata changes"),
            "{field} must not force a new connection"
        );
        assert_ne!(
            initial_wire_digest,
            canonical_sha256(&wire_payload(&changed_metadata)).expect("changed wire digest"),
            "{field} must remain bound in the physical request"
        );
        assert_ne!(
            initial_recovery,
            recovery_fingerprint(&changed_metadata),
            "{field} must remain bound in the complete cold-recovery fingerprint"
        );
    }
}
