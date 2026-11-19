//! Preserve the normal transport, with an explicit owned fixture alternative.

use super::test_transport::FirstPartyTestTransport;
use codex_http_client::HttpClientBuilder;
use codex_http_client::HttpTransport;
use codex_http_client::Request;
use codex_http_client::ReqwestTransport;
use codex_http_client::Response;
use codex_http_client::StreamResponse;
use codex_http_client::TransportError;
use std::sync::Arc;

pub(super) struct ModelApiTransport {
    inner: ReqwestTransport,
    fixture: Option<Arc<FirstPartyTestTransport>>,
}

impl ModelApiTransport {
    pub(super) fn production(inner: ReqwestTransport) -> Self {
        Self {
            inner,
            fixture: None,
        }
    }

    pub(super) fn for_fixture(
        fixture: Arc<FirstPartyTestTransport>,
        logical_url: &str,
    ) -> std::io::Result<Self> {
        fixture.physical_url(logical_url)?;
        // This is the builder's documented hermetic-test exception. Neither
        // ambient proxies nor a server redirect may receive the request.
        let client = HttpClientBuilder::new()
            .without_redirects()
            .without_request_logging()
            .build_direct()
            .map_err(std::io::Error::other)?;
        Ok(Self {
            inner: ReqwestTransport::from_http_client(client),
            fixture: Some(fixture),
        })
    }

    fn destination(&self, mut request: Request) -> Result<Request, TransportError> {
        if let Some(fixture) = &self.fixture {
            // Validate the final owned request again after authentication.
            // Its body, headers, compression, method, and timeout are unchanged.
            request.url = fixture
                .physical_url(&request.url)
                .map_err(|error| TransportError::Build(error.to_string()))?;
        }
        Ok(request)
    }
}

impl HttpTransport for ModelApiTransport {
    async fn execute(&self, request: Request) -> Result<Response, TransportError> {
        self.inner.execute(self.destination(request)?).await
    }

    async fn stream(&self, request: Request) -> Result<StreamResponse, TransportError> {
        self.inner.stream(self.destination(request)?).await
    }
}
