//! Terminal receipts bind the actual provider output across SSE and GET.

use pretty_assertions::assert_ne;

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_http_client::HttpClientFactory;
use codex_http_client::OutboundProxyPolicy;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio::sync::oneshot;

use super::super::ModelEvent;
use super::super::ModelRequest;
use super::super::ResponsesModel;

async fn provider(
    bodies: Vec<(&'static str, String)>,
) -> Result<(ResponsesModel, ModelRequest, tokio::task::JoinHandle<Result<()>>)> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let peer = tokio::spawn(async move {
        for (index, (content_type, body)) in bodies.into_iter().enumerate() {
            let (mut socket, _) = tokio::time::timeout(Duration::from_secs(3), listener.accept()).await??;
            let mut headers = Vec::new();
            while !headers.ends_with(b"\r\n\r\n") {
                ensure!(headers.len() < 8192, "fixture header bound");
                headers.push(socket.read_u8().await?);
            }
            let headers = String::from_utf8(headers)?;
            if index == 0 {
                ensure!(headers.starts_with("POST /v1/responses "), "unexpected original request");
            } else {
                ensure!(headers.starts_with("GET /v1/responses/response-original "), "recovery retried or changed response");
            }
            let content_length = headers.lines().find_map(|line| {
                let (name, value) = line.split_once(':')?;
                name.eq_ignore_ascii_case("content-length").then(|| value.trim().parse::<usize>())
            }).transpose()?.unwrap_or(0);
            ensure!(content_length <= 4096, "fixture request body bound");
            let mut request_body = vec![0; content_length];
            socket.read_exact(&mut request_body).await?;
            let response = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len(),
            );
            socket.write_all(response.as_bytes()).await?;
            socket.shutdown().await?;
        }
        Ok(())
    });
    let model = ResponsesModel::new(
        &HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault),
        format!("http://{address}/v1/responses"),
        /*bearer*/ None,
        Duration::from_secs(3),
        /*max_stream_bytes*/ 16_384,
    )?;
    let request = ModelRequest {
        operation_id: "operation:terminal-original".to_string(),
        body: br#"{"model":"fixture","stream":true}"#.to_vec(),
    };
    Ok((model, request, peer))
}

fn stream_events(output: &[Value], terminal: Value) -> String {
    std::iter::once(json!({"type":"response.created","response":{"id":"response-original"}}))
        .chain(output.iter().cloned().map(|item| json!({"type":"response.output_item.done","item":item})))
        .chain(std::iter::once(json!({"type":"response.completed","response":terminal})))
        .map(|event| format!("data: {event}\n\n"))
        .collect()
}

#[tokio::test]
async fn sse_and_get_evidence_bind_the_same_complete_output() -> Result<()> {
    let output = vec![
        json!({"type":"message","id":"message-1","content":[{"type":"output_text","text":"exact result","annotations":[]}]}),
        json!({"type":"function_call","call_id":"call-original","name":"inspect","arguments":"{\"path\":\"a\"}"}),
    ];
    let terminal = json!({
        "id":"response-original","status":"completed","output":output,
        "usage":{"input_tokens":3,"output_tokens":7},
    });
    let changed = json!({
        "id":"response-original","status":"completed",
        "output":[output[0].clone(), {
            "type":"function_call","call_id":"call-original","name":"inspect","arguments":"{\"path\":\"b\"}"
        }],
        "usage":{"input_tokens":3,"output_tokens":7},
    });
    let (model, request, peer) = provider(vec![
        ("text/event-stream", stream_events(&output, terminal.clone())),
        ("application/json", terminal.to_string()),
        ("application/json", changed.to_string()),
    ]).await?;
    let (terminal_tx, terminal_rx) = oneshot::channel();
    let mut stream = model.open(&request).await?.with_terminal_observer(&request, move |terminal| async move {
        terminal_tx.send(terminal).map_err(|_| anyhow::anyhow!("fixture observer dropped"))?;
        Ok(())
    })?;
    let mut seen_items = Vec::new();
    while let Some(event) = stream.next().await? {
        if let ModelEvent::Item(item) = event {
            seen_items.push(item);
        }
    }
    let streamed = terminal_rx.await?;
    assert_eq!(seen_items, output);
    let recovered = model.reconcile(&request, "response-original").await?.context("GET completion")?;
    assert_eq!(streamed.evidence_digest(), recovered.terminal()?.evidence_digest());
    let changed = model.reconcile(&request, "response-original").await?.context("changed GET completion")?;
    assert_ne!(streamed.evidence_digest(), changed.terminal()?.evidence_digest());
    peer.await??;
    Ok(())
}

#[tokio::test]
async fn contradictory_terminal_output_cannot_mint_observation_evidence() -> Result<()> {
    let streamed = json!({"type":"function_call","call_id":"call-original","name":"inspect","arguments":"{}"});
    let terminal = json!({
        "id":"response-original","status":"completed",
        "output":[{"type":"function_call","call_id":"call-changed","name":"inspect","arguments":"{}"}],
        "usage":{"output_tokens":1},
    });
    let (model, request, peer) = provider(vec![
        ("text/event-stream", stream_events(&[streamed], terminal)),
    ]).await?;
    let observed = Arc::new(AtomicBool::new(false));
    let callback_observed = Arc::clone(&observed);
    let mut stream = model.open(&request).await?.with_terminal_observer(&request, move |_| async move {
        callback_observed.store(true, Ordering::SeqCst);
        Ok(())
    })?;
    assert!(matches!(stream.next().await?, Some(ModelEvent::Created(_))));
    assert!(matches!(stream.next().await?, Some(ModelEvent::Item(_))));
    assert!(stream.next().await.is_err());
    assert!(!observed.load(Ordering::SeqCst));
    peer.await??;
    Ok(())
}

#[tokio::test]
async fn missing_complete_output_is_compatible_only_without_a_terminal_observer() -> Result<()> {
    let terminal = json!({"id":"response-original","status":"completed","usage":{}});
    let body = stream_events(&[], terminal);
    let (model, request, peer) = provider(vec![("text/event-stream", body)]).await?;
    let observed = Arc::new(AtomicBool::new(false));
    let callback_observed = Arc::clone(&observed);
    let mut stream = model.open(&request).await?.with_terminal_observer(&request, move |_| async move {
        callback_observed.store(true, Ordering::SeqCst);
        Ok(())
    })?;
    assert!(matches!(stream.next().await?, Some(ModelEvent::Created(_))));
    assert!(stream.next().await.is_err());
    assert!(!observed.load(Ordering::SeqCst));
    peer.await??;
    Ok(())
}

#[tokio::test]
async fn get_rejects_non_object_output_instead_of_issuing_a_receipt() -> Result<()> {
    let terminal = json!({"id":"response-original","status":"completed","output":[],"usage":{}});
    let (model, request, peer) = provider(vec![
        ("text/event-stream", stream_events(&[], terminal)),
        ("application/json", json!({
            "id":"response-original","status":"completed","output":["not an output item"],"usage":{}
        }).to_string()),
    ]).await?;
    let mut stream = model.open(&request).await?;
    while stream.next().await?.is_some() {}
    assert!(model.reconcile(&request, "response-original").await.is_err());
    peer.await??;
    Ok(())
}

