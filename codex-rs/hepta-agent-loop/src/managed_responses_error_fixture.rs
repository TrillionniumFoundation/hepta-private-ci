//! Controlled original lease, exact body observer and continuation test ports.
//! These fixtures do not establish production admission or issue authority.

use super::super::*;
use super::http_fixture::BODY_SECRET;
use codex_api::EncodedRequestBodyObserver;
use codex_api::EncodedRequestTerminal;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderTerminal;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_http_client::EncodedJsonBody;
use futures::future::BoxFuture;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

pub(super) struct State {
    pub policy: Mutex<Vec<ModelProviderTerminal>>,
    pub encoded: Mutex<Vec<EncodedRequestTerminal>>,
    pub bodies: AtomicUsize,
    pub continuations: AtomicUsize,
    expected_body: Digest32,
}

impl State {
    pub fn new(api: &ResponsesApiRequest) -> Arc<Self> {
        let body = EncodedJsonBody::encode(api).expect("controlled request encode");
        Arc::new(Self {
            policy: Mutex::new(Vec::new()),
            encoded: Mutex::new(Vec::new()),
            bodies: AtomicUsize::new(0),
            continuations: AtomicUsize::new(0),
            expected_body: Digest32::of_bytes(body.as_bytes()),
        })
    }
}

pub(super) struct Lease(pub Arc<State>);

impl ModelProviderAttemptLease for Lease {
    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(async move {
            self.0
                .policy
                .lock()
                .expect("policy receipt lock")
                .push(terminal);
            Ok(())
        })
    }
}

pub(super) struct Observer(pub Arc<State>);

impl fmt::Debug for Observer {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("ControlledBodyObserver")
    }
}

impl EncodedRequestBodyObserver for Observer {
    fn observe_encoded_body<'a>(
        &'a self,
        body: &'a [u8],
    ) -> BoxFuture<'a, std::result::Result<(), String>> {
        Box::pin(async move {
            if Digest32::of_bytes(body) != self.0.expected_body {
                return Err("fixture body binding mismatch".into());
            }
            self.0.bodies.fetch_add(1, Ordering::SeqCst);
            Ok(())
        })
    }

    fn observe_terminal<'a>(
        &'a self,
        terminal: EncodedRequestTerminal,
    ) -> BoxFuture<'a, std::result::Result<(), String>> {
        Box::pin(async move {
            self.0
                .encoded
                .lock()
                .expect("encoded receipt lock")
                .push(terminal);
            Ok(())
        })
    }
}

pub(super) struct Continuation(pub Arc<State>);

impl ResponsesContinuationOwner for Continuation {
    async fn retain(
        &mut self,
        _: &TurnBinding,
        _: &ModelRequest,
        _: crate::ResponsesContinuation,
    ) -> Result<Digest32> {
        self.0.continuations.fetch_add(1, Ordering::SeqCst);
        Ok(Digest32::of_bytes(b"controlled retained continuation"))
    }
}

pub(super) fn request() -> (TurnBinding, ModelRequest, ResponsesApiRequest) {
    let id = |value: &str| StableId::new(value).expect("controlled ID");
    let binding = TurnBinding {
        run_id: id("fixture-run"),
        turn_id: id("fixture-turn"),
        generation: Generation::new(1).expect("generation"),
        admission_digest: Digest32::of_bytes(b"controlled original admission"),
        deadline_unix_ms: u64::MAX,
    };
    let request = ModelRequest {
        request_id: id("fixture-request"),
        payload: "".into(),
        context_digest: Digest32::of_bytes(b""),
        input_tokens: 0,
        maximum_provider_input_tokens: 8,
        maximum_output_tokens: 8,
    };
    let api = ResponsesApiRequest {
        model: "diagnostic-fixture".into(),
        instructions: BODY_SECRET.into(),
        input: Vec::new(),
        tools: None,
        tool_choice: "none".into(),
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
    (binding, request, api)
}
