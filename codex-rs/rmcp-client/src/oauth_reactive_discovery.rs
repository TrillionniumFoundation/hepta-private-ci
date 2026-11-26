use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use codex_exec_server::ExecServerError;
use codex_exec_server::HttpClient;
use codex_exec_server::HttpRequestParams;
use codex_exec_server::HttpRequestResponse;
use codex_exec_server::HttpRequestRestrictedParams;
use codex_exec_server::HttpResponseBodyStream;
use futures::future::BoxFuture;
use http::HeaderMap;
use rmcp::model::ClientCapabilities;
use rmcp::model::ClientConfig;
use rmcp::model::Implementation;
use rmcp::model::ProtocolVersion;
use rmcp::service::ClientInitializeError;
use rmcp::service::ClientServiceExt;
use rmcp::service::QuitReason;
use rmcp::transport::AuthorizationManager;
use rmcp::transport::StreamableHttpClientTransport;
use rmcp::transport::auth::AuthorizationMetadataResolution;
use rmcp::transport::auth::AuthorizationMetadataSource;
use rmcp::transport::streamable_http_client::StreamableHttpClientTransportConfig;
use rmcp::transport::streamable_http_client::StreamableHttpError;
use url::Url;

use crate::http_client_adapter::StreamableHttpClientAdapter;
use crate::http_client_adapter::StreamableHttpClientAdapterError;
use crate::http_client_adapter::StreamableHttpRedirectMode;
use crate::logging_client_handler::LoggingClientHandler;
use crate::oauth_http_client::OAuthHttpClientAdapter;
use crate::protocol_mode::McpProtocolMode;

// Ordinary discovery, the reactive handshake and challenge-based metadata all
// share one five-second absolute discovery deadline. The login's own earlier
// deadline wins; entering a later phase never resets either clock.
const MAX_OAUTH_DISCOVERY_TIME: Duration = Duration::from_secs(5);
const MAX_OBSERVED_CHALLENGE_BYTES: usize = 16 * 1024;

pub(crate) struct McpOAuthProbeContext {
    pub(crate) http_client: Arc<dyn HttpClient>,
    pub(crate) default_headers: HeaderMap,
    pub(crate) configured_resource_origin: String,
    pub(crate) has_configured_headers: bool,
    pub(crate) redirect_mode: StreamableHttpRedirectMode,
}

/// Only an explicit login whose ordinary discovery found no published metadata
/// performs an MCP handshake. A real 401 challenge seeds reactive discovery;
/// network, protocol and deadline failures never become legacy-fallback success.
pub(crate) async fn resolve_metadata_with_mcp_challenge(
    manager: &AuthorizationManager,
    oauth_http_client: &OAuthHttpClientAdapter,
    server_url: &str,
    protocol_mode: McpProtocolMode,
    login_deadline: Instant,
) -> Result<AuthorizationMetadataResolution> {
    let discovery_started = Instant::now();
    if login_deadline <= discovery_started {
        bail!("OAuth login timed out before metadata discovery");
    }
    let deadline = discovery_started
        .checked_add(MAX_OAUTH_DISCOVERY_TIME)
        .context("MCP OAuth discovery deadline overflowed")?
        .min(login_deadline);
    let resolution = tokio::time::timeout_at(
        tokio::time::Instant::from_std(deadline),
        manager.resolve_metadata(),
    )
    .await
    .context("OAuth metadata discovery timed out")??;
    if resolution.source != AuthorizationMetadataSource::LegacyEndpointFallback {
        return Ok(resolution);
    }

    tokio::time::timeout_at(tokio::time::Instant::from_std(deadline), async {
        let challenge = observe_mcp_challenge(
            oauth_http_client.mcp_probe_context(),
            server_url,
            protocol_mode,
            deadline,
        )
        .await?;
        match challenge {
            Some(challenge) => manager
                .resolve_metadata_from_challenge(Some(&challenge))
                .await
                .map_err(Into::into),
            None => Ok(resolution),
        }
    })
    .await
    .context("MCP OAuth challenge discovery timed out")?
}

async fn observe_mcp_challenge(
    context: McpOAuthProbeContext,
    server_url: &str,
    protocol_mode: McpProtocolMode,
    deadline: Instant,
) -> Result<Option<String>> {
    if Url::parse(server_url)?.origin().ascii_serialization() != context.configured_resource_origin
    {
        bail!("MCP OAuth challenge resource origin changed");
    }
    let http_client = RestrictedMcpProbeClient {
        inner: context.http_client,
        configured_resource_origin: context.configured_resource_origin,
        deadline,
    };
    let adapter = StreamableHttpClientAdapter::new(
        Arc::new(http_client),
        context.default_headers,
        /*auth_provider*/ None,
        context.has_configured_headers,
        context.redirect_mode,
        Arc::new(Mutex::new(Some(deadline))),
    );
    let transport = StreamableHttpClientTransport::with_client(
        adapter,
        StreamableHttpClientTransportConfig::with_uri(server_url.to_owned())
            .reinit_on_expired_session(/*enable*/ false),
    );
    let service = LoggingClientHandler::new(
        ClientConfig::new(
            ClientCapabilities::default(),
            Implementation::new("codex-mcp-client", env!("CARGO_PKG_VERSION")).with_title("Codex"),
        )
        .with_protocol_version(ProtocolVersion::V_2025_06_18),
        Box::new(|_, _| {
            Box::pin(async { bail!("OAuth discovery does not accept elicitation requests") })
        }),
    );

    match service
        .serve_with_lifecycle(transport, protocol_mode.client_lifecycle())
        .await
    {
        Ok(mut service) => {
            // Drop only requests asynchronous cancellation in rmcp. Await the
            // successful probe's original service and transport cleanup within
            // the caller's same discovery deadline before returning no challenge.
            match service
                .close()
                .await
                .context("failed to close MCP OAuth probe")?
            {
                QuitReason::Closed | QuitReason::Cancelled => Ok(None),
                QuitReason::JoinError(error) => {
                    Err(error).context("MCP OAuth probe cleanup failed")
                }
                _ => bail!("MCP OAuth probe returned an unsupported cleanup outcome"),
            }
        }
        Err(error) => {
            let Some(challenge) = observed_challenge(&error) else {
                return Err(error.into());
            };
            if challenge.is_empty() || challenge.len() > MAX_OBSERVED_CHALLENGE_BYTES {
                bail!("MCP OAuth challenge has an invalid length");
            }
            Ok(Some(challenge.to_owned()))
        }
    }
}

fn observed_challenge(error: &ClientInitializeError) -> Option<&str> {
    match error {
        ClientInitializeError::LegacyFallbackFailed { fallback, .. } => {
            observed_challenge(fallback)
        }
        ClientInitializeError::TransportError { error, .. } => match error
            .error
            .downcast_ref::<StreamableHttpError<StreamableHttpClientAdapterError>>()
        {
            Some(StreamableHttpError::AuthRequired(error)) => Some(&error.www_authenticate_header),
            _ => None,
        },
        _ => None,
    }
}

struct RestrictedMcpProbeClient {
    inner: Arc<dyn HttpClient>,
    configured_resource_origin: String,
    deadline: Instant,
}

impl HttpClient for RestrictedMcpProbeClient {
    fn http_request(
        &self,
        _params: HttpRequestParams,
    ) -> BoxFuture<'_, std::result::Result<HttpRequestResponse, ExecServerError>> {
        Box::pin(async {
            Err(ExecServerError::Protocol(
                "MCP OAuth challenge requires streamed restricted HTTP".to_string(),
            ))
        })
    }

    fn http_request_stream(
        &self,
        mut params: HttpRequestParams,
    ) -> BoxFuture<
        '_,
        std::result::Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>,
    > {
        Box::pin(async move {
            let remaining = self
                .deadline
                .checked_duration_since(Instant::now())
                .filter(|remaining| remaining.as_millis() > 0)
                .ok_or_else(|| {
                    ExecServerError::HttpRequest(
                        "MCP OAuth challenge discovery timed out".to_string(),
                    )
                })?;
            let remaining_ms = u64::try_from(remaining.as_millis()).map_err(|error| {
                ExecServerError::HttpRequest(format!(
                    "MCP OAuth challenge timeout overflowed: {error}"
                ))
            })?;
            params.timeout_ms = Some(params.timeout_ms.unwrap_or(remaining_ms).min(remaining_ms));
            params.stream_response = true;
            self.inner
                .http_request_stream_restricted(HttpRequestRestrictedParams {
                    request: params,
                    configured_resource_origin: self.configured_resource_origin.clone(),
                    authorization_origins: Default::default(),
                })
                .await
        })
    }
}

#[cfg(test)]
#[path = "oauth_reactive_discovery_tests.rs"]
mod tests;
