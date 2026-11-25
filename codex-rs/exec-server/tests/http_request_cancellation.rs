#![cfg(unix)]

mod common;

use std::time::Duration;

use anyhow::bail;
use codex_exec_server::ExecServerClient;
use codex_exec_server::HttpRedirectPolicy;
use codex_exec_server::HttpRequestCancelParams;
use codex_exec_server::HttpRequestCancelResponse;
use codex_exec_server::HttpRequestParams;
use codex_exec_server::HttpRequestResponse;
use codex_exec_server::InitializeParams;
use codex_exec_server::RemoteExecServerConnectArgs;
use codex_exec_server_protocol::JSONRPCMessage;
use codex_exec_server_protocol::RequestId;
use codex_http_client::HttpClientFactory;
use codex_http_client::OutboundProxyPolicy;
use common::exec_server::ExecServerHarness;
use common::exec_server::exec_server;
use futures::poll;
use pretty_assertions::assert_eq;
use serde::de::DeserializeOwned;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::net::TcpListener;
use tokio::net::TcpStream;
use tokio::time::timeout;

const LIMIT: Duration = Duration::from_secs(5);

fn request(url: String, request_id: &str) -> HttpRequestParams {
    HttpRequestParams {
        method: "DELETE".to_string(),
        url,
        headers: Vec::new(),
        body: None,
        timeout_ms: None,
        redirect_policy: HttpRedirectPolicy::Stop,
        request_id: request_id.to_string(),
        stream_response: true,
    }
}

async fn accept_headers(listener: &TcpListener) -> anyhow::Result<TcpStream> {
    let (stream, _) = timeout(LIMIT, listener.accept()).await??;
    let mut reader = BufReader::new(stream);
    loop {
        let mut line = String::new();
        let count = timeout(LIMIT, reader.read_line(&mut line)).await??;
        if count == 0 {
            bail!("HTTP request ended before headers");
        }
        if line == "\r\n" {
            return Ok(reader.into_inner());
        }
    }
}

async fn response<T: DeserializeOwned>(
    server: &mut ExecServerHarness,
    id: RequestId,
) -> anyhow::Result<T> {
    let event = server
        .wait_for_event(|event| match event {
            JSONRPCMessage::Response(response) => response.id == id,
            JSONRPCMessage::Error(error) => error.id == id,
            _ => false,
        })
        .await?;
    match event {
        JSONRPCMessage::Response(response) => Ok(serde_json::from_value(response.result)?),
        other => bail!("RPC failed: {other:?}"),
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn delete_body_drop_and_header_future_drop_close_the_actual_remote_request()
-> anyhow::Result<()> {
    let mut server = exec_server().await?;
    let client = ExecServerClient::connect_websocket(RemoteExecServerConnectArgs::new(
        server.websocket_url().to_string(),
        "http-cancel".to_string(),
        HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault),
    ))
    .await?;
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let url = format!("http://{}/delete", listener.local_addr()?);
    for send_headers in [true, false] {
        let mut pending = Box::pin(client.http_request_stream(request(url.clone(), "caller-id")));
        let mut peer = tokio::select! {
            peer = accept_headers(&listener) => peer?,
            _ = pending.as_mut() => bail!("request completed without HTTP response"),
        };
        if send_headers {
            peer.write_all(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
                .await?;
            let (headers, body) = timeout(LIMIT, pending).await??;
            assert_eq!(headers.status, 200);
            drop(body);
        } else {
            drop(pending);
        }
        // The peer has not ended its body and the request has no HTTP timeout.
        // Removing only the orchestrator's route cannot make this read reach EOF.
        assert_eq!(timeout(LIMIT, peer.read(&mut [0])).await??, 0);
    }
    let mut fresh = Box::pin(client.http_request_stream(request(url, "same-caller-id")));
    let mut peer = tokio::select! {
        peer = accept_headers(&listener) => peer?,
        _ = fresh.as_mut() => bail!("fresh request completed early"),
    };
    peer.write_all(b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n")
        .await?;
    let (headers, mut body) = timeout(LIMIT, fresh).await??;
    assert_eq!(headers.status, 204);
    assert_eq!(timeout(LIMIT, body.recv()).await??, None);
    drop(body);
    drop(client);
    server.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn queued_request_cancels_without_network_and_unknown_id_is_not_success() -> anyhow::Result<()>
{
    let mut server = exec_server().await?;
    let id = server
        .send_request(
            "initialize",
            serde_json::to_value(InitializeParams {
                process_exit_observation: true,
                client_name: "http-queued-cancel".to_string(),
                resume_session_id: None,
            })?,
        )
        .await?;
    let _: serde_json::Value = response(&mut server, id).await?;
    server
        .send_notification("initialized", serde_json::json!({}))
        .await?;
    let active_listener = TcpListener::bind("127.0.0.1:0").await?;
    let queued_listener = TcpListener::bind("127.0.0.1:0").await?;
    let active_id = server
        .send_request(
            "http/requestCancellableV1",
            serde_json::to_value(request(
                format!("http://{}/active", active_listener.local_addr()?),
                "active",
            ))?,
        )
        .await?;
    let mut active = accept_headers(&active_listener).await?;
    server
        .send_request(
            "http/requestCancellableV1",
            serde_json::to_value(request(
                format!("http://{}/queued", queued_listener.local_addr()?),
                "queued",
            ))?,
        )
        .await?;
    let id = server
        .send_request(
            "http/cancelRequestV1",
            serde_json::to_value(HttpRequestCancelParams {
                request_id: "queued".to_string(),
            })?,
        )
        .await?;
    assert_eq!(
        timeout(
            LIMIT,
            response::<HttpRequestCancelResponse>(&mut server, id)
        )
        .await??,
        HttpRequestCancelResponse::Cancelled
    );
    let queued_accept = queued_listener.accept();
    tokio::pin!(queued_accept);
    assert!(poll!(queued_accept.as_mut()).is_pending());
    let id = server
        .send_request(
            "http/cancelRequestV1",
            serde_json::to_value(HttpRequestCancelParams {
                request_id: "queued".to_string(),
            })?,
        )
        .await?;
    assert_eq!(
        response::<HttpRequestCancelResponse>(&mut server, id).await?,
        HttpRequestCancelResponse::NotActive
    );
    // Cancelling the queued/unknown id did not close the already active request.
    active
        .write_all(b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        .await?;
    assert_eq!(
        response::<HttpRequestResponse>(&mut server, active_id)
            .await?
            .status,
        204
    );
    drop(active);
    let id = server
        .send_request(
            "http/request",
            serde_json::to_value(request(
                format!("http://{}/fresh", active_listener.local_addr()?),
                "fresh",
            ))?,
        )
        .await?;
    let mut fresh = accept_headers(&active_listener).await?;
    fresh
        .write_all(b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n")
        .await?;
    assert_eq!(
        response::<HttpRequestResponse>(&mut server, id)
            .await?
            .status,
        204
    );
    assert!(poll!(queued_accept.as_mut()).is_pending());
    server.shutdown().await?;
    Ok(())
}
