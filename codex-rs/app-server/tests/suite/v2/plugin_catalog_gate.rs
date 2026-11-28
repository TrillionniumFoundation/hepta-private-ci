//! A local response gate for the catalog cache integration fixture.
//!
//! Wiremock still checks the original method, query and authentication headers.
//! Only one selected response is withheld; other fixture requests keep running.

use super::DEFAULT_TIMEOUT;
use anyhow::Context;
use anyhow::Result;
use axum::Router;
use axum::extract::State;
use axum::http::HeaderMap;
use axum::http::Method;
use axum::http::StatusCode;
use axum::http::Uri;
use axum::http::header;
use axum::response::IntoResponse;
use axum::response::Response;
use codex_http_client::HttpClient;
use codex_http_client::HttpClientBuilder;
use std::sync::Arc;
use std::sync::Mutex;
use tokio::net::TcpListener;
use tokio::sync::oneshot;
use tokio::task::JoinHandle;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;
use wiremock::MockServer;

struct PendingResponse {
    entered: oneshot::Sender<()>,
    release: oneshot::Receiver<()>,
}

struct ProxyState {
    upstream: String,
    client: HttpClient,
    pending: Mutex<Option<PendingResponse>>,
    shutdown: CancellationToken,
}

pub(super) struct CatalogGate {
    uri: String,
    state: Arc<ProxyState>,
    task: Option<JoinHandle<std::io::Result<()>>>,
}

pub(super) struct HeldCatalogResponse {
    entered: oneshot::Receiver<()>,
    release: oneshot::Sender<()>,
}

impl CatalogGate {
    pub(super) async fn start(server: &MockServer) -> Result<Self> {
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let uri = format!("http://{}", listener.local_addr()?);
        let state = Arc::new(ProxyState {
            upstream: server.uri(),
            // This client connects only to the supplied loopback test fixture.
            client: HttpClientBuilder::new()
                .without_redirects()
                .build_direct()?,
            pending: Mutex::default(),
            shutdown: CancellationToken::new(),
        });
        let app = Router::new().fallback(proxy).with_state(Arc::clone(&state));
        let shutdown = state.shutdown.clone();
        let task = tokio::spawn(async move {
            axum::serve(listener, app)
                .with_graceful_shutdown(shutdown.cancelled_owned())
                .await
        });
        Ok(Self {
            uri,
            state,
            task: Some(task),
        })
    }

    pub(super) fn uri(&self) -> &str {
        &self.uri
    }

    pub(super) fn hold_next_global_catalog(&self) -> HeldCatalogResponse {
        let (entered_tx, entered_rx) = oneshot::channel();
        let (release_tx, release_rx) = oneshot::channel();
        let mut pending = self.state.pending.lock().expect("catalog gate lock");
        assert!(pending.is_none(), "a catalog response is already armed");
        *pending = Some(PendingResponse {
            entered: entered_tx,
            release: release_rx,
        });
        HeldCatalogResponse {
            entered: entered_rx,
            release: release_tx,
        }
    }

    pub(super) async fn shutdown(mut self) -> Result<()> {
        self.state.shutdown.cancel();
        if let Some(task) = self.task.as_mut() {
            timeout(DEFAULT_TIMEOUT, task)
                .await
                .context("catalog gate did not shut down")?
                .context("catalog gate task panicked")??;
        }
        self.task.take();
        Ok(())
    }
}

impl Drop for CatalogGate {
    fn drop(&mut self) {
        self.state.shutdown.cancel();
        if let Some(task) = self.task.take() {
            task.abort();
        }
    }
}

impl HeldCatalogResponse {
    pub(super) async fn wait_until_held(&mut self) -> Result<()> {
        (&mut self.entered)
            .await
            .context("catalog request did not reach the response gate")
    }

    pub(super) fn release(self) -> Result<()> {
        self.release
            .send(())
            .map_err(|()| anyhow::anyhow!("catalog request left before its response was released"))
    }
}

async fn proxy(
    State(state): State<Arc<ProxyState>>,
    method: Method,
    uri: Uri,
    mut headers: HeaderMap,
) -> Response {
    if method != Method::GET {
        return StatusCode::METHOD_NOT_ALLOWED.into_response();
    }
    let forward = async {
        let path = uri
            .path_and_query()
            .map_or("/", axum::http::uri::PathAndQuery::as_str);
        headers.remove(header::HOST);
        headers.remove(header::CONNECTION);
        let response = state
            .client
            .get(format!("{}{path}", state.upstream))
            .headers(headers)
            .send()
            .await?;
        let status = response.status();
        let mut response_headers = response.headers().clone();
        response_headers.remove(header::CONTENT_LENGTH);
        response_headers.remove(header::TRANSFER_ENCODING);
        response_headers.remove(header::CONNECTION);
        let body = response.bytes().await?;

        let is_global_catalog = uri.path() == "/backend-api/ps/plugins/list"
            && url::form_urlencoded::parse(uri.query().unwrap_or_default().as_bytes())
                .any(|(key, value)| key == "scope" && value == "GLOBAL");
        let pending = if is_global_catalog {
            state.pending.lock().expect("catalog gate lock").take()
        } else {
            None
        };
        if let Some(pending) = pending {
            let _ = pending.entered.send(());
            pending
                .release
                .await
                .context("held catalog response was dropped without release")?;
        }
        Ok::<_, anyhow::Error>((status, response_headers, body).into_response())
    };
    tokio::select! {
        _ = state.shutdown.cancelled() => StatusCode::SERVICE_UNAVAILABLE.into_response(),
        response = forward => match response {
            Ok(response) => response,
            Err(error) => (StatusCode::BAD_GATEWAY, error.to_string()).into_response(),
        },
    }
}

#[cfg(test)]
#[path = "plugin_catalog_gate_tests.rs"]
mod tests;
