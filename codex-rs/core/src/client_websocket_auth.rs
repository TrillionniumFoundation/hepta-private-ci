use http::HeaderMap;
use http::header::AUTHORIZATION;

/// A comparison-only binding. Secret material stays in memory and is redacted by Debug.
#[derive(Clone, Eq, PartialEq)]
pub(super) struct WebsocketAuthIdentity {
    headers: HeaderMap,
    authorization_identity: Option<Vec<u8>>,
}

impl std::fmt::Debug for WebsocketAuthIdentity {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("WebsocketAuthIdentity([redacted])")
    }
}

/// Owns exactly the auth headers used for one connection's upgrade.
pub(super) struct WebsocketAuthSnapshot {
    pub(super) headers: HeaderMap,
    pub(super) identity: WebsocketAuthIdentity,
}

impl WebsocketAuthSnapshot {
    pub(super) fn new(headers: HeaderMap, authorization_identity: Option<Vec<u8>>) -> Self {
        let mut identity_headers = headers.clone();
        if authorization_identity.is_some() {
            // Only a provider-supplied credential binding can replace the
            // volatile Authorization proof. Account and custom security
            // headers still participate in exact equality.
            identity_headers.remove(AUTHORIZATION);
        }
        Self {
            headers,
            identity: WebsocketAuthIdentity {
                headers: identity_headers,
                authorization_identity,
            },
        }
    }
}

#[cfg(test)]
#[path = "client_websocket_auth_tests.rs"]
mod tests;
