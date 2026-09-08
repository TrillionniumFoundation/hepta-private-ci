//! Narrow TLS backend fallback for delegated requests that select their route per destination.
//!
//! Native TLS remains the default. A recognized connection-time protocol negotiation failure can
//! select rustls for one HTTPS origin and outbound route without changing other destinations.

use std::collections::HashMap;
use std::collections::HashSet;
use std::error::Error;
use std::sync::Arc;
use std::sync::Mutex;

use crate::HttpClient;
use crate::OutboundProxyRoute;

const MAX_CACHED_RUSTLS_DESTINATIONS: usize = 16;
// Schannel maps TLS alert 70 (protocol_version) to SEC_E_UNSUPPORTED_FUNCTION.
const SCHANNEL_PROTOCOL_VERSION_ERROR: i32 = 0x8009_0302_u32 as i32;

#[derive(Clone, Default)]
pub(crate) struct RustlsClientCache {
    state: Arc<Mutex<RustlsClientCacheState>>,
}

#[derive(Default)]
struct RustlsClientCacheState {
    destinations: HashSet<DestinationRoute>,
    clients: HashMap<OutboundProxyRoute, HttpClient>,
}

#[derive(Clone, Hash, PartialEq, Eq)]
struct DestinationRoute {
    host: String,
    port: u16,
    route: OutboundProxyRoute,
}

impl RustlsClientCache {
    pub(crate) fn requires_rustls(&self, url: &reqwest::Url, route: &OutboundProxyRoute) -> bool {
        let Some(destination) = DestinationRoute::new(url, route) else {
            return false;
        };
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .destinations
            .contains(&destination)
    }

    pub(crate) fn client_for_route(&self, route: &OutboundProxyRoute) -> Option<HttpClient> {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clients
            .get(route)
            .cloned()
    }

    pub(crate) fn remember(
        &self,
        url: &reqwest::Url,
        route: &OutboundProxyRoute,
        client: HttpClient,
    ) {
        let Some(destination) = DestinationRoute::new(url, route) else {
            return;
        };
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if state.destinations.contains(&destination) {
            return;
        }
        if state.destinations.len() >= MAX_CACHED_RUSTLS_DESTINATIONS
            && let Some(destination_to_evict) = state.destinations.iter().next().cloned()
        {
            state.destinations.remove(&destination_to_evict);
            if !state
                .destinations
                .iter()
                .any(|destination| destination.route == destination_to_evict.route)
            {
                state.clients.remove(&destination_to_evict.route);
            }
        }
        state.clients.entry(route.clone()).or_insert(client);
        state.destinations.insert(destination);
    }
}

impl DestinationRoute {
    fn new(url: &reqwest::Url, route: &OutboundProxyRoute) -> Option<Self> {
        if url.scheme() != "https" {
            return None;
        }
        Some(Self {
            host: url.host_str()?.to_ascii_lowercase(),
            port: url.port_or_known_default()?,
            route: route.clone(),
        })
    }
}

const MAX_ERROR_CHAIN_DEPTH: usize = 32;

pub(crate) fn should_retry_with_rustls(error: &reqwest::Error) -> bool {
    error.is_connect() && !error.is_timeout() && error.source().is_some_and(has_retryable_tls_error)
}

pub(crate) fn has_tls_error(error: &(dyn Error + 'static)) -> bool {
    let mut has_tls_error = false;
    walk_error_chain(error, 0, &mut |error| {
        has_tls_error |= error.is::<rustls::Error>() || error.is::<native_tls::Error>();
    });
    has_tls_error
}

fn has_retryable_tls_error(error: &(dyn Error + 'static)) -> bool {
    let mut recognized_negotiation_failure = false;
    let mut certificate_failure = false;

    walk_error_chain(error, 0, &mut |error| {
        let mut message = error.to_string().to_ascii_lowercase();
        if error.is::<rustls::Error>() {
            message.push(' ');
            message.push_str(&format!("{error:?}").to_ascii_lowercase());
        }

        if [
            "certificate",
            "unknown issuer",
            "unknownissuer",
            "unknown ca",
            "unknownca",
            "untrusted",
            "self signed",
            "self-signed",
            "hostname",
            "notvalidforname",
            "expired",
            "revoked",
        ]
        .iter()
        .any(|marker| message.contains(marker))
        {
            certificate_failure = true;
        }

        // macOS Secure Transport reports the protocol alert as "bad protocol version".
        let is_macos_protocol_version_error = message.contains("bad protocol version");
        // Linux OpenSSL reports the peer's "tlsv1 alert protocol version".
        let is_linux_protocol_version_error = message.contains("tlsv1 alert protocol version");
        // rustls retains the protocol alert as a structured error nested inside io::Error.
        let is_rustls_protocol_version_error = error.is::<rustls::Error>()
            && (message.contains("alertreceived(protocolversion)")
                || message.contains("received fatal alert: protocolversion"));
        // Windows Schannel may expose the protocol alert as a raw or formatted OS error.
        let is_schannel_protocol_version_error = error
            .downcast_ref::<std::io::Error>()
            .and_then(std::io::Error::raw_os_error)
            == Some(SCHANNEL_PROTOCOL_VERSION_ERROR)
            || message.contains("(os error -2146893054)")
            || message.contains("0x80090302");
        if is_macos_protocol_version_error
            || is_linux_protocol_version_error
            || is_rustls_protocol_version_error
            || is_schannel_protocol_version_error
        {
            recognized_negotiation_failure = true;
        }
    });

    recognized_negotiation_failure && !certificate_failure
}

fn walk_error_chain(
    error: &(dyn Error + 'static),
    depth: usize,
    visitor: &mut impl FnMut(&(dyn Error + 'static)),
) {
    if depth >= MAX_ERROR_CHAIN_DEPTH {
        return;
    }

    visitor(error);

    // std::io::Error stores custom errors behind get_ref(); on current Rust versions that
    // inner value is not guaranteed to be exposed by Error::source(). Walk it explicitly
    // so rustls certificate and protocol alerts remain classifiable through hyper/reqwest.
    if let Some(io_error) = error.downcast_ref::<std::io::Error>()
        && let Some(inner) = io_error.get_ref()
    {
        walk_error_chain(inner, depth + 1, visitor);
        return;
    }

    if let Some(source) = error.source() {
        walk_error_chain(source, depth + 1, visitor);
    }
}

#[cfg(test)]
#[path = "tls_backend_fallback_tests.rs"]
mod tests;
