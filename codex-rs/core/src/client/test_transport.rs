//! An owned transport attachment for hermetic first-party HTTP fixtures.
//!
//! Like the rest of `test_support`, this module is compiled into the library.
//! It is not a configuration option or a release-build authorization mechanism.
//! A fixture must supply an already-bound loopback listener, which stays owned
//! for the attachment's lifetime. No URL, provider name, or serialized flag can
//! create this attachment.

use crate::config::Config;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::ThreadStartInput;
use codex_model_provider_info::ModelProviderInfo;
use codex_model_provider_info::OPENAI_API_BASE_URL;
use std::io;
use std::net::SocketAddr;
use std::net::TcpListener;
use std::sync::Arc;

/// Keeps one test's actual listener alive while its requests are forwarded.
///
/// The logical request still uses the exact first-party endpoint and passes
/// the unchanged metadata policy. Only the final HTTP transport replaces its
/// destination with this listener. This does not exercise production TLS or
/// authenticate a live first-party service.
#[derive(Clone, Debug)]
pub struct FirstPartyTestTransport {
    listener: Arc<TcpListener>,
    address: SocketAddr,
}

impl FirstPartyTestTransport {
    /// Takes ownership of a bound listener, rejecting non-loopback bindings.
    /// Pass a clone of the same listener to the fixture's HTTP server.
    pub fn from_loopback_listener(listener: TcpListener) -> io::Result<Self> {
        let address = listener.local_addr()?;
        if !address.ip().is_loopback() || address.port() == 0 {
            return Err(io::Error::other(
                "fixture listener must be bound to loopback",
            ));
        }
        Ok(Self {
            listener: Arc::new(listener),
            address,
        })
    }

    /// Returns the address of the listener retained by this fixture.
    pub fn address(&self) -> SocketAddr {
        self.address
    }

    pub(crate) fn validate_provider(&self, provider: &ModelProviderInfo) -> io::Result<()> {
        if provider.base_url.as_deref() != Some(OPENAI_API_BASE_URL) || provider.supports_websockets
        {
            return Err(io::Error::other(
                "first-party HTTP fixture requires the exact OpenAI base URL and HTTP transport",
            ));
        }
        Ok(())
    }

    pub(crate) fn physical_url(&self, logical_url: &str) -> io::Result<String> {
        let path = match logical_url.strip_prefix(OPENAI_API_BASE_URL) {
            Some("/responses") => "/v1/responses",
            Some("/responses/compact") => "/v1/responses/compact",
            _ => {
                return Err(io::Error::other(
                    "first-party HTTP fixture refuses this logical origin or path",
                ));
            }
        };
        // The listener is retained, so a stopped server cannot release this
        // port to an unrelated process while a child or resumed thread uses it.
        if self.listener.local_addr()? != self.address {
            return Err(io::Error::other("fixture listener identity changed"));
        }
        Ok(format!("http://{}{path}", self.address))
    }
}

impl ThreadLifecycleContributor<Config> for FirstPartyTestTransport {
    fn on_thread_start<'a>(
        &'a self,
        input: ThreadStartInput<'a, Config>,
    ) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            input.thread_store.insert(self.clone());
        })
    }
}
