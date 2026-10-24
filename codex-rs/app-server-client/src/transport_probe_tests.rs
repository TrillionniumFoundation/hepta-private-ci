#![allow(
    clippy::expect_used,
    reason = "isolated transport qualification fixtures fail loudly"
)]

//! Opt-in incremental transport probe, never a production compatibility gate.
//!
//! Both routes use one real MessageProcessor in this process. The socket route
//! adds a bounded UDS/WebSocket bridge above the same in-process owner. This
//! measures that additional framing, serialization, socket and queue work; it
//! is not a full Agentd benchmark or proof of Hepta startup-binding parity.

use super::*;
use codex_app_server_protocol::JSONRPCError;
use codex_app_server_protocol::JSONRPCMessage;
use codex_app_server_protocol::JSONRPCResponse;
use codex_app_server_protocol::ThreadSettingsUpdateParams;
use codex_app_server_protocol::ThreadSettingsUpdateResponse;
use codex_app_server_protocol::ThreadSettingsUpdatedNotification;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_core::config::ConfigBuilder;
use codex_core::init_state_db;
use codex_protocol::config_types::Personality;
use codex_uds::UnixListener;
use futures::SinkExt;
use futures::StreamExt;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Instant;
use tempfile::TempDir;
use tokio_tungstenite::accept_async;
use tokio_tungstenite::tungstenite::Message;

const CAPACITY: usize = 8;
const WARMUP_PAIRS: usize = 32;
const SAMPLE_PAIRS: usize = 256;
const OPERATION_TIMEOUT: Duration = Duration::from_secs(5);

async fn start_owner(home: &std::path::Path) -> InProcessAppServerClient {
    let config = Arc::new(
        ConfigBuilder::default()
            .codex_home(home.to_path_buf())
            .build()
            .await
            .expect("isolated probe config"),
    );
    let state_db = init_state_db(config.as_ref())
        .await
        .expect("isolated state database");
    InProcessAppServerClient::start(InProcessClientStartArgs {
        arg0_paths: Arg0DispatchPaths::default(),
        config,
        cli_overrides: Vec::new(),
        loader_overrides: LoaderOverrides::default(),
        strict_config: false,
        cloud_config_bundle: CloudConfigBundleLoader::default(),
        feedback: CodexFeedback::new(),
        log_db: None,
        state_db: Some(state_db),
        environment_manager: Arc::new(EnvironmentManager::default_for_tests()),
        config_warnings: Vec::new(),
        session_source: SessionSource::Exec,
        enable_codex_api_key_env: false,
        client_name: "same-owner-transport-probe".to_string(),
        client_version: "0.0.0-probe".to_string(),
        experimental_api: true,
        mcp_server_openai_form_elicitation: false,
        opt_out_notification_methods: Vec::new(),
        channel_capacity: CAPACITY,
    })
    .await
    .expect("real in-process owner")
}

async fn start_thread(
    handle: &InProcessAppServerRequestHandle,
    id: i64,
    workspace: &std::path::Path,
) -> String {
    let thread: ThreadStartResponse = handle
        .request_typed(ClientRequest::ThreadStart {
            request_id: RequestId::Integer(id),
            params: ThreadStartParams {
                cwd: Some(workspace.to_string_lossy().into_owned()),
                ephemeral: Some(true),
                personality: Some(Personality::None),
                ..Default::default()
            },
        })
        .await
        .expect("probe thread");
    thread.thread.id
}

/// Only the setup handshake is synthetic: the owner is already initialized.
/// Every measured request and notification passes through the real processor.
async fn bridge(
    mut owner: InProcessAppServerClient,
    mut listener: UnixListener,
    socket_route: Arc<AtomicBool>,
    direct_events: mpsc::Sender<InProcessServerEvent>,
    home: String,
) {
    let stream = listener.accept().await.expect("probe socket accept");
    let mut socket = accept_async(stream).await.expect("probe websocket upgrade");
    let frame = socket
        .next()
        .await
        .expect("initialize frame")
        .expect("initialize");
    let Message::Text(frame) = frame else {
        panic!("initialize was not text");
    };
    let JSONRPCMessage::Request(initialize) =
        serde_json::from_str(&frame).expect("initialize JSON")
    else {
        panic!("initialize was not a request");
    };
    assert_eq!(initialize.method, "initialize");
    let result = JSONRPCMessage::Response(JSONRPCResponse {
        id: initialize.id,
        result: serde_json::json!({
            "userAgent": "codex_cli_rs/0.0.0-probe (transport bridge)",
            "codexHome": home,
        }),
    });
    socket
        .send(Message::Text(
            serde_json::to_string(&result)
                .expect("initialize result")
                .into(),
        ))
        .await
        .expect("initialize send");
    let handle = owner.request_handle();
    loop {
        tokio::select! {
            event = owner.next_event() => {
                let event = event.expect("owner event stream");
                if socket_route.load(Ordering::Acquire) {
                    let InProcessServerEvent::ServerNotification(notification) = event else {
                        panic!("probe must not lose events or request approvals: {event:?}");
                    };
                    socket.send(Message::Text(
                        serde_json::to_string(&notification).expect("notification JSON").into()
                    )).await.expect("notification send");
                } else {
                    direct_events.send(event).await.expect("direct event consumer");
                }
            }
            frame = socket.next() => {
                let Some(frame) = frame else { break; };
                match frame.expect("socket receive") {
                    Message::Text(text) => {
                        match serde_json::from_str::<JSONRPCMessage>(&text).expect("request JSON") {
                            JSONRPCMessage::Request(request) => {
                                let id = request.id.clone();
                                let request = ClientRequest::try_from(request).expect("typed request");
                                let response = match handle.request(request).await.expect("owner request") {
                                    Ok(result) => JSONRPCMessage::Response(JSONRPCResponse { id, result }),
                                    Err(error) => JSONRPCMessage::Error(JSONRPCError { id, error }),
                                };
                                socket.send(Message::Text(
                                    serde_json::to_string(&response).expect("response JSON").into()
                                )).await.expect("response send");
                            }
                            JSONRPCMessage::Notification(notification) => {
                                assert_eq!(notification.method, "initialized");
                            }
                            _ => panic!("unexpected client message"),
                        }
                    }
                    Message::Close(_) => break,
                    Message::Ping(payload) => {
                        socket.send(Message::Pong(payload)).await.expect("pong send");
                    }
                    _ => {}
                }
            }
        }
    }
    owner.shutdown().await.expect("owner shutdown");
}

fn settings(event: AppServerEvent, thread: &str) -> Option<ThreadSettingsUpdatedNotification> {
    match event {
        AppServerEvent::ServerNotification(notification) => {
            if let ServerNotification::ThreadSettingsUpdated(notification) = *notification
                && notification.thread_id == thread
            {
                return Some(notification);
            }
            None
        }
        event => panic!("probe must not lose events or request approvals: {event:?}"),
    }
}

fn percentile(values: &[i128], numerator: usize) -> i128 {
    values[((values.len() - 1) * numerator) / 100]
}

fn summarize(mut values: Vec<i128>) -> serde_json::Value {
    values.sort_unstable();
    serde_json::json!({
        "count": values.len(),
        "min_ns": values[0],
        "p50_ns": percentile(&values, 50),
        "p95_ns": percentile(&values, 95),
        "max_ns": values[values.len() - 1],
    })
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "opt-in latency probe; no timing pass/fail threshold"]
async fn same_owner_typed_and_uds_transport_probe() {
    let home = TempDir::new().expect("probe home");
    let socket_dir = TempDir::new().expect("short socket path");
    let setup_started = Instant::now();
    let owner = start_owner(home.path()).await;
    let direct = owner.request_handle();
    let direct_thread = start_thread(&direct, 1, home.path()).await;
    let remote_thread = start_thread(&direct, 2, home.path()).await;
    let socket_path = AbsolutePathBuf::from_absolute_path(socket_dir.path().join("probe.sock"))
        .expect("absolute socket path");
    let listener = UnixListener::bind(socket_path.as_path())
        .await
        .expect("socket bind");
    let socket_route = Arc::new(AtomicBool::new(false));
    let (direct_tx, mut direct_rx) = mpsc::channel(CAPACITY);
    let server = tokio::spawn(bridge(
        owner,
        listener,
        socket_route.clone(),
        direct_tx,
        home.path().to_string_lossy().into_owned(),
    ));
    let mut remote = RemoteAppServerClient::connect_with_bounded_events(
        RemoteAppServerConnectArgs {
            endpoint: RemoteAppServerEndpoint::UnixSocket { socket_path },
            client_name: "same-owner-transport-probe".to_string(),
            client_version: "0.0.0-probe".to_string(),
            experimental_api: true,
            mcp_server_openai_form_elicitation: false,
            opt_out_notification_methods: Vec::new(),
            channel_capacity: CAPACITY,
        },
        CAPACITY,
    )
    .await
    .expect("remote probe client");
    let setup_ns = setup_started.elapsed().as_nanos();
    let mut direct_ns = Vec::new();
    let mut remote_ns = Vec::new();
    let mut paired_delta_ns = Vec::new();
    let mut request_bytes = 0;
    let mut event_bytes = 0;
    for pair in 0..(WARMUP_PAIRS + SAMPLE_PAIRS) {
        let personality = if pair % 2 == 0 {
            Personality::Friendly
        } else {
            Personality::Pragmatic
        };
        let mut durations = [0_i128; 2];
        let mut observed_settings = [None, None];
        // Alternate pair order to reduce warmup, scheduler and temporal bias.
        let order = if pair % 2 == 0 {
            [false, true]
        } else {
            [true, false]
        };
        for use_socket in order {
            socket_route.store(use_socket, Ordering::Release);
            let thread = if use_socket {
                &remote_thread
            } else {
                &direct_thread
            };
            let request = ClientRequest::ThreadSettingsUpdate {
                request_id: RequestId::Integer(100 + (pair * 2 + usize::from(use_socket)) as i64),
                params: ThreadSettingsUpdateParams {
                    thread_id: thread.clone(),
                    personality: Some(personality),
                    ..Default::default()
                },
            };
            request_bytes = serde_json::to_vec(&request).expect("request size").len();
            let started = Instant::now();
            let notification = timeout(OPERATION_TIMEOUT, async {
                let _: ThreadSettingsUpdateResponse = if use_socket {
                    remote.request_typed(request).await
                } else {
                    direct.request_typed(request).await
                }
                .expect("settings response");
                loop {
                    let event = if use_socket {
                        remote.next_event().await.expect("remote event")
                    } else {
                        direct_rx.recv().await.expect("direct event").into()
                    };
                    if let Some(notification) = settings(event, thread) {
                        break notification;
                    }
                }
            })
            .await
            .expect("request and matching event deadline");
            durations[usize::from(use_socket)] = started.elapsed().as_nanos() as i128;
            assert_eq!(notification.thread_settings.personality, Some(personality));
            event_bytes = serde_json::to_vec(&notification).expect("event size").len();
            observed_settings[usize::from(use_socket)] =
                Some(serde_json::to_value(&notification.thread_settings).expect("settings value"));
        }
        assert_eq!(observed_settings[0], observed_settings[1]);
        if pair >= WARMUP_PAIRS {
            direct_ns.push(durations[0]);
            remote_ns.push(durations[1]);
            paired_delta_ns.push(durations[1] - durations[0]);
        }
    }
    println!(
        "HEPTA_TRANSPORT_PROBE {}",
        serde_json::json!({
            "schema_version": 1,
            "scope": "same-process UDS bridge added above one real in-process MessageProcessor",
            "debug_assertions": cfg!(debug_assertions),
            "os": std::env::consts::OS,
            "arch": std::env::consts::ARCH,
            "model_turns_requested": 0,
            "setup_ns": setup_ns,
            "warmup_pairs": WARMUP_PAIRS,
            "sample_pairs": SAMPLE_PAIRS,
            "explicit_queue_capacity": CAPACITY,
            "max_requests_outstanding": 1,
            "internal_facade_event_queue": "upstream unbounded; one outstanding request bounds probe backlog only",
            "request": "thread/settings/update",
            "event": "thread/settings/updated",
            "request_json_bytes_last": request_bytes,
            "event_params_json_bytes_last": event_bytes,
            "direct_request_and_event": summarize(direct_ns),
            "uds_bridge_request_and_event": summarize(remote_ns),
            "paired_uds_minus_direct": summarize(paired_delta_ns),
            "excludes": ["model latency", "token usage", "Agentd owner bindings", "overload and memory qualification", "large streaming payloads"],
        })
    );
    remote.shutdown().await.expect("remote shutdown");
    timeout(Duration::from_secs(50), server)
        .await
        .expect("bridge shutdown deadline")
        .expect("bridge task");
}
