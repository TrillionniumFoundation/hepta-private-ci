//! Explicit fixture capabilities for cross-crate tests.
//!
//! Ordinary clients never construct this lease. The hidden test-support bridge
//! binds one fixture lineage to a complete provider configuration and an exact,
//! literal loopback endpoint. It is not a provider setting or a URL registry.

use codex_model_provider_info::ModelProviderInfo;
use codex_model_provider_info::OPENAI_PROVIDER_ID;
use std::fmt;
use std::sync::Arc;
use url::Host;
use url::Url;

pub(crate) struct OpenAiFixtureMetadataLease {
    provider_id: String,
    provider: ModelProviderInfo,
    endpoint: String,
}

impl fmt::Debug for OpenAiFixtureMetadataLease {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Provider configurations can contain credentials. The capability does
        // not expose those values or its endpoint through diagnostics.
        f.debug_struct("OpenAiFixtureMetadataLease")
            .finish_non_exhaustive()
    }
}

/// Private, nonpersistent attachment overwritten by the owning thread manager.
pub(crate) struct FixtureMetadataContext(pub(crate) Option<Arc<OpenAiFixtureMetadataLease>>);

impl OpenAiFixtureMetadataLease {
    pub(crate) fn for_owned_test_provider(
        fixture_provider: &ModelProviderInfo,
        configured_provider_id: &str,
        configured_provider: &ModelProviderInfo,
    ) -> Option<Arc<Self>> {
        let endpoint = fixture_provider.base_url.as_deref()?;
        if configured_provider_id != OPENAI_PROVIDER_ID || !is_literal_fixture_endpoint(endpoint) {
            return None;
        }

        // The builder supplies the provider it created before with_config.
        // Only its built-in OpenAI fixture may issue this capability.
        let mut expected = ModelProviderInfo::create_openai_provider(Some(endpoint.to_string()));
        expected.supports_websockets = false;
        if fixture_provider != &expected {
            return None;
        }

        // Existing tests tune transport behavior without replacing their
        // provider. These five fields do not select an endpoint or identity.
        // All other fields, including name, URL, auth, headers and wire API,
        // must still equal the builder's original fixture.
        expected.request_max_retries = configured_provider.request_max_retries;
        expected.stream_max_retries = configured_provider.stream_max_retries;
        expected.stream_idle_timeout_ms = configured_provider.stream_idle_timeout_ms;
        expected.websocket_connect_timeout_ms = configured_provider.websocket_connect_timeout_ms;
        expected.supports_websockets = configured_provider.supports_websockets;
        if configured_provider != &expected {
            return None;
        }

        Some(Arc::new(Self {
            provider_id: configured_provider_id.to_string(),
            provider: configured_provider.clone(),
            endpoint: endpoint.to_string(),
        }))
    }

    pub(crate) fn matches_config(&self, provider_id: &str, provider: &ModelProviderInfo) -> bool {
        self.provider_id == provider_id && self.matches_provider(provider)
    }

    pub(crate) fn matches_provider(&self, provider: &ModelProviderInfo) -> bool {
        self.provider == *provider
    }

    pub(crate) fn accepts_request(&self, provider: &ModelProviderInfo, endpoint: &str) -> bool {
        self.matches_provider(provider) && self.endpoint == endpoint
    }
}

fn is_literal_fixture_endpoint(endpoint: &str) -> bool {
    let Ok(url) = Url::parse(endpoint) else {
        return false;
    };
    let is_loopback = match url.host() {
        Some(Host::Ipv4(address)) => address.is_loopback(),
        Some(Host::Ipv6(address)) => address.is_loopback(),
        _ => false,
    };
    is_loopback
        && url.scheme() == "http"
        && url.port().is_some_and(|port| port != 0)
        && url.username().is_empty()
        && url.password().is_none()
        && url.path() == "/v1"
        && url.query().is_none()
        && url.fragment().is_none()
        && url.as_str() == endpoint
}

#[cfg(test)]
#[path = "fixture_metadata_tests.rs"]
mod tests;
