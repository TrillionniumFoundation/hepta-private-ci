//! Type-erased production trust bootstrap for the Agentd automation effect owner.
//!
//! Deployments construct this value from one complete, already validated
//! `ProductionAuthorityTrustBundle`. Agentd retains that exact bundle and binds
//! the host-file issuer key set only while opening the single effect owner. No
//! request, adapter, or compatibility path can manufacture a production trust
//! context.

use std::fmt;
use std::sync::Arc;

use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseIssuerTrustKey;
use codex_hepta_contracts::ProductionFinalUseTrustContext;
use codex_hepta_contracts::authority_trust::ProductionAuthorityClock;
use codex_hepta_contracts::authority_trust::ProductionAuthorityFrontierStore;
use codex_hepta_contracts::authority_trust::ProductionAuthorityKeyCustody;
use codex_hepta_contracts::authority_trust::ProductionAuthorityTrustBundle;

type BindProductionFinalUse = dyn Fn(&[FinalUseIssuerTrustKey]) -> Result<ProductionFinalUseTrustContext, FinalUseError>
    + Send
    + Sync;

/// One retained production trust bundle for the Agentd automation effect owner.
#[derive(Clone)]
pub struct AgentdProductionAuthorityBootstrap {
    bind_final_use: Arc<BindProductionFinalUse>,
}

impl fmt::Debug for AgentdProductionAuthorityBootstrap {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("AgentdProductionAuthorityBootstrap([REDACTED LIVE TRUST])")
    }
}

impl AgentdProductionAuthorityBootstrap {
    /// Retain one complete production bundle behind the normal Agentd startup
    /// path. The bundle is never reconstructed from host-file or request data.
    pub fn from_trust_bundle<C, S, K>(
        bundle: ProductionAuthorityTrustBundle<C, S, K, FinalUseFrontier>,
    ) -> Self
    where
        C: ProductionAuthorityClock + 'static,
        S: ProductionAuthorityFrontierStore<FinalUseFrontier> + 'static,
        K: ProductionAuthorityKeyCustody + 'static,
    {
        let bundle = Arc::new(bundle);
        let bind_final_use = Arc::new(move |issuer_keys: &[FinalUseIssuerTrustKey]| {
            ProductionFinalUseTrustContext::bind(issuer_keys, bundle.as_ref())
        });
        Self { bind_final_use }
    }

    pub(crate) fn bind(
        &self,
        issuer_keys: &[FinalUseIssuerTrustKey],
    ) -> Result<ProductionFinalUseTrustContext, FinalUseError> {
        (self.bind_final_use)(issuer_keys)
    }
}
