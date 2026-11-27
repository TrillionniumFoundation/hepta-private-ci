use codex_api::AuthProvider;
use http::HeaderMap;

/// The non-HTTP auth interface supplies header-only authentication. Capture all
/// of it once so connection identity and the actual handshake use equal values.
/// Host headers, including attestation, are still generated only on reconnect.
pub(super) struct WebsocketAuthSnapshot {
    headers: HeaderMap,
}

impl WebsocketAuthSnapshot {
    pub(super) fn capture(auth: &dyn AuthProvider) -> Self {
        Self {
            headers: auth.to_auth_headers(),
        }
    }

    pub(super) fn headers(&self) -> &HeaderMap {
        &self.headers
    }
}

impl AuthProvider for WebsocketAuthSnapshot {
    fn add_auth_headers(&self, headers: &mut HeaderMap) {
        headers.extend(self.headers.clone());
    }
}

impl std::fmt::Debug for WebsocketAuthSnapshot {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("WebsocketAuthSnapshot")
            .field("header_count", &self.headers.len())
            .finish()
    }
}
