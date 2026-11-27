//! Binds owner-configured OAuth origins to one resource's selected HTTP client.

use std::future::Future;
use std::sync::Arc;
use std::sync::Mutex;
use std::task::Poll;

use anyhow::Context;
use anyhow::Result;
use codex_exec_server::ExecServerError;
use codex_exec_server::HttpClient;
use codex_exec_server::HttpRequestParams;
use codex_exec_server::HttpRequestResponse;
use codex_exec_server::HttpRequestRestrictedParams;
use codex_exec_server::HttpResponseBodyStream;
use codex_protocol::OAuthAuthorizationOrigins;
use futures::future::BoxFuture;
use tokio_util::sync::CancellationToken;

/// One-way retirement fence shared by every wrapper for one MCP connection.
///
/// The gate serializes revocation with polling a restricted request. Cancelling
/// a token alone is not used as the dispatch fence: a future created earlier
/// must also be unable to begin HTTP I/O after `revoke` returns.
#[derive(Clone, Default)]
pub struct OAuthAuthorizationRevocation {
    gate: Arc<Mutex<()>>,
    cancelled: CancellationToken,
}

impl OAuthAuthorizationRevocation {
    /// Ends this captured authorization context permanently.
    pub fn revoke(&self) {
        let _guard = self
            .gate
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        self.cancelled.cancel();
    }
}

fn authorization_revoked() -> ExecServerError {
    ExecServerError::HttpRequest("owner-configured OAuth authorization was revoked".to_string())
}

/// Attaches explicit owner grants without changing the configured resource identity.
///
/// Call this only at the configuration boundary, before discovery or requests.
/// Empty grants preserve the original client. Every operation other than the
/// restricted OAuth capability delegates without changing its transport contract.
pub fn with_oauth_authorization_origins(
    client: Arc<dyn HttpClient>,
    resource_url: &str,
    authorization_origins: OAuthAuthorizationOrigins,
) -> Result<Arc<dyn HttpClient>> {
    with_revocable_oauth_authorization_origins(
        client,
        resource_url,
        authorization_origins,
        OAuthAuthorizationRevocation::default(),
    )
}

/// Binds the same owner grants to an explicit, irreversible connection lifetime.
pub fn with_revocable_oauth_authorization_origins(
    client: Arc<dyn HttpClient>,
    resource_url: &str,
    authorization_origins: OAuthAuthorizationOrigins,
    revocation: OAuthAuthorizationRevocation,
) -> Result<Arc<dyn HttpClient>> {
    if authorization_origins.is_empty() {
        return Ok(client);
    }
    let policy = codex_http_client::HttpAddressPolicy::from_configured_resource(resource_url)
        .context("invalid configured OAuth resource URL")?;
    let origin = policy.configured_resource_origin().to_string();
    if authorization_origins.as_slice().contains(&origin) {
        anyhow::bail!("an OAuth authorization origin duplicates the configured resource origin");
    }
    Ok(Arc::new(OwnerAuthorizedOAuthHttpClient {
        inner: client,
        resource_origin: origin,
        authorization_origins,
        revocation,
    }))
}

struct OwnerAuthorizedOAuthHttpClient {
    inner: Arc<dyn HttpClient>,
    resource_origin: String,
    authorization_origins: OAuthAuthorizationOrigins,
    revocation: OAuthAuthorizationRevocation,
}

impl HttpClient for OwnerAuthorizedOAuthHttpClient {
    fn restricted_request_cancellation(&self) -> Option<CancellationToken> {
        Some(self.revocation.cancelled.clone())
    }

    fn http_request_stream_restricted(
        &self,
        mut params: HttpRequestRestrictedParams,
    ) -> BoxFuture<'_, Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>> {
        if params.configured_resource_origin != self.resource_origin
            || !params.authorization_origins.is_empty()
        {
            return Box::pin(async {
                Err(ExecServerError::HttpRequest(
                    "OAuth request does not match its owner-bound address capability".to_string(),
                ))
            });
        }
        params.authorization_origins = self.authorization_origins.clone();
        Box::pin(async move {
            let mut cancellation = Box::pin(self.revocation.cancelled.cancelled());
            let mut request = Some(params);
            let mut operation: Option<
                BoxFuture<
                    '_,
                    Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>,
                >,
            > = None;
            futures::future::poll_fn(move |context| {
                let _guard = match self.revocation.gate.lock() {
                    Ok(guard) => guard,
                    Err(_) => return Poll::Ready(Err(authorization_revoked())),
                };
                if cancellation.as_mut().poll(context).is_ready() {
                    // Dropping the original future invokes its existing local
                    // cancellation or original-connection RPC cleanup.
                    drop(operation.take());
                    return Poll::Ready(Err(authorization_revoked()));
                }
                if operation.is_none() {
                    let Some(params) = request.take() else {
                        return Poll::Ready(Err(authorization_revoked()));
                    };
                    operation = Some(self.inner.http_request_stream_restricted(params));
                }
                match operation.as_mut() {
                    Some(operation) => operation.as_mut().poll(context),
                    None => Poll::Ready(Err(authorization_revoked())),
                }
            })
            .await
        })
    }

    fn supports_single_attempt_requests(&self) -> bool {
        self.inner.supports_single_attempt_requests()
    }

    fn http_request_stream_once(
        &self,
        params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>> {
        self.inner.http_request_stream_once(params)
    }

    fn http_request(
        &self,
        params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<HttpRequestResponse, ExecServerError>> {
        self.inner.http_request(params)
    }

    fn http_request_stream(
        &self,
        params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>> {
        self.inner.http_request_stream(params)
    }
}

#[cfg(test)]
#[path = "oauth_authorization_http_client_tests.rs"]
mod tests;
