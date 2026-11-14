use crate::config::NetworkMode;
use crate::mitm::MitmState;
use crate::state::NetworkProxyState;
use rama_core::error::extra::OpaqueError;
use rama_core::extensions::Extension;
use rama_core::extensions::ExtensionsRef;
use rama_http::Request;
use rama_net::AuthorityInputExt;
use rama_net::Protocol;
use rama_net::ProtocolInputExt;
use rama_net::address::Host;
use rama_net::address::HostWithOptPort;
use rama_net::address::HostWithPort;
use rama_net::uri::Uri;
use std::borrow::Cow;

impl Extension for NetworkProxyState {}
impl Extension for MitmState {}
impl Extension for NetworkMode {}

/// The destination accepted by policy before a CONNECT or SOCKS tunnel is upgraded.
#[derive(Clone, Debug)]
pub(crate) struct TunnelTarget(pub(crate) HostWithPort);

impl Extension for TunnelTarget {}

/// The routing authority used for policy and Host-header validation.
pub(crate) struct RequestTarget {
    pub(crate) authority: HostWithOptPort,
    pub(crate) protocol: Protocol,
}

impl<Body> TryFrom<&Request<Body>> for RequestTarget {
    type Error = OpaqueError;

    fn try_from(request: &Request<Body>) -> Result<Self, Self::Error> {
        let protocol = request.protocol().cloned().unwrap_or(Protocol::HTTP);
        // CONNECT supplies a checked domain before TLS is terminated. Preserve its priority
        // over SNI/Host for origin-form requests, as in the previous Rama request context.
        let tunnel_authority = request
            .uri()
            .host()
            .is_none()
            .then(|| {
                request
                    .extensions()
                    .get_ref::<TunnelTarget>()
                    .and_then(|target| {
                        matches!(target.0.host, Host::Name(_)).then(|| target.0.clone().into())
                    })
            })
            .flatten();
        let authority = tunnel_authority
            .or_else(|| request.authority())
            .ok_or_else(|| OpaqueError::from_static_str("request authority is missing"))?;
        Ok(Self {
            authority,
            protocol,
        })
    }
}

impl RequestTarget {
    pub(crate) fn host_with_port(&self) -> HostWithPort {
        self.authority
            .clone()
            .into_host_with_port_or(self.protocol.default_port().unwrap_or(80))
    }

    pub(crate) fn authority_has_default_port(&self) -> bool {
        self.protocol.default_port() == self.authority.port_u16()
    }
}

/// Preserve the parsed path's bytes for authorization without percent-decoding
/// or re-encoding it. Rama's path presentation now escapes literal brackets.
pub(crate) fn request_path(uri: &Uri) -> Cow<'_, str> {
    let has_scheme = uri.scheme().is_some();
    let has_authority = uri.authority().is_some();
    match uri.as_str() {
        Cow::Borrowed(source) => Cow::Borrowed(raw_request_path(source, has_scheme, has_authority)),
        Cow::Owned(source) => {
            Cow::Owned(raw_request_path(&source, has_scheme, has_authority).to_owned())
        }
    }
}

fn raw_request_path(source: &str, has_scheme: bool, has_authority: bool) -> &str {
    if source == "*" {
        return source;
    }
    let source = if has_scheme {
        source.split_once(':').map_or(source, |(_, rest)| rest)
    } else {
        source
    };
    let path = if has_authority {
        let authority = source.strip_prefix("//").unwrap_or(source);
        authority
            .find(['/', '?', '#'])
            .map_or("", |start| &authority[start..])
    } else {
        source
    };
    let path = path.split(['?', '#']).next().unwrap_or_default();
    if path.is_empty() { "/" } else { path }
}

#[cfg(test)]
#[path = "rama_ext_tests.rs"]
mod tests;
