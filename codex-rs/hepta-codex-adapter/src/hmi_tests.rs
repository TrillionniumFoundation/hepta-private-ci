use super::*;
use futures::SinkExt;
use futures::StreamExt;
use serde_json::Value;
use serde_json::json;
use tokio::net::TcpListener;
use tokio::net::TcpStream;
use tokio_tungstenite::WebSocketStream;
use tokio_tungstenite::accept_async;
use tokio_tungstenite::tungstenite::Message;
type Socket = WebSocketStream<TcpStream>;

fn binding() -> HmiBindingV1 {
    HmiBindingV1 {
        principal_id: "user:test".into(),
        device_id: "device:test".into(),
        device_generation: 2,
        organ_id: "hmi:test".into(),
        logical_session_id: "logical:test".into(),
        organ_generation: 7,
        thread_id: "thread:test".into(),
        app_server_session_id: "session:test".into(),
        codex_home: "/server/.codex".into(),
        app_server_version: "9.8.7-test".into(),
    }
}
fn args(url: &str) -> RemoteAppServerConnectArgs {
    RemoteAppServerConnectArgs {
        endpoint: codex_app_server_client::RemoteAppServerEndpoint::WebSocket {
            websocket_url: url.into(),
            auth_token: None,
        },
        client_name: "hepta-hmi-test".into(),
        client_version: "test".into(),
        experimental_api: true,
        mcp_server_openai_form_elicitation: false,
        opt_out_notification_methods: Vec::new(),
        channel_capacity: 8,
    }
}
async fn read(socket: &mut Socket) -> Value {
    loop {
        match socket
            .next()
            .await
            .expect("socket message")
            .expect("valid websocket")
        {
            Message::Text(text) => return serde_json::from_str(text.as_str()).expect("JSON RPC"),
            Message::Ping(bytes) => socket.send(Message::Pong(bytes)).await.expect("pong"),
            other => panic!("unexpected message {other:?}"),
        }
    }
}
async fn send(socket: &mut Socket, value: Value) {
    socket
        .send(Message::Text(value.to_string().into()))
        .await
        .expect("send JSON RPC");
}
async fn reply(socket: &mut Socket, request: &Value, result: Value) {
    send(
        socket,
        json!({"jsonrpc":"2.0", "id":request["id"], "result":result}),
    )
    .await;
}
async fn notification(socket: &mut Socket, method: &str, params: Value) {
    send(
        socket,
        json!({"jsonrpc":"2.0", "method":method, "params":params}),
    )
    .await;
}
async fn initialize(socket: &mut Socket) {
    let request = read(socket).await;
    assert_eq!(request["method"], "initialize");
    reply(
        socket,
        &request,
        json!({"userAgent":"codex_cli_rs/9.8.7-test (test)","codexHome":"/server/.codex"}),
    )
    .await;
    assert_eq!(read(socket).await["method"], "initialized");
    let resume = read(socket).await;
    assert_eq!(resume["method"], "thread/resume");
    assert_eq!(resume["params"]["threadId"], "thread:test");
    assert_eq!(resume["params"]["excludeTurns"], true);
    reply(
        socket,
        &resume,
        json!({"thread":{
        "id":"thread:test","sessionId":"session:test","preview":"","ephemeral":false,
        "modelProvider":"fixture","createdAt":1,"updatedAt":2,"status":{"type":"idle"},
        "cwd":"/tmp","cliVersion":"test","source":"appServer","turns":[]},
        "model":"fixture","modelProvider":"fixture","cwd":"/tmp","approvalPolicy":"never",
        "approvalsReviewer":"user","sandbox":{"type":"readOnly","networkAccess":false},
        "reasoningEffort":null}),
    )
    .await;
}
fn admission(request: &Value, persisted: bool) -> Value {
    let params = &request["params"];
    json!({"clientUserMessageId": params["clientUserMessageId"], "payloadSha256":params["expectedPayloadSha256"],
        "outcome":if persisted {json!({"type":"persisted","turnId":"turn:test"})}
        else {json!({"type":"queued","created":true,"queuedSubmission":{"id":"queue:test",
            "input":params["input"],"clientUserMessageId":params["clientUserMessageId"]}})}})
}
async fn started(socket: &mut Socket, request: &Value) {
    notification(
        socket,
        "item/started",
        json!({"threadId":"thread:test","turnId":"turn:test","startedAtMs":1,
        "item":{"type":"userMessage","id":"user:test","content":request["params"]["input"],
            "clientId":request["params"]["clientUserMessageId"]}}),
    )
    .await;
}
async fn delta(socket: &mut Socket, thread: &str, text: &str) {
    notification(
        socket,
        "item/agentMessage/delta",
        json!({"threadId":thread,"turnId":"turn:test","itemId":"answer:test","delta":text}),
    )
    .await;
}
async fn completed(socket: &mut Socket, status: &str) {
    notification(socket,"turn/completed",json!({"threadId":"thread:test","turn":{
        "id":"turn:test","items":[],"status":status,
        "error":if status == "failed" {json!({"message":"fixture provider failed","additionalDetails":null,"codexErrorInfo":null})}else{Value::Null}
    }})).await;
}
async fn listener() -> (TcpListener, String) {
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("loopback listener");
    let url = format!("ws://{}", listener.local_addr().expect("address"));
    (listener, url)
}

#[tokio::test]
async fn real_socket_stream_preserves_failure_and_reconciles_same_request() {
    let (listener, url) = listener().await;
    let peer = tokio::spawn(async move {
        let mut socket = accept_async(listener.accept().await.unwrap().0)
            .await
            .unwrap();
        initialize(&mut socket).await;
        let first = read(&mut socket).await;
        assert_eq!(first["method"], "thread/queue/reconcile");
        reply(&mut socket, &first, admission(&first, false)).await;
        started(&mut socket, &first).await;
        delta(&mut socket, "other-thread", "must not leak").await;
        delta(&mut socket, "thread:test", "你好").await;
        completed(&mut socket, "failed").await;
        let replay = read(&mut socket).await;
        assert_eq!(replay["params"]["mode"], "reconcileOnly");
        assert_eq!(
            replay["params"]["clientUserMessageId"],
            first["params"]["clientUserMessageId"]
        );
        reply(&mut socket, &replay, admission(&replay, true)).await;
        let _ = socket.close(None).await;
    });
    let mut connection =
        HmiConnectionV1::connect(args(&url), binding(), 16, Duration::from_secs(3))
            .await
            .unwrap();
    connection
        .requests
        .submit_text(
            7,
            1,
            "utterance:one",
            "用户输入",
            ThreadQueueReconcileMode::AllowIfAbsent,
        )
        .await
        .unwrap();
    assert!(matches!(
        connection.events.next().await.unwrap().unwrap().kind,
        HmiEventKindV1::TurnStarted
    ));
    let delta = connection.events.next().await.unwrap().unwrap();
    assert_eq!(
        delta.kind,
        HmiEventKindV1::TextDelta {
            item_id: "answer:test".into(),
            delta: "你好".into()
        }
    );
    assert!(connection.requests.permits_output(&delta.scope).unwrap());
    let scope = serde_json::to_value(&delta.scope).unwrap();
    assert_eq!(scope["deviceGeneration"], 2);
    assert_eq!(scope["organId"], "hmi:test");
    assert_eq!(scope["utteranceSequence"], 1);
    assert!(scope["connectionId"].is_u64());
    assert_eq!(
        scope["utteranceId"],
        connection
            .requests
            .client_message_id("utterance:one")
            .unwrap()
    );
    let terminal = connection.events.next().await.unwrap().unwrap();
    assert_eq!(
        terminal.kind,
        HmiEventKindV1::Terminal {
            outcome: HmiTerminalV1 {
                status: HmiTerminalStatusV1::Failed,
                generated_text: "你好".into(),
                error: Some("fixture provider failed".into())
            }
        }
    );
    assert_eq!(
        connection.requests.terminal_snapshot().unwrap(),
        Some(terminal)
    );
    assert_eq!(
        connection
            .requests
            .submit_text(
                8,
                1,
                "utterance:one",
                "用户输入",
                ThreadQueueReconcileMode::ReconcileOnly
            )
            .await
            .unwrap_err(),
        HmiError::Fenced
    );
    connection
        .requests
        .submit_text(
            7,
            1,
            "utterance:one",
            "用户输入",
            ThreadQueueReconcileMode::ReconcileOnly,
        )
        .await
        .unwrap();
    connection.requests.stop_output(7).unwrap();
    assert!(!connection.requests.permits_output(&delta.scope).unwrap());
    peer.await.unwrap();
    connection.events.shutdown().await.unwrap();
}

#[tokio::test]
async fn cancellation_before_admission_interrupts_late_turn_without_presenting_it() {
    let (listener, url) = listener().await;
    let (seen_tx, seen_rx) = tokio::sync::oneshot::channel();
    let (release_tx, release_rx) = tokio::sync::oneshot::channel();
    let peer = tokio::spawn(async move {
        let mut socket = accept_async(listener.accept().await.unwrap().0)
            .await
            .unwrap();
        initialize(&mut socket).await;
        let admission_request = read(&mut socket).await;
        seen_tx.send(()).unwrap();
        release_rx.await.unwrap();
        reply(
            &mut socket,
            &admission_request,
            admission(&admission_request, false),
        )
        .await;
        started(&mut socket, &admission_request).await;
        delta(&mut socket, "thread:test", "canceled output").await;
        let mut interrupted = false;
        let mut deleted = false;
        for _ in 0..2 {
            let request = read(&mut socket).await;
            match request["method"].as_str().unwrap() {
                "turn/interrupt" => {
                    interrupted = true;
                    assert_eq!(request["params"]["turnId"], "turn:test");
                    reply(&mut socket, &request, json!({})).await;
                }
                "thread/queue/delete" => {
                    deleted = true;
                    reply(&mut socket, &request, json!({"deleted":false})).await;
                }
                method => panic!("unexpected {method}"),
            }
        }
        assert!(interrupted && deleted);
        completed(&mut socket, "interrupted").await;
        let _ = socket.close(None).await;
    });
    let mut connection =
        HmiConnectionV1::connect(args(&url), binding(), 16, Duration::from_secs(3))
            .await
            .unwrap();
    let requests = connection.requests.clone();
    let submit = tokio::spawn(async move {
        requests
            .submit_text(
                7,
                1,
                "cancel:one",
                "input",
                ThreadQueueReconcileMode::AllowIfAbsent,
            )
            .await
    });
    seen_rx.await.unwrap();
    connection.requests.interrupt(7).await.unwrap();
    release_tx.send(()).unwrap();
    let result = tokio::time::timeout(Duration::from_secs(3), connection.events.next())
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert!(matches!(
        result.kind,
        HmiEventKindV1::Terminal {
            outcome: HmiTerminalV1 {
                status: HmiTerminalStatusV1::Interrupted,
                ..
            }
        }
    ));
    assert!(!connection.requests.permits_output(&result.scope).unwrap());
    submit.await.unwrap().unwrap();
    peer.await.unwrap();
    connection.events.shutdown().await.unwrap();
}

#[tokio::test]
async fn real_socket_reconnect_resumes_exact_thread_and_revokes_old_handle() {
    let (listener, url) = listener().await;
    let peer = tokio::spawn(async move {
        for _ in 0..2 {
            let mut socket = accept_async(listener.accept().await.unwrap().0)
                .await
                .unwrap();
            initialize(&mut socket).await;
            let request = read(&mut socket).await;
            assert_eq!(request["method"], "thread/queue/reconcile");
            assert_eq!(request["params"]["mode"], "reconcileOnly");
            reply(&mut socket, &request, admission(&request, true)).await;
            let _ = socket.next().await;
        }
    });
    let connection = HmiConnectionV1::connect(args(&url), binding(), 16, Duration::from_secs(3))
        .await
        .unwrap();
    let old = connection.requests.clone();
    old.submit_text(
        7,
        1,
        "recover:one",
        "input",
        ThreadQueueReconcileMode::ReconcileOnly,
    )
    .await
    .unwrap();
    let reattached = connection.reconnect(args(&url), 16).await.unwrap();
    assert_eq!(
        old.submit_text(
            7,
            1,
            "recover:one",
            "input",
            ThreadQueueReconcileMode::ReconcileOnly
        )
        .await
        .unwrap_err(),
        HmiError::Fenced
    );
    assert_eq!(
        old.client_message_id("recover:one").unwrap(),
        reattached
            .requests
            .client_message_id("recover:one")
            .unwrap()
    );
    reattached
        .requests
        .submit_text(
            7,
            1,
            "recover:one",
            "input",
            ThreadQueueReconcileMode::ReconcileOnly,
        )
        .await
        .unwrap();
    reattached.events.shutdown().await.unwrap();
    peer.await.unwrap();
}
