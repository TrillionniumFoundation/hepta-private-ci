//! An external host can reject first entry and retain original-response observation.
//! The rejecting wrapper is a test boundary, not a production FinalUse authority.

use std::sync::Mutex;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use codex_hepta_native_agent::Limits;
use codex_hepta_native_agent::ModelPort;
use codex_hepta_native_agent::ModelRequest;
use codex_hepta_native_agent::NativeAgent;
use codex_hepta_native_agent::ObservedModelCompletion;
use codex_hepta_native_agent::ResponsesModel;
use codex_hepta_native_agent::ResponsesStream;
use codex_hepta_native_agent::RunOutcome;
use codex_hepta_native_agent::ToolAdmission;
use codex_hepta_native_agent::ToolCall;
use codex_hepta_native_agent::ToolObservation;
use codex_hepta_native_agent::ToolPort;
use codex_hepta_native_agent::TurnBinding;
use codex_hepta_native_agent::TurnOwner;
use codex_hepta_native_agent::TurnState;
use codex_hepta_types::Generation;
use codex_hepta_types::RuntimeToolIntentV1;
use codex_hepta_types::StableId;
use codex_http_client::HttpClientFactory;
use codex_http_client::OutboundProxyPolicy;
use pretty_assertions::assert_eq;
use serde_json::json;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;

struct RejectNewModelEntry {
    transport: ResponsesModel,
    opened: Mutex<Vec<(String, Vec<u8>)>>,
    reconciled: Mutex<Vec<(String, Vec<u8>, String)>>,
}

impl ModelPort for RejectNewModelEntry {
    async fn open(&self, request: &ModelRequest) -> Result<ResponsesStream> {
        self.opened
            .lock()
            .map_err(|_| anyhow::anyhow!("opened requests lock poisoned"))?
            .push((request.operation_id.clone(), request.body.clone()));
        bail!("host rejected this local model effect entry")
    }

    async fn reconcile(
        &self,
        request: &ModelRequest,
        response_id: &str,
    ) -> Result<Option<ObservedModelCompletion>> {
        self.reconciled
            .lock()
            .map_err(|_| anyhow::anyhow!("reconciled requests lock poisoned"))?
            .push((
                request.operation_id.clone(),
                request.body.clone(),
                response_id.to_owned(),
            ));
        self.transport.reconcile(request, response_id).await
    }
}

struct RecordingOwner {
    binding: TurnBinding,
    snapshots: Mutex<Vec<TurnState>>,
}

impl TurnOwner for RecordingOwner {
    async fn verify_current(&self, binding: &TurnBinding) -> Result<()> {
        ensure!(binding == &self.binding, "unexpected owner binding");
        Ok(())
    }

    async fn checkpoint(&self, state: &TurnState) -> Result<()> {
        self.verify_current(&state.binding).await?;
        self.snapshots
            .lock()
            .map_err(|_| anyhow::anyhow!("snapshot lock poisoned"))?
            .push(state.clone());
        Ok(())
    }

    async fn admit_model(
        &self,
        binding: &TurnBinding,
        sequence: usize,
        exact_body: &[u8],
    ) -> Result<ModelRequest> {
        self.verify_current(binding).await?;
        Ok(ModelRequest {
            operation_id: format!("{}:model:{sequence}", binding.operation_id),
            body: exact_body.to_vec(),
        })
    }

    async fn admit_tool(&self, _binding: &TurnBinding, _call: &ToolCall) -> Result<ToolAdmission> {
        bail!("this test has no tool admission")
    }
}

struct NoTools;

impl ToolPort for NoTools {
    async fn execute_or_observe(
        &self,
        _intent: &RuntimeToolIntentV1,
        _arguments: &[u8],
    ) -> Result<ToolObservation> {
        bail!("this test has no tool dispatch")
    }

    async fn observe(&self, _intent: &RuntimeToolIntentV1) -> Result<ToolObservation> {
        bail!("this test has no tool observation")
    }

    async fn cancel(&self, _intent: &RuntimeToolIntentV1) -> Result<()> {
        bail!("this test has no tool cancellation")
    }
}

#[tokio::test]
async fn external_wrapper_denies_post_and_observes_an_original_response() -> Result<()> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let peer = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await?;
        let mut input = Vec::new();
        while !input.ends_with(b"\r\n\r\n") {
            ensure!(input.len() < 8192, "HTTP header budget exceeded");
            input.push(socket.read_u8().await?);
        }
        let request = String::from_utf8(input)?;
        let response = json!({
            "id": "response-original",
            "status": "completed",
            "output": [{"type":"message", "role":"assistant", "content":[
                {"type":"output_text", "text":"restored final answer"}
            ]}],
            "usage": {"input_tokens":1, "output_tokens":1}
        })
        .to_string();
        let wire = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{response}",
            response.len()
        );
        socket.write_all(wire.as_bytes()).await?;
        socket.shutdown().await?;
        Ok::<_, anyhow::Error>(request)
    });
    let port = RejectNewModelEntry {
        transport: ResponsesModel::new(
            &HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault),
            format!("http://{address}/v1/responses"),
            /*bearer*/ None,
            Duration::from_secs(2),
            /*max_stream_bytes*/ 4096,
        )?,
        opened: Mutex::new(Vec::new()),
        reconciled: Mutex::new(Vec::new()),
    };
    let binding = TurnBinding {
        thread_id: StableId::new("thread:denied")?,
        turn_id: StableId::new("turn:denied")?,
        operation_id: StableId::new("operation:denied")?,
        generation: Generation::new(1)?,
    };
    let owner = RecordingOwner {
        binding: binding.clone(),
        snapshots: Mutex::new(Vec::new()),
    };
    let mut denied = TurnState::new(binding.clone(), "new input".to_owned());
    let agent = NativeAgent {
        model_name: "fixture-model".to_owned(),
        instructions: "Use the original request".to_owned(),
        tools: Vec::new(),
        store_responses: true,
        limits: Limits {
            context_bytes: 4096,
            output_tokens: 128,
            model_calls: 2,
            tool_calls: 1,
            tool_output_bytes: 4096,
            model_timeout: Duration::from_secs(3),
            tool_timeout: Duration::from_secs(3),
            observation_interval: Duration::from_millis(1),
        },
    };
    let exact_body = serde_json::to_vec(&json!({
        "model":"fixture-model", "instructions":"Use the original request",
        "input":[{"role":"user", "content":"new input"}], "tools":[],
        "tool_choice":"auto", "parallel_tool_calls":false,
        "max_output_tokens":128, "store":true, "stream":true
    }))?;
    assert_eq!(
        agent
            .run(
                &owner,
                &NoTools,
                &port,
                &mut denied,
                &CancellationToken::new()
            )
            .await?,
        RunOutcome::PendingModel
    );
    let expected_request = ("operation:denied:model:0".to_owned(), exact_body.clone());
    let pending = denied.pending_model.as_ref().context("pending admission")?;
    assert_eq!(
        (pending.operation_id.clone(), pending.body.clone()),
        expected_request
    );
    assert_eq!(denied.binding, binding);
    assert_eq!(denied.provider_response_id, None);
    assert_eq!(denied.model_calls, 1);
    assert_eq!(denied.final_answer, None);
    assert_eq!(
        port.opened.lock().expect("opened requests lock").as_slice(),
        std::slice::from_ref(&expected_request)
    );
    {
        let snapshots = owner.snapshots.lock().expect("snapshot lock");
        let stored = snapshots.last().context("saved pending checkpoint")?;
        let stored_request = stored.pending_model.as_ref().context("saved admission")?;
        assert_eq!(
            (
                stored_request.operation_id.clone(),
                stored_request.body.clone()
            ),
            expected_request
        );
    }
    // Re-running the denied operation must not retry its POST or re-enter the port.
    assert_eq!(
        agent
            .run(
                &owner,
                &NoTools,
                &port,
                &mut denied,
                &CancellationToken::new()
            )
            .await?,
        RunOutcome::PendingModel
    );
    assert_eq!(port.opened.lock().expect("opened requests lock").len(), 1);

    // A separate restored fixture has a response ID observed before this run.
    // Do not invent a response ID for the entry which the host just rejected.
    let restored_binding = TurnBinding {
        thread_id: StableId::new("thread:restored")?,
        turn_id: StableId::new("turn:restored")?,
        operation_id: StableId::new("operation:restored")?,
        generation: Generation::new(1)?,
    };
    let restored_owner = RecordingOwner {
        binding: restored_binding.clone(),
        snapshots: Mutex::new(Vec::new()),
    };
    let mut restored = TurnState::new(restored_binding, "new input".to_owned());
    restored.model_calls = 1;
    restored.pending_model = Some(ModelRequest {
        operation_id: "operation:restored:model:0".to_owned(),
        body: exact_body.clone(),
    });
    restored.provider_response_id = Some("response-original".to_owned());
    assert_eq!(
        agent
            .run(
                &restored_owner,
                &NoTools,
                &port,
                &mut restored,
                &CancellationToken::new(),
            )
            .await?,
        RunOutcome::Completed("restored final answer".to_owned())
    );
    assert_eq!(
        port.reconciled
            .lock()
            .expect("reconciled requests lock")
            .as_slice(),
        &[(
            "operation:restored:model:0".to_owned(),
            exact_body,
            "response-original".to_owned()
        )]
    );
    assert_eq!(port.opened.lock().expect("opened requests lock").len(), 1);
    assert_eq!(restored.model_calls, 1);
    assert!(restored.pending_model.is_none());
    let observed_http = tokio::time::timeout(Duration::from_secs(3), peer).await???;
    assert_eq!(
        observed_http.lines().next(),
        Some("GET /v1/responses/response-original HTTP/1.1")
    );
    // The only connection to the actual peer was the original-response GET.
    // There was no POST, and parsing used the transport's sealed completion.
    Ok(())
}
