//! Named all-or-none product entrypoint for canonical Agentd execution.
//!
//! The ordinary `run` entrypoint remains available for the explicit
//! compatibility profile. A canonical product host must instead consume the
//! complete typed bootstrap and start the daemon in one operation, so callers
//! cannot install a subset of runner/provider/Neuron/runtime.codex/final-use
//! owners and later mistake that partial process for a canonical profile.

use codex_arg0::Arg0DispatchPaths;

use crate::AgentdCanonicalRuntimeBootstrapV1;
use crate::AgentdConfig;
use crate::AgentdError;

/// One-shot owner of the complete canonical Agentd product composition.
///
/// Construction is inert. `run` consumes both the host and bootstrap, performs
/// the all-or-none installation, and immediately transfers the resulting
/// configuration into the daemon lifecycle. There is no API to retrieve a
/// partially installed `AgentdConfig` from this type.
pub struct AgentdCanonicalProductHostV1 {
    config: AgentdConfig,
    bootstrap: AgentdCanonicalRuntimeBootstrapV1,
}

impl AgentdCanonicalProductHostV1 {
    pub fn new(config: AgentdConfig, bootstrap: AgentdCanonicalRuntimeBootstrapV1) -> Self {
        Self { config, bootstrap }
    }

    pub fn identity(&self) -> &crate::AgentdIdentity {
        self.config.identity()
    }

    pub async fn run(self, arg0_paths: Arg0DispatchPaths) -> Result<(), AgentdError> {
        let config = self.bootstrap.install(self.config)?;
        crate::runtime::run(config, arg0_paths).await
    }
}

/// Convenience entrypoint for a trusted embedding that already owns all typed
/// canonical dependencies. Compatibility callers must continue to call
/// `crate::run` explicitly; this function never falls back to a partial or
/// compatibility composition.
pub async fn run_canonical_product(
    config: AgentdConfig,
    bootstrap: AgentdCanonicalRuntimeBootstrapV1,
    arg0_paths: Arg0DispatchPaths,
) -> Result<(), AgentdError> {
    AgentdCanonicalProductHostV1::new(config, bootstrap)
        .run(arg0_paths)
        .await
}
