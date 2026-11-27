#[path = "../../src/proto/codex.exec_server.relay.v1.rs"]
mod relay_proto;

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use anyhow::Context;
use anyhow::Result;
use codex_api::AuthProvider;
use codex_exec_server::ExecServerClient;
use codex_exec_server::NoiseChannelIdentity;
use codex_exec_server::NoiseChannelPublicKey;
use codex_exec_server::NoiseRendezvousConnectArgs;
use codex_exec_server::NoiseRendezvousConnectBundle;
use codex_exec_server::RemoteEnvironmentConfig;
use codex_http_client::HttpClientFactory;
use codex_http_client::OutboundProxyPolicy;
use futures::SinkExt;
use futures::StreamExt;
use http::HeaderMap;
use http::HeaderValue;
use prost::Message as ProstMessage;
use relay_proto::RelayMessageFrame;
use relay_proto::relay_message_frame;
use tokio::net::TcpListener;
use tokio::net::TcpStream;
use tokio::time::timeout;
use tokio_tungstenite::WebSocketStream;
use tokio_tungstenite::accept_async;
use tokio_tungstenite::tungstenite::Message;
use tokio_util::task::AbortOnDropHandle;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::header;
use wiremock::matchers::method;
use wiremock::matchers::path;

pub(crate) const ENVIRONMENT_ID: &str = "env-noise-relay-test";
pub(crate) const EXECUTOR_REGISTRATION_ID: &str = "registration-1";
pub(crate) const HARNESS_KEY_AUTHORIZATION: &str = "harness-key-authorization";
pub(crate) const REGISTRY_TOKEN: &str = "registry-token";
pub(crate) const TEST_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Debug)]
struct StaticRegistryAuthProvider;

impl AuthProvider for StaticRegistryAuthProvider {
    fn add_auth_headers(&self, headers: &mut HeaderMap) {
        let _ = headers.insert(
            http::header::AUTHORIZATION,
            HeaderValue::from_static("Bearer registry-token"),
        );
    }
}

pub(crate) fn static_registry_auth_provider() -> codex_api::SharedAuthProvider {
    Arc::new(StaticRegistryAuthProvider)
}

pub(crate) struct RelayTest {
    registry: MockServer,
    listener: TcpListener,
}

// One relay task writes these fixed scalars. Debug reads are intentionally
// non-atomic observations; a completed send is not a peer acknowledgement.
pub(crate) struct RelayProgress {
    started: Instant,
    environment_received: AtomicU64,
    environment_forwarded: AtomicU64,
    harness_received: AtomicU64,
    harness_forwarded: AtomicU64,
    forward_wait: AtomicU8,
    last_forward_ms: AtomicU64,
    has_forwarded: AtomicBool,
}

impl Default for RelayProgress {
    fn default() -> Self {
        Self {
            started: Instant::now(),
            environment_received: AtomicU64::default(),
            environment_forwarded: AtomicU64::default(),
            harness_received: AtomicU64::default(),
            harness_forwarded: AtomicU64::default(),
            forward_wait: AtomicU8::default(),
            last_forward_ms: AtomicU64::default(),
            has_forwarded: AtomicBool::default(),
        }
    }
}

#[derive(Clone, Copy)]
#[repr(u8)]
enum RelayDirection {
    EnvironmentToHarness = 1,
    HarnessToEnvironment = 2,
}

struct RelayForwardWait<'a>(&'a AtomicU8);

impl Drop for RelayForwardWait<'_> {
    fn drop(&mut self) {
        self.0.store(/*val*/ 0, Ordering::Relaxed);
    }
}

impl RelayProgress {
    fn received(&self, direction: RelayDirection) {
        let counter = match direction {
            RelayDirection::EnvironmentToHarness => &self.environment_received,
            RelayDirection::HarnessToEnvironment => &self.harness_received,
        };
        let _ = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |count| {
            Some(count.saturating_add(/*rhs*/ 1))
        });
    }

    fn forwarding(&self, direction: RelayDirection) -> RelayForwardWait<'_> {
        self.forward_wait.store(direction as u8, Ordering::Relaxed);
        RelayForwardWait(&self.forward_wait)
    }

    fn forwarded(&self, direction: RelayDirection) {
        let counter = match direction {
            RelayDirection::EnvironmentToHarness => &self.environment_forwarded,
            RelayDirection::HarnessToEnvironment => &self.harness_forwarded,
        };
        let _ = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |count| {
            Some(count.saturating_add(/*rhs*/ 1))
        });
        self.last_forward_ms
            .store(self.elapsed_ms(), Ordering::Relaxed);
        self.has_forwarded.store(/*val*/ true, Ordering::Release);
    }

    fn elapsed_ms(&self) -> u64 {
        u64::try_from(self.started.elapsed().as_millis()).unwrap_or(u64::MAX)
    }
}

impl std::fmt::Debug for RelayProgress {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let forward_wait = match self.forward_wait.load(Ordering::Relaxed) {
            0 => "none",
            1 => "environment_to_harness",
            2 => "harness_to_environment",
            _ => "unknown",
        };
        let last_forward_age_ms = self.has_forwarded.load(Ordering::Acquire).then(|| {
            self.elapsed_ms()
                .saturating_sub(self.last_forward_ms.load(Ordering::Relaxed))
        });
        f.debug_struct("RelayProgress")
            .field(
                "environment_received",
                &self.environment_received.load(Ordering::Relaxed),
            )
            .field(
                "environment_forwarded",
                &self.environment_forwarded.load(Ordering::Relaxed),
            )
            .field(
                "harness_received",
                &self.harness_received.load(Ordering::Relaxed),
            )
            .field(
                "harness_forwarded",
                &self.harness_forwarded.load(Ordering::Relaxed),
            )
            .field("forward_wait", &forward_wait)
            .field("last_forward_age_ms", &last_forward_age_ms)
            .finish()
    }
}

pub(crate) struct RelayConnection {
    pub(crate) client: ExecServerClient,
    captured_frames: Arc<Mutex<Vec<Vec<u8>>>>,
    progress: Arc<RelayProgress>,
    relay_task: AbortOnDropHandle<Result<()>>,
}

impl std::fmt::Debug for RelayConnection {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        const MAX_SAMPLED_FRAMES: usize = 64;

        let mut state = f.debug_struct("RelayConnection");
        state.field(
            "relay_task_finished",
            &self.relay_task.abort_handle().is_finished(),
        );
        state.field("progress", &self.progress);
        match self.captured_frames.try_lock() {
            Ok(frames) => {
                let sampled_tail_frames = frames.len().min(MAX_SAMPLED_FRAMES);
                let sampled_tail_bytes = frames
                    .iter()
                    .rev()
                    .take(MAX_SAMPLED_FRAMES)
                    .map(Vec::len)
                    .fold(/*init*/ 0usize, usize::saturating_add);
                state
                    .field("capture", &"ready")
                    .field("captured_frames", &frames.len())
                    .field("sampled_tail_frames", &sampled_tail_frames)
                    .field("sampled_tail_bytes", &sampled_tail_bytes);
            }
            Err(std::sync::TryLockError::WouldBlock) => {
                state.field("capture", &"busy");
            }
            Err(std::sync::TryLockError::Poisoned(_)) => {
                state.field("capture", &"poisoned");
            }
        }
        state.finish_non_exhaustive()
    }
}

impl RelayTest {
    pub(crate) async fn new() -> Result<Self> {
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let rendezvous_url = format!("ws://{}", listener.local_addr()?);
        let registry = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path(format!(
                "/cloud/environment/{ENVIRONMENT_ID}/register"
            )))
            .and(header("authorization", format!("Bearer {REGISTRY_TOKEN}")))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "environment_id": ENVIRONMENT_ID,
                "url": format!("{rendezvous_url}/relay?role=environment"),
                "security_profile": "noise_hybrid_ik_v1",
                "executor_registration_id": EXECUTOR_REGISTRATION_ID,
            })))
            .mount(&registry)
            .await;
        Mock::given(method("POST"))
            .and(path(format!(
                "/cloud/environment/{ENVIRONMENT_ID}/validate"
            )))
            .and(header("authorization", format!("Bearer {REGISTRY_TOKEN}")))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "valid": true,
            })))
            .mount(&registry)
            .await;
        Ok(Self { registry, listener })
    }

    pub(crate) fn config(&self) -> Result<RemoteEnvironmentConfig> {
        Ok(RemoteEnvironmentConfig::new(
            self.registry.uri(),
            ENVIRONMENT_ID.to_string(),
            static_registry_auth_provider(),
            HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault),
        )?)
    }

    pub(crate) async fn connect(&self) -> Result<RelayConnection> {
        let rendezvous_url = format!("ws://{}", self.listener.local_addr()?);
        let environment_websocket = accept_websocket(&self.listener, "environment").await?;
        let executor_public_key = registered_executor_public_key(&self.registry).await?;
        let harness_identity = NoiseChannelIdentity::generate()?;
        let client_args = NoiseRendezvousConnectArgs {
            bundle: NoiseRendezvousConnectBundle {
                websocket_url: format!("{rendezvous_url}/relay?role=harness"),
                environment_id: ENVIRONMENT_ID.to_string(),
                executor_registration_id: EXECUTOR_REGISTRATION_ID.to_string(),
                executor_public_key,
                harness_key_authorization: HARNESS_KEY_AUTHORIZATION.to_string(),
            },
            harness_identity,
            client_name: "noise-relay-test".to_string(),
            connect_timeout: TEST_TIMEOUT,
            initialize_timeout: TEST_TIMEOUT,
            resume_session_id: None,
            http_client_factory: HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault),
        };
        let client_task =
            tokio::spawn(
                async move { ExecServerClient::connect_noise_rendezvous(client_args).await },
            );
        let harness_websocket = accept_websocket(&self.listener, "harness").await?;
        let captured_frames = Arc::new(Mutex::new(Vec::new()));
        let progress = Arc::new(RelayProgress::default());
        let relay_task = AbortOnDropHandle::new(tokio::spawn(proxy_relay_frames(
            environment_websocket,
            harness_websocket,
            Arc::clone(&captured_frames),
            Arc::clone(&progress),
        )));
        let client = timeout(TEST_TIMEOUT, client_task)
            .await
            .context("Noise harness client should connect")???;
        Ok(RelayConnection {
            client,
            captured_frames,
            progress,
            relay_task,
        })
    }
}

impl RelayConnection {
    pub(crate) fn assert_encrypted(&self) -> Result<()> {
        assert_relay_data_is_encrypted(&self.captured_frames)
    }

    pub(crate) async fn close(self) {
        drop(self.client);
        self.relay_task.abort();
        let _ = self.relay_task.await;
    }
}

pub(crate) async fn accept_websocket(
    listener: &TcpListener,
    role: &str,
) -> Result<WebSocketStream<TcpStream>> {
    let (socket, _peer_addr) = timeout(TEST_TIMEOUT, listener.accept())
        .await
        .with_context(|| format!("remote {role} should connect to fake rendezvous"))??;
    // Match the production connectors: do not delay an individual relay record
    // while waiting for more data to fill a TCP segment.
    socket
        .set_nodelay(/*nodelay*/ true)
        .context("fake rendezvous should configure TCP_NODELAY")?;
    timeout(TEST_TIMEOUT, accept_async(socket))
        .await
        .with_context(|| format!("fake rendezvous should accept {role} websocket"))?
        .map_err(Into::into)
}

pub(crate) async fn registered_executor_public_key(
    registry: &MockServer,
) -> Result<NoiseChannelPublicKey> {
    let requests = registry
        .received_requests()
        .await
        .context("wiremock should retain requests")?;
    let request = requests
        .iter()
        .find(|request| request.url.path().ends_with("/register"))
        .context("exec-server should register before connecting")?;
    let body: serde_json::Value = serde_json::from_slice(&request.body)?;
    let key = serde_json::from_value(body["executor_public_key"].clone())?;
    Ok(key)
}

pub(crate) async fn proxy_relay_frames(
    mut environment: WebSocketStream<TcpStream>,
    mut harness: WebSocketStream<TcpStream>,
    captured_frames: Arc<Mutex<Vec<Vec<u8>>>>,
    progress: Arc<RelayProgress>,
) -> Result<()> {
    loop {
        tokio::select! {
            message = environment.next() => {
                let Some(message) = message else {
                    break;
                };
                let message = message?;
                let direction = RelayDirection::EnvironmentToHarness;
                progress.received(direction);
                capture_binary_frame(&captured_frames, &message);
                let forwarding = progress.forwarding(direction);
                harness.send(message).await?;
                progress.forwarded(direction);
                drop(forwarding);
            }
            message = harness.next() => {
                let Some(message) = message else {
                    break;
                };
                let message = message?;
                let direction = RelayDirection::HarnessToEnvironment;
                progress.received(direction);
                capture_binary_frame(&captured_frames, &message);
                let forwarding = progress.forwarding(direction);
                environment.send(message).await?;
                progress.forwarded(direction);
                drop(forwarding);
            }
        }
    }
    Ok(())
}

fn capture_binary_frame(captured_frames: &Mutex<Vec<Vec<u8>>>, message: &Message) {
    if let Message::Binary(bytes) = message {
        captured_frames
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .push(bytes.to_vec());
    }
}

pub(crate) fn assert_relay_data_is_encrypted(captured_frames: &Mutex<Vec<Vec<u8>>>) -> Result<()> {
    let captured_frames = captured_frames
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let mut data_frames = 0;
    for encoded in captured_frames.iter() {
        let frame = RelayMessageFrame::decode(encoded.as_slice())?;
        let Some(relay_message_frame::Body::Data(data)) = frame.body else {
            continue;
        };
        data_frames += 1;
        let payload = String::from_utf8_lossy(&data.payload);
        assert!(!payload.contains("initialize"));
        assert!(!payload.contains("process/start"));
        assert!(!payload.contains("noise-relay-test"));
    }
    assert!(
        data_frames >= 4,
        "expected encrypted request and response frames"
    );
    Ok(())
}
