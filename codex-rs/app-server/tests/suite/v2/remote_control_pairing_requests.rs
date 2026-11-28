use super::HttpRequest;
use super::read_http_request;
use anyhow::Result;
use anyhow::ensure;
use tokio::net::TcpListener;

const WEBSOCKET_REQUEST: &str = "GET /backend-api/wham/remote/control/server HTTP/1.1";

#[derive(Default)]
pub(super) struct PairingRequestReader {
    background_websocket: Option<HttpRequest>,
}

impl PairingRequestReader {
    pub(super) async fn next(&mut self, listener: &TcpListener) -> Result<HttpRequest> {
        loop {
            let request = read_http_request(listener).await?;
            if let Some(request) = self.route(request)? {
                return Ok(request);
            }
        }
    }

    fn route(&mut self, request: HttpRequest) -> Result<Option<HttpRequest>> {
        if request.request_line != WEBSOCKET_REQUEST {
            return Ok(Some(request));
        }
        ensure!(
            request.body.is_empty(),
            "background WebSocket upgrade request must have an empty body"
        );
        // Enrollment starts an independent controller; its first connection or
        // a reconnect can arrive between any two pairing HTTP requests. Keep
        // at most its latest pending socket, as this fixture does not complete
        // the WebSocket handshake. All other routes retain the caller's checks.
        self.background_websocket = Some(request);
        Ok(None)
    }
}

#[cfg(test)]
#[path = "remote_control_pairing_requests_tests.rs"]
mod tests;
