//! Concurrent counterpart of the scripted WebSocket fixture.
//!
//! A completed script does not close a connection unless its configuration explicitly asks
//! for that. This lets a test distinguish a policy-driven reconnect from server-forced EOF.

use std::collections::VecDeque;
use std::sync::Arc;
use std::sync::Mutex;

use futures::SinkExt;
use futures::StreamExt;
use tokio::net::TcpListener;
use tokio::sync::Notify;
use tokio::sync::oneshot;
use tokio::task::JoinSet;
use tokio_tungstenite::accept_hdr_async_with_config;
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::tungstenite::handshake::server::Request;
use tokio_tungstenite::tungstenite::handshake::server::Response;
use wiremock::http::HeaderName;
use wiremock::http::HeaderValue;

use super::WebSocketConnectionConfig;
use super::WebSocketHandshake;
use super::WebSocketRequest;
use super::WebSocketTestServer;
use super::parse_ws_request_body;
use super::websocket_accept_config;

pub async fn start_concurrent_websocket_server(
    connections: Vec<WebSocketConnectionConfig>,
) -> WebSocketTestServer {
    let start = std::time::Instant::now();
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind concurrent websocket server");
    let addr = listener.local_addr().expect("websocket server address");
    let uri = format!("ws://{addr}");
    let connections_log = Arc::new(Mutex::new(Vec::new()));
    let handshakes_log = Arc::new(Mutex::new(Vec::new()));
    let request_log_updated = Arc::new(Notify::new());
    let requests = Arc::clone(&connections_log);
    let handshakes = Arc::clone(&handshakes_log);
    let request_log = Arc::clone(&request_log_updated);
    let (shutdown_tx, mut shutdown_rx) = oneshot::channel();

    let task = tokio::spawn(async move {
        let mut pending = VecDeque::from(connections);
        let mut handlers = JoinSet::new();
        loop {
            let (stream, _) = tokio::select! {
                _ = &mut shutdown_rx => break,
                finished = handlers.join_next(), if !handlers.is_empty() => {
                    if let Some(Err(error)) = finished {
                        eprintln!("concurrent websocket handler failed: {error}");
                    }
                    continue;
                }
                accepted = listener.accept() => {
                    match accepted {
                        Ok(value) => value,
                        Err(error) => {
                            eprintln!("concurrent websocket accept failed: {error}");
                            break;
                        }
                    }
                }
            };
            let Some(connection) = pending.front().cloned() else {
                continue;
            };
            if let Some(delay) = connection.accept_delay {
                tokio::select! {
                    _ = &mut shutdown_rx => break,
                    _ = tokio::time::sleep(delay) => {}
                }
            }
            let handshake_log = Arc::clone(&handshakes);
            let response_headers = connection.response_headers.clone();
            let callback = move |req: &Request, mut response: Response| {
                let headers = req
                    .headers()
                    .iter()
                    .filter_map(|(name, value)| {
                        value
                            .to_str()
                            .ok()
                            .map(|value| (name.as_str().to_string(), value.to_string()))
                    })
                    .collect();
                handshake_log.lock().unwrap().push(WebSocketHandshake {
                    uri: req.uri().to_string(),
                    headers,
                });
                for (name, value) in &response_headers {
                    if let (Ok(name), Ok(value)) = (
                        HeaderName::from_bytes(name.as_bytes()),
                        HeaderValue::from_str(value),
                    ) {
                        response.headers_mut().insert(name, value);
                    }
                }
                Ok(response)
            };
            let handshake = tokio::select! {
                _ = &mut shutdown_rx => break,
                handshake = accept_hdr_async_with_config(
                    stream, callback, Some(websocket_accept_config()),
                ) => handshake,
            };
            let mut ws_stream = match handshake {
                Ok(stream) => stream,
                // As in the serial fixture, an ordinary HTTP probe must not consume a script.
                Err(_) => continue,
            };
            pending.pop_front();
            let connection_index = {
                let mut log = requests.lock().unwrap();
                log.push(Vec::new());
                log.len() - 1
            };
            let requests = Arc::clone(&requests);
            let request_log = Arc::clone(&request_log);
            handlers.spawn(async move {
                let mut scripted_requests = connection.requests.into_iter();
                while let Some(Ok(message)) = ws_stream.next().await {
                    let Some(body) = parse_ws_request_body(message) else {
                        continue;
                    };
                    let request_index = {
                        let mut log = requests.lock().unwrap();
                        let connection_log = &mut log[connection_index];
                        connection_log.push(WebSocketRequest { body });
                        connection_log.len() - 1
                    };
                    eprintln!(
                        "[concurrent ws test server +{}ms] connection={connection_index} received request={request_index}",
                        start.elapsed().as_millis(),
                    );
                    // Retain a permit if the fixture's request waiter is not registered yet.
                    request_log.notify_one();
                    let Some(request_events) = scripted_requests.next() else {
                        // Keep this socket alive, and record unexpected reuse instead of closing it.
                        continue;
                    };
                    for event in request_events {
                        if ws_stream
                            .send(Message::Text(event.to_string().into()))
                            .await
                            .is_err()
                        {
                            return;
                        }
                    }
                    if connection.close_after_requests && scripted_requests.len() == 0 {
                        let _ = ws_stream.close(None).await;
                        return;
                    }
                }
            });
        }
        // Dropping the outer task also drops JoinSet and aborts its owned connection tasks.
        handlers.shutdown().await;
    });

    WebSocketTestServer {
        uri,
        connections: connections_log,
        handshakes: handshakes_log,
        request_log_updated,
        shutdown: shutdown_tx,
        task,
    }
}
