//! Real loopback HTTP fixture; no installed auth, proxy or external provider.

use super::super::*;
use codex_api::AuthProvider;
use codex_api::Provider;
use codex_api::RetryConfig;
use codex_http_client::HttpClientBuilder;
use http::HeaderMap;
use http::HeaderValue;
use std::sync::Arc;
use std::sync::Mutex;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio::net::TcpStream;
use tokio::task::JoinHandle;

pub(super) const URL_SECRET: &str = "URL_SECRET_SENTINEL";
pub(super) const AUTH_SECRET: &str = "Bearer AUTH_SECRET_SENTINEL";
pub(super) const BODY_SECRET: &str = "BODY_SECRET_SENTINEL";
pub(super) const HEADER_SECRET: &str = "HEADER_SECRET_SENTINEL";

struct FixtureAuth;

impl AuthProvider for FixtureAuth {
    fn add_auth_headers(&self, headers: &mut HeaderMap) {
        headers.insert("authorization", HeaderValue::from_static(AUTH_SECRET));
    }
}

pub(super) struct Server {
    pub client: ManagedResponsesClient,
    pub requests: Arc<Mutex<Vec<bool>>>,
    stop: CancellationToken,
    task: JoinHandle<()>,
}

impl Server {
    pub async fn start(status: u16, body: String, content_type: &'static str) -> Self {
        let listener = TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, 0))
            .await
            .expect("owned loopback listener");
        let address = listener.local_addr().expect("loopback address");
        let base_url = format!("http://{address}/{URL_SECRET}");
        let provider = Provider {
            name: "controlled diagnostic fixture".into(),
            base_url,
            query_params: None,
            headers: HeaderMap::new(),
            retry: RetryConfig {
                max_attempts: 3,
                base_delay: Duration::from_millis(1),
                retry_429: true,
                retry_5xx: true,
                retry_transport: true,
            },
            stream_idle_timeout: Duration::from_secs(2),
        };
        let endpoint = provider.url_for_path("responses");
        // The documented direct-route exception is limited to this hermetic
        // loopback fixture; production still uses the installed route owner.
        let http = HttpClientBuilder::new()
            .without_request_logging()
            .without_redirects()
            .build_direct()
            .expect("loopback HTTP client");
        let client = ManagedResponsesClient {
            client: ResponsesClient::new(
                ReqwestTransport::from_http_client(http),
                provider,
                Arc::new(FixtureAuth),
            )
            .with_redacted_response_diagnostics(),
            endpoint,
        };
        let stop = CancellationToken::new();
        let stopping = stop.clone();
        let requests = Arc::new(Mutex::new(Vec::new()));
        let observed = requests.clone();
        let response = format!(
            "HTTP/1.1 {status} Fixture\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nX-Fixture-Secret: {HEADER_SECRET}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        );
        let task = tokio::spawn(async move {
            loop {
                let accepted = tokio::select! {
                    biased;
                    _ = stopping.cancelled() => break,
                    accepted = listener.accept() => accepted,
                };
                let (mut socket, _) = accepted.expect("fixture accept");
                let request =
                    tokio::time::timeout(Duration::from_secs(2), read_request(&mut socket))
                        .await
                        .expect("bounded request read");
                let request = String::from_utf8(request).expect("controlled UTF-8 request");
                observed.lock().expect("fixture request lock").push(
                    request.contains(URL_SECRET)
                        && request.contains(AUTH_SECRET)
                        && request.contains(BODY_SECRET),
                );
                socket
                    .write_all(response.as_bytes())
                    .await
                    .expect("fixture response write");
                socket.shutdown().await.expect("fixture close");
            }
        });
        Self {
            client,
            requests,
            stop,
            task,
        }
    }

    pub fn parts(
        self,
    ) -> (
        ManagedResponsesClient,
        Arc<Mutex<Vec<bool>>>,
        CancellationToken,
        JoinHandle<()>,
    ) {
        (self.client, self.requests, self.stop, self.task)
    }
}

async fn read_request(socket: &mut TcpStream) -> Vec<u8> {
    let mut bytes = Vec::new();
    loop {
        let mut chunk = [0_u8; 4096];
        let read = socket.read(&mut chunk).await.expect("fixture read");
        assert!(read > 0, "request must arrive before peer closes");
        bytes.extend_from_slice(&chunk[..read]);
        assert!(bytes.len() <= 65_536, "fixture request bound");
        if let Some(end) = bytes.windows(4).position(|part| part == b"\r\n\r\n") {
            let headers = std::str::from_utf8(&bytes[..end]).expect("HTTP headers");
            let length = headers
                .lines()
                .find_map(|line| {
                    let (name, value) = line.split_once(':')?;
                    name.eq_ignore_ascii_case("content-length")
                        .then(|| value.trim().parse::<usize>().expect("content length"))
                })
                .expect("encoded JSON request content length");
            assert!(length <= 65_536, "fixture body bound");
            if bytes.len() >= end + 4 + length {
                return bytes;
            }
        }
    }
}
