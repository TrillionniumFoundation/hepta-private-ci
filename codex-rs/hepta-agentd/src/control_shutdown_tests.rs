//! Connection ownership tests, not proof of termination of external effects.
use super::*;
use tokio::sync::oneshot;

#[tokio::test]
async fn graceful_control_drain_waits_for_acknowledgement() {
    let mut connections = JoinSet::new();
    let (sender, receiver) = oneshot::channel();
    connections.spawn(async move {
        receiver.await.expect("completion signal");
        Ok(())
    });
    let completion = tokio::spawn(async move {
        tokio::task::yield_now().await;
        sender.send(()).expect("handler still alive");
    });
    drain_connections(&mut connections, Duration::from_secs(1))
        .await
        .expect("graceful completion");
    completion.await.expect("completion task joined");
    assert!(connections.is_empty());
}

#[tokio::test]
async fn forced_control_drain_reaps_tasks_and_is_not_success() {
    let mut connections = JoinSet::new();
    let (sender, receiver) = oneshot::channel::<()>();
    connections.spawn(async move {
        let outcome = std::future::pending::<Result<(), AgentdError>>().await;
        drop(sender);
        outcome
    });
    let error = drain_connections(&mut connections, Duration::from_millis(10))
        .await
        .expect_err("forced drain must fail");
    assert!(error.to_string().contains("indeterminate"));
    assert!(connections.is_empty());
    assert!(
        timeout(Duration::from_secs(1), receiver)
            .await
            .expect("task guard was dropped")
            .is_err()
    );
}

#[tokio::test]
async fn control_task_panic_is_not_hidden_by_shutdown() {
    let mut connections: JoinSet<Result<(), AgentdError>> = JoinSet::new();
    connections.spawn(async { panic!("injected control task panic") });
    connections.spawn(std::future::pending());
    drain_connections(&mut connections, Duration::from_secs(1))
        .await
        .expect_err("task panic must fail drain");
    assert!(connections.is_empty());
}

#[tokio::test]
async fn error_frame_never_echoes_untrusted_request_generation() {
    let (temp, state) = super::tests::fixture();
    let expected_generation = state.current_generation().expect("current generation");
    let socket = temp.path().join("generation.sock");
    let mut listener = UnixListener::bind(&socket).await.expect("bind");
    let server = tokio::spawn(async move {
        let stream = listener.accept().await.expect("accept");
        serve_connection_with(stream, state, |_| async {
            panic!("unsupported schema must not dispatch")
        })
        .await
        .expect("error response");
    });
    let request_id = 7;
    let supplied_generation = 999;
    let mut request = AgentdRequest::health(request_id, supplied_generation);
    request.schema_version = 0;
    let mut bytes = serde_json::to_vec(&request).expect("request");
    bytes.push(b'\n');
    let mut stream = UnixStream::connect(&socket).await.expect("connect");
    stream.write_all(&bytes).await.expect("write");
    let mut frame = String::new();
    BufReader::new(stream)
        .read_line(&mut frame)
        .await
        .expect("read");
    let response: AgentdResponse = serde_json::from_str(&frame).expect("response");
    assert_eq!(
        (response.request_id, response.current_generation),
        (request_id, expected_generation)
    );
    assert!(matches!(
        response.payload,
        AgentdPayload::Error { code, .. } if code == "unsupported_schema"
    ));
    server.await.expect("server joined");
}
