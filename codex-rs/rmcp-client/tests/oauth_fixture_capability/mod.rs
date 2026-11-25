//! Protocol fixtures model external OAuth servers on separate loopback ports.
//! This test-only capability admits only endpoints explicitly registered by the
//! individual fixture. It keeps real mock HTTP traffic and old protocol checks;
//! it provides no evidence of production destination-policy enforcement.
#![cfg(test)]

use std::collections::BTreeSet;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_exec_server::ExecServerError;
use codex_exec_server::HttpClient;
use codex_exec_server::HttpRedirectPolicy;
use codex_exec_server::HttpRequestParams;
use codex_exec_server::HttpRequestResponse;
use codex_exec_server::HttpRequestRestrictedParams;
use codex_exec_server::HttpResponseBodyStream;
use codex_exec_server::RouteAwareHttpClient;
use codex_http_client::HttpClientFactory;
use codex_http_client::OutboundProxyPolicy;
use futures::future::BoxFuture;
use pretty_assertions::assert_eq;
use url::Url;

const MAX_FIXTURE_ENDPOINTS: usize = 64;
const MAX_REDIRECTS: usize = 10;
const MAX_BUFFERED_FIXTURE_BODY: usize = 1024 * 1024;

struct FixtureHttpClient {
    resource_origin: String,
    endpoints: BTreeSet<(String, String)>,
    inner: RouteAwareHttpClient,
}

#[derive(Clone, Copy)]
enum FixtureAccess {
    Ordinary,
    ConfiguredResource,
}

fn fixture_url(value: &str) -> Url {
    let url = Url::parse(value).expect("fixture URL");
    assert_eq!(url.scheme(), "http");
    assert!(url.username().is_empty() && url.password().is_none());
    assert!(url.fragment().is_none());
    assert!(
        matches!(url.host(), Some(url::Host::Ipv4(ip)) if ip.is_loopback())
            || matches!(url.host(), Some(url::Host::Ipv6(ip)) if ip.is_loopback())
    );
    assert!(url.port_or_known_default().is_some_and(|port| port != 0));
    url
}

pub(crate) fn fixture_http_client(
    resource_url: &str,
    endpoints: &[(&str, String)],
) -> Arc<dyn HttpClient> {
    assert!(!endpoints.is_empty() && endpoints.len() <= MAX_FIXTURE_ENDPOINTS);
    let resource_origin = fixture_url(resource_url).origin().ascii_serialization();
    let endpoints = endpoints
        .iter()
        .map(|(method, url)| {
            let method = http::Method::from_bytes(method.as_bytes()).expect("fixture method");
            (method.as_str().to_string(), fixture_url(url).to_string())
        })
        .collect();
    Arc::new(FixtureHttpClient {
        resource_origin,
        endpoints,
        inner: RouteAwareHttpClient::new(HttpClientFactory::new(
            OutboundProxyPolicy::ReqwestDefault,
        )),
    })
}

impl FixtureHttpClient {
    async fn execute_stream(
        &self,
        mut params: HttpRequestParams,
        access: FixtureAccess,
    ) -> Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError> {
        let follow = params.redirect_policy == HttpRedirectPolicy::Follow;
        let deadline = params
            .timeout_ms
            .map(|value| Instant::now() + Duration::from_millis(value));
        params.redirect_policy = HttpRedirectPolicy::Stop;
        params.stream_response = true;
        let mut redirects = 0;
        loop {
            let current = Url::parse(&params.url)
                .map_err(|error| ExecServerError::HttpRequest(error.to_string()))?;
            if !self
                .endpoints
                .contains(&(params.method.clone(), current.to_string()))
            {
                return Err(ExecServerError::HttpRequest(
                    "OAuth fixture endpoint was not registered".to_string(),
                ));
            }
            if let Some(deadline) = deadline {
                let remaining = deadline
                    .checked_duration_since(Instant::now())
                    .filter(|value| !value.is_zero())
                    .ok_or_else(|| {
                        ExecServerError::HttpRequest("OAuth fixture request timed out".to_string())
                    })?;
                params.timeout_ms = Some(
                    u64::try_from(remaining.as_millis())
                        .unwrap_or(u64::MAX)
                        .max(1),
                );
            }
            // Keep real enforcement for the configured resource. Only explicitly
            // registered external fixture endpoints substitute the capability.
            // Both branches use the original factory with automatic redirects off.
            let (response, body) = match access {
                FixtureAccess::ConfiguredResource
                    if current.origin().ascii_serialization() == self.resource_origin =>
                {
                    self.inner
                        .http_request_stream_restricted(HttpRequestRestrictedParams {
                            request: params.clone(),
                            configured_resource_origin: self.resource_origin.clone(),
                        })
                        .await?
                }
                FixtureAccess::ConfiguredResource | FixtureAccess::Ordinary => {
                    self.inner.http_request_stream(params.clone()).await?
                }
            };
            if !follow || !matches!(response.status, 301 | 302 | 303 | 307 | 308) {
                return Ok((response, body));
            }
            let Some(location) = response
                .headers
                .iter()
                .find(|header| header.name.eq_ignore_ascii_case("location"))
            else {
                return Ok((response, body));
            };
            if redirects == MAX_REDIRECTS {
                return Err(ExecServerError::HttpRequest(
                    "OAuth fixture redirect limit exceeded".to_string(),
                ));
            }
            let next = current
                .join(&location.value)
                .map_err(|error| ExecServerError::HttpRequest(error.to_string()))?;
            let drop_body = matches!(response.status, 301 | 302)
                && params.method.eq_ignore_ascii_case("POST")
                || response.status == 303;
            if drop_body {
                if !params.method.eq_ignore_ascii_case("HEAD") {
                    params.method = "GET".to_string();
                }
                params.body = None;
                params.headers.retain(|header| {
                    ![
                        "content-type",
                        "content-length",
                        "content-encoding",
                        "transfer-encoding",
                    ]
                    .iter()
                    .any(|name| header.name.eq_ignore_ascii_case(name))
                });
            }
            if current.origin() != next.origin() {
                params.headers.retain(|header| {
                    ![
                        "authorization",
                        "cookie",
                        "cookie2",
                        "proxy-authorization",
                        "www-authenticate",
                        "referer",
                    ]
                    .iter()
                    .any(|name| header.name.eq_ignore_ascii_case(name))
                });
            }
            drop(body);
            params.url = next.to_string();
            redirects += 1;
        }
    }
}

impl HttpClient for FixtureHttpClient {
    fn http_request_stream_restricted(
        &self,
        params: HttpRequestRestrictedParams,
    ) -> BoxFuture<'_, Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>> {
        Box::pin(async move {
            if params.configured_resource_origin != self.resource_origin {
                return Err(ExecServerError::HttpRequest(
                    "OAuth fixture resource capability changed".to_string(),
                ));
            }
            self.execute_stream(params.request, FixtureAccess::ConfiguredResource)
                .await
        })
    }

    fn http_request_stream(
        &self,
        params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>> {
        Box::pin(self.execute_stream(params, FixtureAccess::Ordinary))
    }

    fn http_request(
        &self,
        params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<HttpRequestResponse, ExecServerError>> {
        Box::pin(async move {
            let (mut response, mut body) =
                self.execute_stream(params, FixtureAccess::Ordinary).await?;
            let mut bytes = Vec::new();
            while let Some(chunk) = body.recv().await? {
                if chunk.len() > MAX_BUFFERED_FIXTURE_BODY - bytes.len() {
                    return Err(ExecServerError::HttpRequest(
                        "OAuth fixture body exceeded its bound".to_string(),
                    ));
                }
                bytes.extend_from_slice(&chunk);
            }
            response.body = bytes.into();
            Ok(response)
        })
    }
}
