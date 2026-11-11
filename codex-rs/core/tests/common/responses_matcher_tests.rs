use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpStream;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::body_json;

use super::mount_response_once_match;
use super::mount_sse_once_match;
use super::sse_completed;

#[derive(Debug)]
enum MatchedHelper {
    Response,
    Sse,
}

async fn send_request(
    server: &MockServer,
    method: &str,
    path: &str,
    body: &Value,
) -> Result<u16> {
    let body = serde_json::to_vec(body)?;
    let length = body.len();
    let address = server.address();
    let mut stream = TcpStream::connect(address).await?;
    let headers = format!(
        "{method} {path} HTTP/1.1\r\nHost: {address}\r\nContent-Type: application/json\r\nContent-Length: {length}\r\nConnection: close\r\n\r\n"
    );
    stream.write_all(headers.as_bytes()).await?;
    stream.write_all(&body).await?;

    let mut response = Vec::new();
    stream.take(8193).read_to_end(&mut response).await?;
    ensure!(response.len() <= 8192, "loopback response exceeded its bound");
    let response = std::str::from_utf8(&response)?;
    let mut status = response
        .lines()
        .next()
        .context("loopback response has no status line")?
        .split_whitespace();
    ensure!(status.next() == Some("HTTP/1.1"), "unexpected HTTP version");
    status
        .next()
        .context("loopback response has no status code")?
        .parse()
        .context("invalid loopback status code")
}

#[tokio::test]
async fn matched_response_helpers_record_only_accepted_requests() -> Result<()> {
    tokio::time::timeout(Duration::from_secs(2), async {
        for helper in [MatchedHelper::Response, MatchedHelper::Sse] {
            let server = MockServer::start().await;
            let accepted = json!({ "input": [], "route": "accepted" });
            let rejected = json!({ "input": [], "route": "rejected" });
            let response_mock = match helper {
                MatchedHelper::Response => {
                    mount_response_once_match(
                        &server,
                        body_json(accepted.clone()),
                        ResponseTemplate::new(200).set_body_json(json!({ "ok": true })),
                    )
                    .await
                }
                MatchedHelper::Sse => {
                    mount_sse_once_match(
                        &server,
                        body_json(accepted.clone()),
                        sse_completed("response-matched"),
                    )
                    .await
                }
            };

            for (method, path, body) in [
                ("GET", "/v1/responses", &accepted),
                ("POST", "/v1/other", &accepted),
                ("POST", "/v1/responses", &rejected),
            ] {
                assert_eq!(send_request(&server, method, path, body).await?, 404);
                assert!(
                    response_mock.requests().is_empty(),
                    "{helper:?} recorded a rejected request: {method} {path}"
                );
            }

            assert_eq!(
                send_request(&server, "POST", "/v1/responses", &accepted).await?,
                200
            );
            assert_eq!(response_mock.single_request().body_json(), accepted);

            assert_eq!(
                send_request(&server, "POST", "/v1/responses", &accepted).await?,
                404
            );
            assert_eq!(response_mock.single_request().body_json(), accepted);
        }
        Ok::<(), anyhow::Error>(())
    })
    .await
    .context("matched response helper regression exceeded two seconds")?
}
