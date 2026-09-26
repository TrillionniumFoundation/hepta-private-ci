//! Host-owned currentness for generation-bound memory retrieval.
//!
//! Payload hashes identify content; product read bindings additionally identify
//! the lease and lifecycle epoch. Provider composition is a trusted host task.

use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_types::Digest32;

#[path = "product_retrieval_context.rs"]
mod product;

pub use product::ProductRetrievalContextControlV1;
pub use product::ProductRetrievalContextSnapshotV1;
pub use product::RetrievalRecoveryWitnessV1;

/// Read capability. Possession does not confer product lifecycle write access.
pub trait CurrentMemoryRetrievalContext: Send + Sync {
    /// Trusted composition selects delivery; a request cannot select its arm.
    fn delivers_hnmf(&self, _owner: &AgentId) -> bool {
        true
    }

    fn current(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<RetrievalExecutionContextV1, String>;

    /// Return one atomic observation: payload, lifecycle binding and lease.
    /// Legacy providers retain their payload-only contract; None is not proof
    /// of a durable product lease. Product implementations override this method.
    fn acquire_context(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<(RetrievalExecutionContextV1, Digest32, Option<u64>), String> {
        let context = self.current(owner, body_generation)?;
        context.validate().map_err(|error| error.to_string())?;
        let binding = context.binding_digest();
        Ok((context, binding, None))
    }

    fn lifecycle_epoch(&self) -> Result<u64, String> {
        Err("provider has no product lifecycle epoch".to_string())
    }

    fn lease_expires_unix_ms(&self) -> Result<u64, String> {
        Err("provider has no product lease".to_string())
    }

    fn context_state_digest(&self) -> Result<Digest32, String> {
        Err("provider has no product state digest".to_string())
    }

    fn revoked(&self) -> Result<bool, String> {
        Err("provider has no product revocation state".to_string())
    }

    // Kept for source compatibility. The product reader does not override these.
    fn rotate_context(
        &self,
        _expected_epoch: u64,
        _context: RetrievalExecutionContextV1,
        _lease_expires_unix_ms: u64,
    ) -> Result<u64, String> {
        Err("rotation requires the protected product control capability".to_string())
    }

    fn renew_context(
        &self,
        _expected_epoch: u64,
        _lease_expires_unix_ms: u64,
    ) -> Result<u64, String> {
        Err("renewal requires the protected product control capability".to_string())
    }

    fn revoke_context(&self, _expected_epoch: u64) -> Result<u64, String> {
        Err("revocation requires the protected product control capability".to_string())
    }
}

impl dyn CurrentMemoryRetrievalContext {
    pub fn product(
        owner: AgentId,
        body_generation: u64,
        context: RetrievalExecutionContextV1,
        lease_expires_unix_ms: u64,
    ) -> Result<Arc<dyn CurrentMemoryRetrievalContext>, String> {
        Self::product_with_control(owner, body_generation, context, lease_expires_unix_ms)
            .map(|(reader, _control)| reader)
    }

    /// The composition root must retain the control handle outside request code.
    pub fn product_with_control(
        owner: AgentId,
        body_generation: u64,
        context: RetrievalExecutionContextV1,
        lease_expires_unix_ms: u64,
    ) -> Result<
        (
            Arc<dyn CurrentMemoryRetrievalContext>,
            ProductRetrievalContextControlV1,
        ),
        String,
    > {
        let provider = Arc::new(product::ProductMemoryRetrievalContextV1::new(
            owner,
            body_generation,
            context,
            lease_expires_unix_ms,
        )?);
        let control = ProductRetrievalContextControlV1::from_provider(Arc::clone(&provider));
        Ok((provider, control))
    }

    /// A self-consistent historical hash is not an anti-rollback witness.
    #[allow(clippy::too_many_arguments)]
    pub fn recover_product(
        _owner: AgentId,
        _body_generation: u64,
        _epoch: u64,
        _lease_expires_unix_ms: u64,
        _context: Option<RetrievalExecutionContextV1>,
        _revoked: bool,
        _state_digest: Digest32,
    ) -> Result<Arc<dyn CurrentMemoryRetrievalContext>, String> {
        Err("recovery requires an independently current owner witness".to_string())
    }

    pub fn recover_product_with_witness(
        snapshot: ProductRetrievalContextSnapshotV1,
        witness: &dyn RetrievalRecoveryWitnessV1,
    ) -> Result<
        (
            Arc<dyn CurrentMemoryRetrievalContext>,
            ProductRetrievalContextControlV1,
        ),
        String,
    > {
        let provider = Arc::new(product::ProductMemoryRetrievalContextV1::recover(
            snapshot, witness,
        )?);
        let control = ProductRetrievalContextControlV1::from_provider(Arc::clone(&provider));
        Ok((provider, control))
    }
}
