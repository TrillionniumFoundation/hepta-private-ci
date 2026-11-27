use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use anyhow::anyhow;
use bytes::Bytes;
use codex_api::AuthProvider;
use codex_api::EncodedRequestBodyObserver;
use codex_api::Provider;
use codex_api::RequestDispatchMetadata;
use codex_api::ResponsesApiRequest;
use codex_api::ResponsesClient;
use codex_api::ResponsesOptions;
use codex_api::RetryConfig;
use codex_client::HttpTransport;
use codex_client::Request;
use codex_client::RequestBody;
use codex_client::Response;
use codex_client::StreamResponse;
use codex_client::TransportError;
use codex_protocol::models::ContentItem;
use codex_protocol::models::ResponseItem;
use futures::future::BoxFuture;
use http::HeaderMap;
use http::StatusCode;
use pretty_assertions::assert_eq;

const COMPLETE_USER_TEXT: &str = "snowman: ☃\ncontrol:\u{0001}";

#[derive(Clone)]
struct RecordingTransport {
    requests: Arc<Mutex<Vec<Request>>>,
}

impl HttpTransport for RecordingTransport {
    async fn execute(&self, _request: Request) -> Result<Response, TransportError> {
        Err(TransportError::Build(
            "unexpected non-streaming request".to_owned(),
        ))
    }

    async fn stream(&self, request: Request) -> Result<StreamResponse, TransportError> {
        self.requests
            .lock()
            .map_err(|_| TransportError::Build("request recorder poisoned".to_owned()))?
            .push(request);
        Ok(StreamResponse {
            status: StatusCode::OK,
            headers: HeaderMap::new(),
            bytes: Box::pin(futures::stream::iter(
                Vec::<Result<Bytes, TransportError>>::new(),
            )),
        })
    }
}

struct RecordingObserver {
    bodies: Arc<Mutex<Vec<Vec<u8>>>>,
}

impl fmt::Debug for RecordingObserver {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("RecordingObserver")
    }
}

impl EncodedRequestBodyObserver for RecordingObserver {
    fn observe_encoded_body<'a>(&'a self, body: &'a [u8]) -> BoxFuture<'a, Result<(), String>> {
        Box::pin(async move {
            self.bodies
                .lock()
                .map_err(|_| "body recorder poisoned".to_owned())?
                .push(body.to_vec());
            Ok(())
        })
    }
}

struct NoAuth;

impl AuthProvider for NoAuth {
    fn add_auth_headers(&self, _headers: &mut HeaderMap) {}
}

fn request(user_text: &str) -> ResponsesApiRequest {
    ResponsesApiRequest {
        model: "model".to_owned(),
        instructions: String::new(),
        input: vec![
            ResponseItem::Message {
                id: None,
                role: "developer".to_owned(),
                content: vec![ContentItem::InputText {
                    text: "follow policy".to_owned(),
                }],
                phase: None,
                internal_chat_message_metadata_passthrough: None,
            },
            ResponseItem::Message {
                id: None,
                role: "user".to_owned(),
                content: vec![ContentItem::InputText {
                    text: user_text.to_owned(),
                }],
                phase: None,
                internal_chat_message_metadata_passthrough: None,
            },
        ],
        tools: None,
        tool_choice: "auto".to_owned(),
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
    }
}

async fn encode_and_observe(request: ResponsesApiRequest) -> Result<Vec<u8>> {
    let requests = Arc::new(Mutex::new(Vec::new()));
    let bodies = Arc::new(Mutex::new(Vec::new()));
    let dispatch = RequestDispatchMetadata::new();
    dispatch.require_final_request_observation();
    dispatch
        .install_final_request_observer(Arc::new(RecordingObserver {
            bodies: Arc::clone(&bodies),
        }))
        .map_err(|error| anyhow!(error))?;
    let provider = Provider {
        name: "openai".to_owned(),
        base_url: "https://example.com/v1".to_owned(),
        query_params: None,
        headers: HeaderMap::new(),
        retry: RetryConfig {
            max_attempts: 1,
            base_delay: Duration::from_millis(/*millis*/ 1),
            retry_429: false,
            retry_5xx: false,
            retry_transport: true,
        },
        stream_idle_timeout: Duration::from_millis(/*millis*/ 10),
    };
    let client = ResponsesClient::new(
        RecordingTransport {
            requests: Arc::clone(&requests),
        },
        provider,
        Arc::new(NoAuth),
    );
    let _stream = client
        .stream_request_single_attempt(request, ResponsesOptions::default(), dispatch.clone())
        .await?;
    assert!(dispatch.transport_invoked());
    let bodies = bodies
        .lock()
        .map_err(|_| anyhow!("body recorder poisoned"))?;
    let requests = requests
        .lock()
        .map_err(|_| anyhow!("request recorder poisoned"))?;
    assert_eq!(bodies.len(), 1);
    assert_eq!(requests.len(), 1);
    let Some(RequestBody::EncodedJson(body)) = &requests[0].body else {
        return Err(anyhow!("transport did not receive encoded JSON"));
    };
    assert_eq!(bodies[0].as_slice(), body.as_bytes());
    Ok(bodies[0].clone())
}

#[tokio::test]
async fn responses_encoder_preserves_complete_typed_context_and_observed_bytes() -> Result<()> {
    let request = request(COMPLETE_USER_TEXT);
    let expected_body = serde_json::to_value(&request)?;
    let expected_input = request.input.clone();
    let encoded = encode_and_observe(request).await?;
    let decoded: serde_json::Value = serde_json::from_slice(&encoded)?;
    assert_eq!(decoded, expected_body);
    let decoded_input: Vec<ResponseItem> = serde_json::from_value(
        decoded
            .get("input")
            .context("encoded input missing")?
            .clone(),
    )?;
    assert_eq!(decoded_input, expected_input);
    Ok(())
}

#[tokio::test]
async fn historical_string_array_is_not_typed_input_and_codec_does_not_restore_omitted_content()
-> Result<()> {
    let historical = br#"{"model":"model","input":["follow policy","snowman: \u2603"]}"#;
    let historical: serde_json::Value = serde_json::from_slice(historical)?;
    let input = historical
        .get("input")
        .context("historical input missing")?;
    assert!(serde_json::from_value::<Vec<ResponseItem>>(input.clone()).is_err());

    let shortened_user_text = "snowman: ☃";
    assert_eq!(
        COMPLETE_USER_TEXT
            .strip_prefix(shortened_user_text)
            .context("source prefix changed")?
            .as_bytes(),
        b"\ncontrol:\x01",
    );
    let shortened_request = request(shortened_user_text);
    let expected_input = shortened_request.input.clone();
    let encoded = encode_and_observe(shortened_request).await?;
    let decoded: serde_json::Value = serde_json::from_slice(&encoded)?;
    let decoded_input: Vec<ResponseItem> = serde_json::from_value(
        decoded
            .get("input")
            .context("encoded input missing")?
            .clone(),
    )?;
    assert_eq!(decoded_input, expected_input);
    assert_ne!(decoded_input, request(COMPLETE_USER_TEXT).input);
    Ok(())
}
