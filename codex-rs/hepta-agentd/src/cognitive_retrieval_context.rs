//! Explicit host-owned current context for generation-bound memory retrieval.
//!
//! The provider authenticates and freezes generations owned outside the SQLite
//! memory store. Agentd never fabricates model, prompt, encoder, compact,
//! authority, retrieval-profile, or engram generations.

use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_types::Digest32;

#[path = "product_retrieval_context.rs"]
mod product;

/// Host-owned currentness boundary for HNMF retrieval composition.
///
/// Implementations must authenticate their registry/source independently,
/// return the exact current context for the requested Agent generation, bound
/// any blocking I/O, and fail closed after revocation. Agentd compares the
/// returned context digest again immediately before response publication.
pub trait CurrentMemoryRetrievalContext: Send + Sync {
    fn current(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<RetrievalExecutionContextV1, String>;

    /// Product lifecycle methods default to unsupported so test doubles and
    /// externally managed providers remain source compatible. The product-owned
    /// provider overrides every method and fences mutations by epoch.
    fn lifecycle_epoch(&self) -> Result<u64, String> {
        Err("retrieval context provider has no product lifecycle epoch".to_string())
    }

    fn lease_expires_unix_ms(&self) -> Result<u64, String> {
        Err("retrieval context provider has no product lease".to_string())
    }

    fn context_state_digest(&self) -> Result<Digest32, String> {
        Err("retrieval context provider has no product state digest".to_string())
    }

    fn revoked(&self) -> Result<bool, String> {
        Err("retrieval context provider has no product revocation state".to_string())
    }

    fn rotate_context(
        &self,
        _expected_epoch: u64,
        _context: RetrievalExecutionContextV1,
        _lease_expires_unix_ms: u64,
    ) -> Result<u64, String> {
        Err("retrieval context provider does not support rotation".to_string())
    }

    fn renew_context(
        &self,
        _expected_epoch: u64,
        _lease_expires_unix_ms: u64,
    ) -> Result<u64, String> {
        Err("retrieval context provider does not support lease renewal".to_string())
    }

    fn revoke_context(&self, _expected_epoch: u64) -> Result<u64, String> {
        Err("retrieval context provider does not support revocation".to_string())
    }
}

impl dyn CurrentMemoryRetrievalContext {
    /// Construct the Agentd-owned provider around a fully validated generation
    /// identity. The returned trait object exposes epoch-fenced rotation,
    /// renewal, revocation and state-digest receipts through the methods above.
    pub fn product(
        owner: AgentId,
        body_generation: u64,
        context: RetrievalExecutionContextV1,
        lease_expires_unix_ms: u64,
    ) -> Result<Arc<dyn CurrentMemoryRetrievalContext>, String> {
        product::ProductMemoryRetrievalContextV1::new(
            owner,
            body_generation,
            context,
            lease_expires_unix_ms,
        )
        .map(|provider| Arc::new(provider) as Arc<dyn CurrentMemoryRetrievalContext>)
        .map_err(|error| error.to_string())
    }

    /// Recover the product provider from an independently retained state
    /// receipt. A live recovery still requires a future lease and a context
    /// whose full model/encoder/tokenizer/policy/engram binding validates.
    #[allow(clippy::too_many_arguments)]
    pub fn recover_product(
        owner: AgentId,
        body_generation: u64,
        epoch: u64,
        lease_expires_unix_ms: u64,
        context: Option<RetrievalExecutionContextV1>,
        revoked: bool,
        state_digest: Digest32,
    ) -> Result<Arc<dyn CurrentMemoryRetrievalContext>, String> {
        product::ProductMemoryRetrievalContextV1::recover(
            product::ProductRetrievalContextSnapshotV1 {
                owner,
                body_generation,
                epoch,
                lease_expires_unix_ms,
                context,
                revoked,
                state_digest,
            },
        )
        .map(|provider| Arc::new(provider) as Arc<dyn CurrentMemoryRetrievalContext>)
        .map_err(|error| error.to_string())
    }
}
