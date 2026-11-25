//! Freeze the same factory's proxy decision before constructing a guarded client.

use hyper_util::client::proxy::matcher::Matcher;
use reqwest::Url;

use crate::BuildRouteAwareHttpClientError;
use crate::ClientRouteClass;
use crate::HttpAddressPolicyError;
use crate::HttpClientFactory;
use crate::OutboundProxyRoute;
use crate::RouteAwareClientPoolError;
use crate::RouteAwareRequestError;

impl HttpClientFactory {
    pub(crate) async fn build_restricted_reqwest_client(
        &self,
        builder: reqwest::ClientBuilder,
        destination: &Url,
        route_class: ClientRouteClass,
    ) -> Result<(reqwest::Client, OutboundProxyRoute), RouteAwareRequestError> {
        let route = self
            .resolve_proxy_route_async(destination.to_string())
            .await
            .map_err(RouteAwareClientPoolError::Resolve)?;
        require_direct_route(&route, destination, route_class)?;
        // Only a proved direct decision reaches no_proxy. It freezes that exact
        // decision instead of letting a new client rediscover ambient proxies.
        let client = self
            .build_reqwest_client_for_resolved_route(
                builder,
                route_class,
                &OutboundProxyRoute::Direct,
            )
            .map_err(RouteAwareClientPoolError::from)?;
        Ok((client, route))
    }
}

fn require_direct_route(
    route: &OutboundProxyRoute,
    destination: &Url,
    route_class: ClientRouteClass,
) -> Result<(), RouteAwareRequestError> {
    if !matches!(destination.scheme(), "http" | "https") || destination.host().is_none() {
        return Err(HttpAddressPolicyError::InvalidDestination.into());
    }
    let uri = destination
        .as_str()
        .parse::<http::Uri>()
        .map_err(|_| HttpAddressPolicyError::InvalidDestination)?;
    let matcher = match route {
        OutboundProxyRoute::Direct => return Ok(()),
        // This is the very matcher used by reqwest 0.12.28, with the same
        // system-proxy feature. It includes CGI and NO_PROXY behavior.
        OutboundProxyRoute::TransportDefault => Matcher::from_system(),
        OutboundProxyRoute::Proxy { url, no_proxy } => {
            reqwest::Proxy::all(url).map_err(|_| {
                RouteAwareClientPoolError::Build(
                    BuildRouteAwareHttpClientError::InvalidProxyConfig { route_class },
                )
            })?;
            // Reqwest first canonicalizes proxy URLs. A raw Unicode/relative
            // URL fed straight to Matcher can parse as no proxy. Support only
            // its provably equivalent absolute HTTP(S) subset here.
            let canonical =
                Url::parse(url).map_err(|_| HttpAddressPolicyError::ProxyUnsupported)?;
            if !matches!(canonical.scheme(), "http" | "https") || canonical.host().is_none() {
                return Err(HttpAddressPolicyError::ProxyUnsupported.into());
            }
            if Matcher::builder()
                .all(canonical.as_str())
                .build()
                .intercept(&uri)
                .is_none()
            {
                return Err(HttpAddressPolicyError::ProxyUnsupported.into());
            }
            Matcher::builder()
                .all(canonical.as_str())
                .no(no_proxy.as_deref().unwrap_or(""))
                .build()
        }
    };
    if matcher.intercept(&uri).is_some() {
        return Err(HttpAddressPolicyError::ProxyUnsupported.into());
    }
    Ok(())
}

#[cfg(test)]
#[path = "restricted_proxy_tests.rs"]
mod tests;
