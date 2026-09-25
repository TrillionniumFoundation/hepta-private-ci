use codex_api::CompactionInput;
use codex_api::ResponseCreateWsRequest;
use codex_api::ResponsesApiRequest;
use codex_api::WS_REQUEST_HEADER_TRACEPARENT_CLIENT_METADATA_KEY;
use codex_api::WS_REQUEST_HEADER_TRACESTATE_CLIENT_METADATA_KEY;
use codex_extension_api::ModelProviderPolicyError;
use http::HeaderValue;
use serde::Serialize;
use serde_json::Value;
use std::collections::HashMap;

const TURN_METADATA_KEY: &str = "x-codex-turn-metadata";
const TURN_STARTED_AT_UNIX_MS_KEY: &str = "turn_started_at_unix_ms";
const TURN_STATE_KEY: &str = "x-codex-turn-state";
const WS_REQUEST_START_MS_KEY: &str = "x-codex-ws-stream-request-start-ms";
const WS_RESPONSES_LITE_KEY: &str = "ws_request_header_x_openai_internal_codex_responses_lite";

/// Exact, secret-free routing hint attached to a provider transport.
///
/// The value is captured from the header that was actually inserted into an
/// HTTP request or used to open a WebSocket connection. A later desired hint
/// must never replace the sticky value bound to an already-open connection.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(transparent)]
pub(crate) struct ProviderRoutingHint(String);

impl ProviderRoutingHint {
    pub(crate) fn from_header(
        value: Option<&HeaderValue>,
    ) -> Result<Option<Self>, ModelProviderPolicyError> {
        value
            .map(|value| {
                value
                    .to_str()
                    .map(|value| Self(value.to_string()))
                    .map_err(|error| {
                        ModelProviderPolicyError::new(
                            "model_provider_policy_invalid_routing_hint",
                            format!("provider routing hint is not valid header text: {error}"),
                        )
                    })
            })
            .transpose()
    }

    pub(crate) fn as_str(&self) -> &str {
        &self.0
    }
}

/// Reads Responses Lite from the exact HTTP header carrier.
///
/// Absence means the normal Responses contract. The only accepted enabled
/// representation is the literal `true` inserted by Core.
pub(crate) fn responses_lite_from_http_header(
    value: Option<&HeaderValue>,
) -> Result<bool, ModelProviderPolicyError> {
    let value = value
        .map(HeaderValue::to_str)
        .transpose()
        .map_err(|error| invalid_responses_lite(error.to_string()))?;
    responses_lite_from_text(value)
}

/// Reads Responses Lite from the exact WebSocket response.create metadata.
pub(crate) fn responses_lite_from_ws_metadata(
    client_metadata: Option<&HashMap<String, String>>,
    key: &str,
) -> Result<bool, ModelProviderPolicyError> {
    responses_lite_from_text(
        client_metadata
            .and_then(|client_metadata| client_metadata.get(key))
            .map(String::as_str),
    )
}

/// Builds the stable semantic payload for one WebSocket response.create.
///
/// The encoded provider request remains unchanged. This projection removes
/// transport tracing, request timing, opaque sticky turn state, and the
/// Responses Lite carrier (which is bound separately as a typed value). All
/// other client metadata remains in the physical wire identity. The canonical
/// turn-metadata JSON string is represented structurally so its request-start
/// timestamp can be excluded without discarding stable turn semantics.
pub(crate) fn provider_websocket_wire_payload(
    payload: &ResponseCreateWsRequest<'_>,
) -> Result<Value, ModelProviderPolicyError> {
    let mut semantic = serde_json::to_value(payload).map_err(|error| {
        ModelProviderPolicyError::new(
            "model_provider_policy_serialization_failed",
            format!("failed to serialize WebSocket provider payload: {error}"),
        )
    })?;
    let Some(metadata) = semantic
        .get_mut("client_metadata")
        .and_then(Value::as_object_mut)
    else {
        return Ok(semantic);
    };

    for key in [
        WS_REQUEST_HEADER_TRACEPARENT_CLIENT_METADATA_KEY,
        WS_REQUEST_HEADER_TRACESTATE_CLIENT_METADATA_KEY,
        WS_REQUEST_START_MS_KEY,
        TURN_STATE_KEY,
        WS_RESPONSES_LITE_KEY,
    ] {
        metadata.remove(key);
    }

    if let Some(turn_metadata) = metadata.get_mut(TURN_METADATA_KEY) {
        let encoded = turn_metadata.as_str().ok_or_else(|| {
            invalid_ws_metadata("turn metadata carrier must be a JSON string".to_string())
        })?;
        let mut structured = serde_json::from_str::<Value>(encoded).map_err(|error| {
            invalid_ws_metadata(format!("failed to parse turn metadata JSON: {error}"))
        })?;
        let object = structured.as_object_mut().ok_or_else(|| {
            invalid_ws_metadata("turn metadata JSON must encode an object".to_string())
        })?;
        object.remove(TURN_STARTED_AT_UNIX_MS_KEY);
        *turn_metadata = structured;
    }

    if metadata.is_empty()
        && let Some(object) = semantic.as_object_mut()
    {
        object.remove("client_metadata");
    }
    Ok(semantic)
}

fn invalid_ws_metadata(detail: String) -> ModelProviderPolicyError {
    ModelProviderPolicyError::new(
        "model_provider_policy_invalid_ws_metadata",
        format!("invalid WebSocket provider metadata: {detail}"),
    )
}

fn responses_lite_from_text(value: Option<&str>) -> Result<bool, ModelProviderPolicyError> {
    match value {
        None => Ok(false),
        Some("true") => Ok(true),
        Some(value) => Err(invalid_responses_lite(format!(
            "expected absent or `true`, found `{value}`"
        ))),
    }
}

fn invalid_responses_lite(detail: String) -> ModelProviderPolicyError {
    ModelProviderPolicyError::new(
        "model_provider_policy_invalid_responses_lite",
        format!("invalid Responses Lite transport marker: {detail}"),
    )
}

/// Versioned behavior-affecting values for one physical provider send.
///
/// Authentication, attestation, trace IDs, request timestamps and transport
/// retry counters are deliberately excluded. `routing_hint` and
/// `responses_lite` are explicit because they live outside the encoded model
/// request on at least one supported transport.
#[derive(Serialize)]
pub(crate) struct ProviderWireSemantic<'a, T> {
    schema: &'static str,
    payload: &'a T,
    routing_hint: Option<&'a ProviderRoutingHint>,
    responses_lite: bool,
}

impl<'a, T> ProviderWireSemantic<'a, T> {
    pub(crate) fn new(
        payload: &'a T,
        routing_hint: Option<&'a ProviderRoutingHint>,
        responses_lite: bool,
    ) -> Self {
        Self {
            schema: "model-provider-wire:v1",
            payload,
            routing_hint,
            responses_lite,
        }
    }
}

/// Retry-stable model-visible request semantics for provider governance.
///
/// Cache and client metadata may change across reconnects or process restarts
/// without changing what the model is asked to do. They remain available to
/// the physical wire binding, but do not mint a new logical replay identity.
pub(crate) fn logical_responses_request(request: &ResponsesApiRequest) -> ResponsesApiRequest {
    let mut logical = request.clone();
    logical.prompt_cache_key = None;
    logical.client_metadata = None;
    logical
}

/// Retry-stable model-visible semantics for `/responses/compact`.
///
/// The cache key remains part of the physical wire binding, but changing it
/// alone must not mint a new logical compaction identity.
pub(crate) fn logical_compaction_request<'a>(request: &CompactionInput<'a>) -> CompactionInput<'a> {
    let mut logical = request.clone();
    logical.prompt_cache_key = None;
    logical
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use codex_api::CompactionInput;
    use codex_api::ResponseCreateWsRequest;
    use codex_api::ResponsesApiRequest;
    use codex_api::WS_REQUEST_HEADER_TRACEPARENT_CLIENT_METADATA_KEY;
    use codex_api::WS_REQUEST_HEADER_TRACESTATE_CLIENT_METADATA_KEY;
    use http::HeaderValue;

    use super::ProviderRoutingHint;
    use super::ProviderWireSemantic;
    use super::TURN_METADATA_KEY;
    use super::TURN_STATE_KEY;
    use super::WS_REQUEST_START_MS_KEY;
    use super::WS_RESPONSES_LITE_KEY;
    use super::logical_compaction_request;
    use super::logical_responses_request;
    use super::provider_websocket_wire_payload;
    use super::responses_lite_from_http_header;
    use super::responses_lite_from_ws_metadata;
    use crate::model_provider_policy::binding::canonical_sha256;

    fn request() -> ResponsesApiRequest {
        ResponsesApiRequest {
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
            service_tier: Some("priority".to_string()),
            prompt_cache_key: Some("cache-a".to_string()),
            text: None,
            client_metadata: Some(HashMap::from([(
                "request_timestamp".to_string(),
                "1".to_string(),
            )])),
        }
    }

    fn compaction_request(cache_key: Option<&'static str>) -> CompactionInput<'static> {
        CompactionInput {
            model: "gpt-test",
            input: &[],
            instructions: "compact faithfully",
            tools: None,
            parallel_tool_calls: false,
            reasoning: None,
            service_tier: Some("priority"),
            prompt_cache_key: cache_key,
            text: None,
        }
    }

    #[test]
    fn logical_request_excludes_cache_and_client_metadata_only() {
        let request = request();
        let logical = logical_responses_request(&request);

        assert_eq!(logical.model, "gpt-test");
        assert_eq!(logical.service_tier.as_deref(), Some("priority"));
        assert_eq!(logical.prompt_cache_key, None);
        assert_eq!(logical.client_metadata, None);

        let mut changed = request;
        changed.prompt_cache_key = Some("cache-b".to_string());
        changed.client_metadata = Some(HashMap::from([(
            "request_timestamp".to_string(),
            "2".to_string(),
        )]));
        assert_eq!(
            canonical_sha256(&logical).expect("logical digest"),
            canonical_sha256(&logical_responses_request(&changed)).expect("changed digest")
        );
    }

    #[test]
    fn model_and_service_tier_remain_logical_identity() {
        let request = request();
        let digest = canonical_sha256(&logical_responses_request(&request)).expect("base digest");

        let mut changed_model = request.clone();
        changed_model.model = "gpt-other".to_string();
        assert_ne!(
            digest,
            canonical_sha256(&logical_responses_request(&changed_model)).expect("model digest")
        );

        let mut changed_tier = request;
        changed_tier.service_tier = Some("flex".to_string());
        assert_ne!(
            digest,
            canonical_sha256(&logical_responses_request(&changed_tier)).expect("tier digest")
        );
    }

    #[test]
    fn logical_compaction_excludes_only_cache_key() {
        let request = compaction_request(Some("cache-a"));
        let logical = logical_compaction_request(&request);
        let mut expected = serde_json::to_value(&request).expect("wire request");
        expected
            .as_object_mut()
            .expect("compaction request object")
            .remove("prompt_cache_key");
        assert_eq!(
            serde_json::to_value(&logical).expect("logical request"),
            expected
        );

        let changed = compaction_request(Some("cache-b"));
        assert_eq!(
            canonical_sha256(&logical).expect("logical digest"),
            canonical_sha256(&logical_compaction_request(&changed)).expect("changed digest")
        );
    }

    #[test]
    fn compaction_wire_digest_binds_cache_routing_and_responses_lite() {
        let request = compaction_request(Some("cache-a"));
        let changed_cache = compaction_request(Some("cache-b"));
        let hint_a = ProviderRoutingHint::from_header(Some(&HeaderValue::from_static("route-a")))
            .expect("valid hint")
            .expect("present hint");
        let hint_b = ProviderRoutingHint::from_header(Some(&HeaderValue::from_static("route-b")))
            .expect("valid hint")
            .expect("present hint");
        let base = canonical_sha256(&ProviderWireSemantic::new(&request, Some(&hint_a), false))
            .expect("base wire digest");

        assert_ne!(
            base,
            canonical_sha256(&ProviderWireSemantic::new(
                &changed_cache,
                Some(&hint_a),
                false,
            ))
            .expect("cache wire digest")
        );
        assert_ne!(
            base,
            canonical_sha256(&ProviderWireSemantic::new(&request, Some(&hint_b), false))
                .expect("routing wire digest")
        );
        assert_ne!(
            base,
            canonical_sha256(&ProviderWireSemantic::new(&request, Some(&hint_a), true))
                .expect("responses-lite wire digest")
        );
    }

    #[test]
    fn wire_digest_binds_routing_hint_and_responses_lite() {
        let request = request();
        let hint_a = ProviderRoutingHint::from_header(Some(&HeaderValue::from_static(
            "model=gpt-test;tier=priority",
        )))
        .expect("valid hint")
        .expect("present hint");
        let hint_b = ProviderRoutingHint::from_header(Some(&HeaderValue::from_static(
            "model=gpt-test;tier=flex",
        )))
        .expect("valid hint")
        .expect("present hint");

        let base = canonical_sha256(&ProviderWireSemantic::new(&request, Some(&hint_a), false))
            .expect("base wire digest");
        assert_ne!(
            base,
            canonical_sha256(&ProviderWireSemantic::new(&request, Some(&hint_b), false,))
                .expect("routing wire digest")
        );
        assert_ne!(
            base,
            canonical_sha256(&ProviderWireSemantic::new(&request, Some(&hint_a), true,))
                .expect("responses-lite wire digest")
        );
        assert_eq!(hint_a.as_str(), "model=gpt-test;tier=priority");
    }

    #[test]
    fn invalid_header_text_is_rejected() {
        let invalid = HeaderValue::from_bytes(&[0xff]).expect("opaque header value");
        let error = ProviderRoutingHint::from_header(Some(&invalid))
            .expect_err("non-text hint must fail closed");
        assert_eq!(
            error.reason_code(),
            "model_provider_policy_invalid_routing_hint"
        );
    }

    #[test]
    fn responses_lite_is_derived_from_exact_transport_carriers() {
        assert!(!responses_lite_from_http_header(None).expect("absent HTTP marker"));
        assert!(
            responses_lite_from_http_header(Some(&HeaderValue::from_static("true")))
                .expect("enabled HTTP marker")
        );

        let key = "responses-lite";
        let metadata = HashMap::from([(key.to_string(), "true".to_string())]);
        assert!(
            responses_lite_from_ws_metadata(Some(&metadata), key)
                .expect("enabled websocket marker")
        );
        assert!(!responses_lite_from_ws_metadata(None, key).expect("absent websocket marker"));
    }

    #[test]
    fn websocket_wire_payload_excludes_only_volatile_metadata() {
        let request = request();
        let mut payload = ResponseCreateWsRequest::from(&request);
        payload.client_metadata = Some(HashMap::from([
            ("stable".to_string(), "alpha".to_string()),
            (
                WS_REQUEST_HEADER_TRACEPARENT_CLIENT_METADATA_KEY.to_string(),
                "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01".to_string(),
            ),
            (
                WS_REQUEST_HEADER_TRACESTATE_CLIENT_METADATA_KEY.to_string(),
                "vendor=a".to_string(),
            ),
            (WS_REQUEST_START_MS_KEY.to_string(), "1".to_string()),
            (TURN_STATE_KEY.to_string(), "opaque-a".to_string()),
            (WS_RESPONSES_LITE_KEY.to_string(), "true".to_string()),
            (
                TURN_METADATA_KEY.to_string(),
                r#"{"turn_id":"turn-1","turn_started_at_unix_ms":1}"#.to_string(),
            ),
        ]));
        let base = provider_websocket_wire_payload(&payload).expect("base semantic payload");

        let metadata = payload.client_metadata.as_mut().expect("metadata");
        metadata.insert(
            WS_REQUEST_HEADER_TRACEPARENT_CLIENT_METADATA_KEY.to_string(),
            "trace-b".to_string(),
        );
        metadata.insert(
            WS_REQUEST_HEADER_TRACESTATE_CLIENT_METADATA_KEY.to_string(),
            "vendor=b".to_string(),
        );
        metadata.insert(WS_REQUEST_START_MS_KEY.to_string(), "2".to_string());
        metadata.insert(TURN_STATE_KEY.to_string(), "opaque-b".to_string());
        metadata.insert(
            TURN_METADATA_KEY.to_string(),
            r#"{"turn_id":"turn-1","turn_started_at_unix_ms":2}"#.to_string(),
        );
        let changed_volatile =
            provider_websocket_wire_payload(&payload).expect("changed volatile payload");
        assert_eq!(
            canonical_sha256(&base).expect("base digest"),
            canonical_sha256(&changed_volatile).expect("volatile digest")
        );

        payload
            .client_metadata
            .as_mut()
            .expect("metadata")
            .insert("stable".to_string(), "beta".to_string());
        let changed_stable =
            provider_websocket_wire_payload(&payload).expect("changed stable payload");
        assert_ne!(
            canonical_sha256(&base).expect("base digest"),
            canonical_sha256(&changed_stable).expect("stable digest")
        );
    }

    #[test]
    fn malformed_websocket_turn_metadata_fails_closed() {
        let request = request();
        let mut payload = ResponseCreateWsRequest::from(&request);
        payload.client_metadata = Some(HashMap::from([(
            TURN_METADATA_KEY.to_string(),
            "not-json".to_string(),
        )]));

        let error = provider_websocket_wire_payload(&payload)
            .expect_err("malformed turn metadata must fail closed");
        assert_eq!(
            error.reason_code(),
            "model_provider_policy_invalid_ws_metadata"
        );
    }

    #[test]
    fn invalid_responses_lite_marker_fails_closed() {
        let error = responses_lite_from_http_header(Some(&HeaderValue::from_static("false")))
            .expect_err("false must be represented by absence");
        assert_eq!(
            error.reason_code(),
            "model_provider_policy_invalid_responses_lite"
        );

        let metadata = HashMap::from([("responses-lite".to_string(), "1".to_string())]);
        assert!(
            responses_lite_from_ws_metadata(Some(&metadata), "responses-lite").is_err(),
            "non-canonical websocket marker must fail closed"
        );
    }
}
