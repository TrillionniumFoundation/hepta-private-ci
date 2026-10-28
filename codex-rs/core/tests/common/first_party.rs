//! First-party HTTP wire fixtures with an explicitly owned local transport.

use crate::test_codex::TestCodexBuilder;
use crate::test_codex::test_codex;
use codex_core::test_support::FirstPartyTestTransport;
use std::net::TcpListener;
use std::ops::Deref;
use std::sync::Arc;
use wiremock::MockServer;

/// A mock server and the capability for its exact bound listener.
///
/// Requests retain the real first-party logical URL through construction and
/// metadata policy. The scoped HTTP adapter forwards their unchanged bodies
/// to this server. No assertion reconstructs or restores stripped metadata.
pub struct FirstPartyMockServer {
    server: MockServer,
    transport: Arc<FirstPartyTestTransport>,
}

impl FirstPartyMockServer {
    pub async fn start() -> anyhow::Result<Self> {
        let listener = TcpListener::bind("127.0.0.1:0")?;
        let transport = Arc::new(FirstPartyTestTransport::from_loopback_listener(
            listener.try_clone()?,
        )?);
        let server = MockServer::builder()
            .listener(listener)
            .body_print_limit(wiremock::BodyPrintLimit::Limited(80_000))
            .start()
            .await;
        anyhow::ensure!(
            server.address() == &transport.address(),
            "fixture listener mismatch"
        );
        Ok(Self { server, transport })
    }

    /// Creates a builder for this HTTP fixture and all of its child runtimes.
    /// The static catalog avoids an unrelated request to a real model endpoint.
    pub fn test_codex(&self) -> TestCodexBuilder {
        self.attach(test_codex())
    }

    /// Adds the scoped attachment while preserving this builder's existing setup.
    pub fn attach(&self, builder: TestCodexBuilder) -> TestCodexBuilder {
        builder.with_first_party_http_fixture(Arc::clone(&self.transport))
    }
}

impl Deref for FirstPartyMockServer {
    type Target = MockServer;

    fn deref(&self) -> &Self::Target {
        &self.server
    }
}
