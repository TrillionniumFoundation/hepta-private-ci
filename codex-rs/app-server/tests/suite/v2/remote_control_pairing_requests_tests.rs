use super::super::DEFAULT_TIMEOUT;
use super::super::HttpRequest;
use super::super::read_http_request;
use super::PairingRequestReader;
use super::WEBSOCKET_REQUEST;
use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use pretty_assertions::assert_eq;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio::net::TcpStream;
use tokio::time::timeout;

const PAIR_REQUEST: &str = "POST /backend-api/wham/remote/control/server/pair HTTP/1.1";
const STATUS_REQUEST: &str = "POST /backend-api/wham/remote/control/server/pair/status HTTP/1.1";

#[tokio::test]
async fn late_and_reconnecting_websockets_preserve_pairing_request_order() -> Result<()> {
    timeout(DEFAULT_TIMEOUT, async {
        let pair_body = r#"{"manual_code":true}"#;
        let code_body = r#"{"pairing_code":"pairing-code"}"#;
        let manual_body = r#"{"manual_pairing_code":"ABCD-EFGH"}"#;
        let mut requests = PairingRequestReader::default();
        let mut clients = Vec::new();
        let mut observed = Vec::new();
        let mut latest_websocket_peer = None;
        for (request_line, body) in [
            (PAIR_REQUEST, pair_body),
            (WEBSOCKET_REQUEST, ""),
            (STATUS_REQUEST, code_body),
            (WEBSOCKET_REQUEST, ""),
            (STATUS_REQUEST, manual_body),
        ] {
            let (request, client) = parsed_request(request_line, body).await?;
            if request_line == WEBSOCKET_REQUEST {
                latest_websocket_peer = Some(client.local_addr()?);
            }
            clients.push(client);
            if let Some(request) = requests.route(request)? {
                observed.push((request.request_line, request.body));
            }
        }
        assert_eq!(
            observed,
            vec![
                (PAIR_REQUEST.to_string(), pair_body.to_string()),
                (STATUS_REQUEST.to_string(), code_body.to_string()),
                (STATUS_REQUEST.to_string(), manual_body.to_string()),
            ]
        );
        let pending = requests
            .background_websocket
            .as_ref()
            .context("the latest background WebSocket should remain pending")?;
        assert_eq!(pending.request_line, WEBSOCKET_REQUEST);
        assert_eq!(pending.body, "");
        assert_eq!(
            Some(pending.reader.get_ref().peer_addr()?),
            latest_websocket_peer
        );
        drop(clients);
        Ok::<(), anyhow::Error>(())
    })
    .await?
}

#[tokio::test]
async fn other_methods_and_paths_remain_visible_to_pairing_assertions() -> Result<()> {
    timeout(DEFAULT_TIMEOUT, async {
        let mut requests = PairingRequestReader::default();
        for request_line in [
            "GET /backend-api/wham/remote/control/server/pair HTTP/1.1",
            "POST /backend-api/wham/remote/control/server HTTP/1.1",
            "GET /backend-api/wham/remote/control/server?unexpected=1 HTTP/1.1",
        ] {
            let (request, _client) = parsed_request(request_line, "unexpected body").await?;
            let observed = requests
                .route(request)?
                .context("an unrelated request must reach the strict pairing assertions")?;
            assert_eq!(
                (observed.request_line, observed.body),
                (request_line.to_string(), "unexpected body".to_string())
            );
        }
        assert!(requests.background_websocket.is_none());
        Ok::<(), anyhow::Error>(())
    })
    .await?
}

#[tokio::test]
async fn websocket_upgrade_with_a_body_is_rejected() -> Result<()> {
    timeout(DEFAULT_TIMEOUT, async {
        let mut requests = PairingRequestReader::default();
        let (request, _client) = parsed_request(WEBSOCKET_REQUEST, "unexpected body").await?;
        match requests.route(request) {
            Err(error) => assert_eq!(
                error.to_string(),
                "background WebSocket upgrade request must have an empty body"
            ),
            Ok(_) => bail!("a WebSocket upgrade with a body must not be ignored"),
        }
        assert!(requests.background_websocket.is_none());
        Ok::<(), anyhow::Error>(())
    })
    .await?
}

async fn parsed_request(request_line: &str, body: &str) -> Result<(HttpRequest, TcpStream)> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let mut client = TcpStream::connect(listener.local_addr()?).await?;
    client
        .write_all(
            format!(
                "{request_line}\r\nContent-Length: {}\r\n\r\n{body}",
                body.len()
            )
            .as_bytes(),
        )
        .await?;
    let request = read_http_request(&listener).await?;
    Ok((request, client))
}
