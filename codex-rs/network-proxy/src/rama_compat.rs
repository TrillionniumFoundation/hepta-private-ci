use crate::config::NetworkMode;
use crate::mitm::MitmState;
use crate::runtime::NetworkProxyState;
use rama_core::error::BoxError;
use rama_core::error::BoxErrorExt as _;
use rama_core::extensions::Extension;
use rama_http::Request;
use rama_net::AuthorityInputExt;
use rama_net::Protocol;
use rama_net::ProtocolInputExt;
use rama_net::address::HostWithOptPort;
use rama_net::address::HostWithPort;

impl Extension for NetworkProxyState {}
impl Extension for MitmState {}
impl Extension for NetworkMode {}

/// Resolves an HTTP routing target without applying transport proxy overrides.
pub(crate) struct RequestContext {
    pub(crate) protocol: Protocol,
    pub(crate) authority: HostWithOptPort,
}

impl<B> TryFrom<&Request<B>> for RequestContext {
    type Error = BoxError;

    fn try_from(request: &Request<B>) -> Result<Self, Self::Error> {
        let authority = request
            .authority()
            .ok_or_else(|| BoxError::from_static_str("HTTP request is missing an authority"))?;
        let protocol = request.protocol().cloned().unwrap_or(Protocol::HTTP);
        Ok(Self {
            protocol,
            authority,
        })
    }
}

impl RequestContext {
    pub(crate) fn host_with_port(&self) -> HostWithPort {
        self.authority.clone().into_host_with_port_or(
            self.protocol
                .default_port()
                .unwrap_or(Protocol::HTTP_DEFAULT_PORT),
        )
    }

    pub(crate) fn authority_has_default_port(&self) -> bool {
        self.protocol.default_port() == self.authority.port.as_u16()
    }
}
