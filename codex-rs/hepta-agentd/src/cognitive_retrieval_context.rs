//! Host-owned currentness for generation-bound memory retrieval.
//!
//! Context content and publication lifecycle are different identities. The
//! named Agentd caller uses acquire_context at acquisition, publication and
//! final use. A renewal must invalidate old bindings even with identical text.

use codex_hepta_contracts::AgentId;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_types::Digest32;

/// Read capability supplied by trusted host composition, not by request data.
/// Implementations authenticate their current owner independently, bound all
/// blocking I/O, and fail closed on expiry, rollback or revocation. This port
/// cannot publish, renew, rotate or revoke another owner's state.
pub trait CurrentMemoryRetrievalContext: Send + Sync {
    /// Delivery arm is fixed by the host. Shadow observations are not exposure.
    fn delivers_hnmf(&self, _owner: &AgentId) -> bool {
        true
    }

    fn current(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<RetrievalExecutionContextV1, String>;

    /// Atomically return payload, lifecycle binding and absolute lease deadline.
    /// The binding must cover the payload AND publication epoch/sequence/lease.
    /// Separate current/epoch/deadline reads are not an atomic observation.
    /// The legacy default preserves the prior payload-only host contract; None
    /// is explicitly NOT evidence of a signed product lease.
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
}
