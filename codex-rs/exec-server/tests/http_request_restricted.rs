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
use codex_exec_server::HttpRequestRestrictedParams;
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

fn request(url: String, original: String, id: &str) -> HttpRequestRestrictedParams {
    HttpRequestRestrictedParams {
        request: HttpRequestParams {
            method: "GET".to_string(),
            url,
            headers: Vec::new(),
            body: None,
            timeout_ms: None,
            redirect_policy: HttpRedirectPolicy::Follow,
            request_id: id.to_string(),
            stream_response: true,
        },
        configured_resource_origin: original,
    }
}

async fn accept_headers(listener: &TcpListener) -> anyhow::Result<TcpStream> {
    let (stream, _) = timeout(LIMIT, listener.accept()).await??;
    let mut reader = BufReader::new(stream);
    let mut total = 0;
    loop {
        let mut line = String::new();
        let count = timeout(LIMIT, reader.read_line(&mut line)).await??;
        total += count;
        if count == 0 || total > 8192 {
            bail!("HTTP headers incomplete or oversized");
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
async fn remote_restricted_request_keeps_original_authority_through_redirect_and_body_drop()
-> anyhow::Result<()> {
    let mut server = exec_server().await?;
    let client = ExecServerClient::connect_websocket(RemoteExecServerConnectArgs::new(
        server.websocket_url().to_string(),
        "http-restricted".to_string(),
        HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault),
    ))
    .await?;
    let allowed = TcpListener::bind("127.0.0.1:0").await?;
    let denied = TcpListener::bind("127.0.0.1:0").await?;
    let origin = format!("http://{}", allowed.local_addr()?);
    let denied_url = format!("http://{}/private", denied.local_addr()?);
    let mut pending = Box::pin(client.http_request_stream_restricted(request(
        format!("{origin}/redirect"),
        origin.clone(),
        "caller-id",
    )));
    let mut peer = tokio::select! {
        peer = accept_headers(&allowed) => peer?,
        _ = pending.as_mut() => bail!("request completed before original response"),
    };
    peer.write_all(format!("HTTP/1.1 302 Found\r\nLocation: {denied_url}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").as_bytes()).await?;
    let result = timeout(LIMIT, pending).await?;
    assert!(matches!(result, Err(error) if error.to_string().contains("address capability")));
    let denied_accept = denied.accept();
    tokio::pin!(denied_accept);
    assert!(poll!(denied_accept.as_mut()).is_pending());
    let mut pending = Box::pin(client.http_request_stream_restricted(request(
        format!("{origin}/stream"),
        origin,
        "same-caller-id",
    )));
    let mut peer = tokio::select! {
        peer = accept_headers(&allowed) => peer?,
        _ = pending.as_mut() => bail!("next request completed before HTTP response"),
    };
    peer.write_all(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
        .await?;
    let (headers, body) = timeout(LIMIT, pending).await??;
    assert_eq!(headers.status, 200);
    drop(body);
    assert_eq!(timeout(LIMIT, peer.read(&mut [0])).await??, 0);
    assert!(poll!(denied_accept.as_mut()).is_pending());
    drop(client);
    server.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn queued_restricted_request_cancels_its_nested_id_without_http_or_affecting_other_owner()
-> anyhow::Result<()> {
    let mut server = exec_server().await?;
    let id = server
        .send_request(
            "initialize",
            serde_json::to_value(InitializeParams {
                process_exit_observation: true,
                client_name: "restricted-queue".to_string(),
                resume_session_id: None,
            })?,
        )
        .await?;
    let _: serde_json::Value = response(&mut server, id).await?;
    server
        .send_notification("initialized", serde_json::json!({}))
        .await?;
    let active = TcpListener::bind("127.0.0.1:0").await?;
    let queued = TcpListener::bind("127.0.0.1:0").await?;
    let active_url = format!("http://{}/active", active.local_addr()?);
    let active_id = server
        .send_request(
            "http/requestRestrictedV1",
            serde_json::to_value(request(active_url.clone(), active_url, "active"))?,
        )
        .await?;
    let mut peer = accept_headers(&active).await?;
    let queued_url = format!("http://{}/queued", queued.local_addr()?);
    server
        .send_request(
            "http/requestRestrictedV1",
            serde_json::to_value(request(queued_url.clone(), queued_url, "queued"))?,
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
    let queued_accept = queued.accept();
    tokio::pin!(queued_accept);
    assert!(poll!(queued_accept.as_mut()).is_pending());
    peer.write_all(b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        .await?;
    assert_eq!(
        response::<HttpRequestResponse>(&mut server, active_id)
            .await?
            .status,
        204
    );
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
    assert!(poll!(queued_accept.as_mut()).is_pending());
    server.shutdown().await?;
    Ok(())
}
