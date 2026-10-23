use std::sync::Arc;

use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderSha256Digest;
use codex_hepta_contracts::ProviderInvocationIntent;

type Authorize = dyn Fn(
        ProviderInvocationIntent,
        ModelProviderSha256Digest,
        u64,
    ) -> ModelProviderPolicyFuture<'static, ()>
    + Send
    + Sync;

/// Embedding-owned late check on the same durable provider attempt. This
/// capability alone proves no model load, CURRENT selection or resource closure.
#[derive(Clone)]
pub struct ProviderRequestEnforcementHost(Arc<Authorize>);

impl ProviderRequestEnforcementHost {
    /// An explicit unavailable capability never degrades to observation mode.
    pub fn unavailable() -> Self {
        Self::from_fn(|_, _, _| {
            Box::pin(async {
                Err(codex_extension_api::ModelProviderPolicyError::new(
                    "hepta_provider_request_host_unavailable",
                    "provider request host is unavailable",
                ))
            })
        })
    }

    pub fn from_fn<F>(authorize: F) -> Self
    where
        F: Fn(
                ProviderInvocationIntent,
                ModelProviderSha256Digest,
                u64,
            ) -> ModelProviderPolicyFuture<'static, ()>
            + Send
            + Sync
            + 'static,
    {
        Self(Arc::new(authorize))
    }

    pub(crate) fn authorize(
        &self,
        intent: ProviderInvocationIntent,
        digest: ModelProviderSha256Digest,
        bytes: u64,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        (self.0)(intent, digest, bytes)
    }
}

impl std::fmt::Debug for ProviderRequestEnforcementHost {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("ProviderRequestEnforcementHost(<opaque>)")
    }
}

impl PartialEq for ProviderRequestEnforcementHost {
    fn eq(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.0, &other.0)
    }
}
impl Eq for ProviderRequestEnforcementHost {}
