use super::connect_websocket;
use crate::error::ApiError;
use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use codex_http_client::HttpClientFactory;
use codex_http_client::OutboundProxyPolicy;
use futures::SinkExt;
use futures::StreamExt;
use http::HeaderMap;
use http::StatusCode;
use pretty_assertions::assert_eq;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;
use tokio::net::TcpListener;
use tokio_tungstenite::tungstenite::Message;
use url::Url;

const PROBE_SCHEME_ENV: &str = "CODEX_RESPONSES_TLS_PROBE_SCHEME";
const INVALID_CA_PATH: &str = "/codex-responses-websocket-nonexistent-custom-ca.pem";
const PROBE_TIMEOUT: Duration = Duration::from_secs(/*secs*/ 10);
const EXCHANGE_TIMEOUT: Duration = Duration::from_secs(/*secs*/ 5);
const PROBE_POLL_INTERVAL: Duration = Duration::from_millis(/*millis*/ 10);

#[test]
fn plain_responses_websocket_ignores_unused_invalid_ca_in_subprocess() -> Result<()> {
    run_isolated_probe("ws")
}

#[test]
fn secure_responses_websocket_keeps_invalid_ca_rejection_in_subprocess() -> Result<()> {
    run_isolated_probe("wss")
}

fn run_isolated_probe(scheme: &str) -> Result<()> {
    assert!(
        !std::path::Path::new(INVALID_CA_PATH).exists(),
        "the isolated probe requires an absent custom CA file"
    );
    let executable = std::env::current_exe().context("locate Responses test executable")?;
    let mut command = Command::new(executable);
    command.args([
        "--exact",
        "endpoint::responses_websocket::tls_tests::isolated_responses_tls_probe",
        "--nocapture",
    ]);
    for key in [
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
        "SSL_CERT_FILE",
    ] {
        command.env_remove(key);
    }
    command
        .env("CODEX_CA_CERTIFICATE", INVALID_CA_PATH)
        .env(PROBE_SCHEME_ENV, scheme)
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());
    let mut child = command
        .spawn()
        .context("spawn isolated Responses TLS probe")?;
    let started = Instant::now();
    let outcome = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Ok(status),
            Ok(None) if started.elapsed() < PROBE_TIMEOUT => {
                std::thread::sleep(PROBE_POLL_INTERVAL);
            }
            Ok(None) => break Err(anyhow::anyhow!("Responses {scheme} probe timed out")),
            Err(error) => break Err(error.into()),
        }
    };
    let status = match outcome {
        Ok(status) => status,
        Err(error) => {
            let kill_result = child.kill();
            let wait_result = child.wait();
            bail!(
                "Responses {scheme} probe failed: {error}; cleanup kill={kill_result:?}; wait={wait_result:?}"
            );
        }
    };
    assert!(
        status.success(),
        "Responses {scheme} probe failed: {status}"
    );
    Ok(())
}

#[tokio::test]
async fn isolated_responses_tls_probe() -> Result<()> {
    let Ok(scheme) = std::env::var(PROBE_SCHEME_ENV) else {
        return Ok(());
    };
    assert_eq!(std::env::var("CODEX_CA_CERTIFICATE")?, INVALID_CA_PATH);
    let factory = HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault);
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let url = Url::parse(&format!("{scheme}://{address}/v1/responses"))?;

    match scheme.as_str() {
        "ws" => {
            let expected = Message::Text("Responses plain WebSocket".into());
            let server_expected = expected.clone();
            let mut server = tokio::spawn(async move {
                let (socket, _) = listener.accept().await?;
                let mut websocket = tokio_tungstenite::accept_async(socket).await?;
                let request = websocket.next().await.context("receive probe message")??;
                ensure!(
                    request == server_expected,
                    "unexpected probe request: {request:?}; expected {server_expected:?}"
                );
                websocket.send(request).await?;
                Ok::<(), anyhow::Error>(())
            });
            let outcome = tokio::time::timeout(EXCHANGE_TIMEOUT, async {
                let (mut websocket, status, _, _) =
                    connect_websocket(url, HeaderMap::new(), &factory, /*turn_state*/ None).await?;
                ensure!(
                    status == StatusCode::SWITCHING_PROTOCOLS,
                    "expected a WebSocket upgrade, got {status}"
                );
                websocket.send(expected.clone()).await?;
                let response = websocket.next().await.context("receive echoed message")??;
                ensure!(
                    response == expected,
                    "unexpected echoed response: {response:?}; expected {expected:?}"
                );
                (&mut server).await??;
                Ok::<(), anyhow::Error>(())
            })
            .await;
            if !server.is_finished() {
                server.abort();
                let _ = server.await;
            }
            outcome??;
        }
        "wss" => {
            let result = tokio::time::timeout(
                EXCHANGE_TIMEOUT,
                connect_websocket(url, HeaderMap::new(), &factory, /*turn_state*/ None),
            )
            .await?;
            match result {
                Err(ApiError::Stream(message)) => {
                    assert!(message.starts_with("failed to configure websocket TLS:"));
                    assert!(message.contains(INVALID_CA_PATH));
                }
                Err(error) => bail!("expected the existing eager CA rejection, got {error}"),
                Ok((websocket, _, _, _)) => {
                    drop(websocket);
                    bail!("secure WebSocket unexpectedly accepted an invalid custom CA");
                }
            }
            drop(listener);
        }
        _ => bail!("unexpected isolated Responses probe scheme: {scheme}"),
    }
    Ok(())
}
